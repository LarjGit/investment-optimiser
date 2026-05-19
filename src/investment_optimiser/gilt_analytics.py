from __future__ import annotations

from datetime import date, timedelta
import sqlite3

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from scipy import optimize

try:
    from govuk_bank_holidays.bank_holidays import BankHolidays

    _holidays = [h["date"] for h in BankHolidays(division="england-and-wales").get_holidays()]
    UK_BUS_DAY = pd.offsets.CustomBusinessDay(holidays=_holidays)
except Exception:
    UK_BUS_DAY = pd.offsets.BusinessDay()


def settlement_date_for(trade_date: date) -> date:
    return (pd.Timestamp(trade_date) + UK_BUS_DAY).date()


def coupon_dates(maturity_date: date, settlement_date: date) -> tuple[date, list[date]]:
    dates = [maturity_date]
    while dates[-1] > settlement_date - relativedelta(months=6):
        dates.append(dates[-1] - relativedelta(months=6))
    dates.reverse()
    prev = max(d for d in dates if d <= settlement_date)
    future = [d for d in dates if d > settlement_date]
    return prev, future


def ex_dividend_date(next_coupon_date: date) -> date:
    try:
        return (pd.Timestamp(next_coupon_date) - 7 * UK_BUS_DAY).date()
    except Exception:
        return next_coupon_date - timedelta(days=10)


def _accrued_interest(
    coupon_pct: float,
    prev_coupon: date,
    next_coupon: date,
    settlement_date: date,
    xd_date: date,
) -> float:
    dividend = coupon_pct / 2.0
    s = (next_coupon - prev_coupon).days
    r_days = (settlement_date - prev_coupon).days
    accrued_fraction = r_days / s
    if settlement_date > xd_date:
        accrued_fraction -= 1.0
    return accrued_fraction * dividend


def compute_gry(
    clean_price_per_100: float,
    coupon_pct: float,
    maturity_date: date,
    settlement_date: date,
) -> tuple[float, float] | tuple[None, None]:
    prev_coupon, future_coupons = coupon_dates(maturity_date, settlement_date)
    if not future_coupons:
        return None, None
    next_coupon = future_coupons[0]
    xd = ex_dividend_date(next_coupon)

    accrued = _accrued_interest(coupon_pct, prev_coupon, next_coupon, settlement_date, xd)
    dirty_price = clean_price_per_100 + accrued

    if dirty_price <= 0:
        return None, None

    c = coupon_pct
    f = 2.0
    d1 = c / f
    d2 = c / f
    n = len(future_coupons) - 1

    r = (next_coupon - settlement_date).days
    s = (next_coupon - prev_coupon).days

    if settlement_date > xd:
        d1 = 0.0

    if n == 0:
        try:
            y = f * (((d1 + 100.0) / dirty_price) ** (s / r) - 1.0)
            t = r / s
            mod_dur = (t / f) / (1 + y / f)
            return y, mod_dur
        except Exception:
            return None, None

    def fn(v: float) -> float:
        return (
            v ** (r / s)
            * (
                d1
                + d2 * v
                + c * v**2 / (f * (1 - v)) * (1 - v ** (n - 1))
                + 100.0 * v**n
            )
            - dirty_price
        )

    v0 = 1.0 / (1.0 + 0.05 / f)

    try:
        v = optimize.newton(fn, v0)
        if not (0.01 <= v <= 0.9999):
            raise RuntimeError("solution outside valid discount-factor range")
    except RuntimeError:
        try:
            v = optimize.brentq(fn, 0.01, 0.9999)
        except (RuntimeError, ValueError):
            return None, None

    y = (1.0 / v - 1.0) * f

    times = np.arange(r / s, r / s + n + 1)
    cash_flows = np.full(n + 1, d2)
    cash_flows[0] = d1
    cash_flows[-1] += 100.0
    discount = v**times
    pv_weighted = np.sum(times * cash_flows * discount)
    macaulay_semi = pv_weighted / dirty_price
    mod_dur = (macaulay_semi / f) / (1.0 + y / f)

    return y, mod_dur


def gilt_analytics_handler(connection: sqlite3.Connection) -> list[str]:
    cache_date = date.today().isoformat()
    settlement = settlement_date_for(date.today())
    warnings: list[str] = []
    updates: list[tuple[float, float, str, str]] = []

    rows = connection.execute(
        """
        SELECT gpc.isin, gpc.clean_price_gbp, gpc.coupon_pct, gpc.maturity_date
        FROM gilt_price_cache gpc
        JOIN gilt_reference gr ON gr.isin = gpc.isin
        WHERE gpc.cache_date = ? AND gpc.gry_pct IS NULL
          AND gr.instrument_type = 'Conventional'
        """,
        (cache_date,),
    ).fetchall()

    for isin, clean_price, coupon_pct, maturity_date_str in rows:
        maturity = date.fromisoformat(maturity_date_str)
        result = compute_gry(clean_price, coupon_pct, maturity, settlement)
        if result == (None, None):
            warnings.append(f"{isin} GRY solve failed: no convergence")
            continue
        gry, mod_dur = result
        updates.append((gry, mod_dur, cache_date, isin))

    if updates:
        connection.executemany(
            """
            UPDATE gilt_price_cache
            SET gry_pct = ?, modified_duration_years = ?
            WHERE cache_date = ? AND isin = ?
            """,
            updates,
        )
    return warnings
