from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import sqlite3

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from scipy import optimize

from investment_optimiser.dmo_d10c import get_latest_observed_inflation
from investment_optimiser.observed_inflation_resolver import (
    InflationResolutionError,
    resolve_il_contract,
)

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

    times = r / s + np.arange(n + 1)
    cash_flows = np.full(n + 1, d2)
    cash_flows[0] = d1
    cash_flows[-1] += 100.0
    discount = v**times
    pv_weighted = np.sum(times * cash_flows * discount)
    macaulay_semi = pv_weighted / dirty_price
    mod_dur = (macaulay_semi / f) / (1.0 + y / f)

    return y, mod_dur


def clean_price_from_gry(
    gry_pct: float,
    coupon_pct: float,
    maturity_date: date,
    settlement_date: date,
) -> float | None:
    """Forward formula: given GRY return clean price per £100 nominal."""
    prev_coupon, future_coupons = coupon_dates(maturity_date, settlement_date)
    if not future_coupons:
        return None

    next_coupon = future_coupons[0]
    xd = ex_dividend_date(next_coupon)
    accrued = _accrued_interest(coupon_pct, prev_coupon, next_coupon, settlement_date, xd)

    c = coupon_pct
    f = 2.0
    d1 = c / f
    d2 = c / f
    n = len(future_coupons) - 1

    r = (next_coupon - settlement_date).days
    s = (next_coupon - prev_coupon).days

    if settlement_date > xd:
        d1 = 0.0

    try:
        v = 1.0 / (1.0 + gry_pct / f)
        if n == 0:
            dirty_price = (d1 + 100.0) * v ** (r / s)
        else:
            dirty_price = v ** (r / s) * (
                d1
                + d2 * v
                + c * v**2 / (f * (1 - v)) * (1 - v ** (n - 1))
                + 100.0 * v**n
            )
    except (ZeroDivisionError, ValueError, OverflowError):
        return None

    clean_price = dirty_price - accrued
    return clean_price if clean_price > 0 else None


def _solve_negative_real_yield(
    clean_price_per_100: float,
    coupon_pct: float,
    maturity_date: date,
    settlement_date: date,
) -> float | None:
    """Brentq solve for IL gilts whose real price just exceeds the undiscounted cash-flow sum.

    compute_gry only searches v ∈ [0.01, 0.9999] (positive yields). For IL gilts
    with near-zero or negative real yields, v > 1. This function searches v ∈ (1, 1.15],
    corresponding to real yields down to roughly −27%, which is sufficient in practice.
    """
    prev_coupon, future_coupons = coupon_dates(maturity_date, settlement_date)
    if not future_coupons:
        return None
    next_coupon = future_coupons[0]
    xd = ex_dividend_date(next_coupon)
    accrued = _accrued_interest(coupon_pct, prev_coupon, next_coupon, settlement_date, xd)
    dirty_price = clean_price_per_100 + accrued
    if dirty_price <= 0:
        return None

    c = coupon_pct
    f = 2.0
    d1 = 0.0 if settlement_date > xd else c / f
    d2 = c / f
    n = len(future_coupons) - 1
    r = (next_coupon - settlement_date).days
    s = (next_coupon - prev_coupon).days

    if n == 0:
        try:
            y = f * (((d1 + 100.0) / dirty_price) ** (s / r) - 1.0)
            return y if y < 0 else None
        except Exception:
            return None

    def fn(v: float) -> float:
        return (
            v ** (r / s)
            * (d1 + d2 * v + c * v**2 / (f * (1 - v)) * (1 - v ** (n - 1)) + 100.0 * v**n)
            - dirty_price
        )

    try:
        v = optimize.brentq(fn, 1.001, 1.15)
        y = (1.0 / v - 1.0) * f
        return y if y < 0 else None
    except (RuntimeError, ValueError):
        return None


def compute_real_gry(
    clean_price_per_100: float,
    coupon_pct: float,
    maturity_date: date,
    settlement_date: date,
    rpi_assumption_pct: float,
) -> tuple[float, float] | tuple[None, None]:
    """Real GRY for an IL gilt and Fisher nominal-equivalent yield (decimal, e.g. 0.05 = 5%)."""
    real_gry, _ = compute_gry(clean_price_per_100, coupon_pct, maturity_date, settlement_date)
    if real_gry is None:
        real_gry = _solve_negative_real_yield(
            clean_price_per_100, coupon_pct, maturity_date, settlement_date
        )
    if real_gry is None:
        return None, None
    # real_gry is decimal; rpi_assumption_pct is %; exact semi-annual Fisher: (1+n/2)=(1+r/2)*(1+i/2)
    nominal_equiv = 2.0 * ((1.0 + real_gry / 2.0) * (1.0 + rpi_assumption_pct / 200.0) - 1.0)
    return real_gry, nominal_equiv


_BENCHMARK_MATURITIES: dict[str, float] = {
    "lse_derived_1y": 1.0,
    "lse_derived_2y": 2.0,
    "lse_derived_5y": 5.0,
    "lse_derived_10y": 10.0,
    "lse_derived_30y": 30.0,
}


def _derive_benchmark_yields(
    connection: sqlite3.Connection, cache_date: str, fetched_at: str
) -> None:
    rows = connection.execute(
        """
        SELECT isin, gry_pct, maturity_date
        FROM gilt_price_cache
        WHERE cache_date = ? AND gry_pct IS NOT NULL
        ORDER BY maturity_date ASC
        """,
        (cache_date,),
    ).fetchall()

    if not rows:
        return

    today = date.fromisoformat(cache_date)
    benchmark_rows = []
    for curve_key, target_years in _BENCHMARK_MATURITIES.items():
        best = min(
            rows,
            key=lambda r, ty=target_years: abs(
                (date.fromisoformat(r[2]) - today).days / 365.25 - ty
            ),
        )
        # yield_curve_cache stores rates as percentage (e.g. 4.96 for 4.96%),
        # consistent with the BoE series; gry_pct is decimal so multiply by 100.
        benchmark_rows.append((
            cache_date,
            curve_key,
            target_years,
            float(best[1]) * 100.0,
            "LSE_DERIVED",
            fetched_at,
        ))

    connection.executemany(
        """
        INSERT OR REPLACE INTO yield_curve_cache
            (cache_date, curve_key, maturity_years, rate_pct, series_code, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        benchmark_rows,
    )


def gilt_analytics_handler(
    connection: sqlite3.Connection,
    forward_rpi_pre_2030_pct: float | None = None,
    forward_rpi_post_2030_pct: float | None = None,
) -> list[str]:
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

    observed_by_isin = {
        row["isin"]: row for row in get_latest_observed_inflation(connection)
    }

    il_rows = connection.execute(
        """
        SELECT gpc.isin, gpc.clean_price_gbp, gpc.coupon_pct, gpc.maturity_date
        FROM gilt_price_cache gpc
        JOIN gilt_reference gr ON gr.isin = gpc.isin
        WHERE gpc.cache_date = ? AND gpc.nominal_equivalent_gry_pct IS NULL
          AND gr.instrument_type = 'Index-linked'
        """,
        (cache_date,),
    ).fetchall()

    il_updates: list[tuple[float, float, str, str]] = []
    il_exclusion_updates: list[tuple[str, str, str]] = []
    for isin, clean_price, coupon_pct, maturity_date_str in il_rows:
        maturity = date.fromisoformat(maturity_date_str)
        contract = resolve_il_contract(
            isin=isin,
            settlement_date=settlement,
            maturity_date=maturity,
            observed_row=observed_by_isin.get(isin),
            forward_rpi_pre_2030_pct=forward_rpi_pre_2030_pct,
            forward_rpi_post_2030_pct=forward_rpi_post_2030_pct,
        )
        if isinstance(contract, InflationResolutionError):
            warnings.append(contract.warning)
            il_exclusion_updates.append((contract.warning, cache_date, isin))
            continue
        result = compute_real_gry(
            clean_price, coupon_pct, maturity, settlement,
            contract.effective_forward_rpi_pct,
        )
        if result == (None, None):
            reason = f"{isin} real GRY solve failed: no convergence"
            warnings.append(reason)
            il_exclusion_updates.append((reason, cache_date, isin))
            continue
        real_gry, nominal_equiv = result
        il_updates.append((real_gry, nominal_equiv, cache_date, isin))

    if il_updates:
        connection.executemany(
            """
            UPDATE gilt_price_cache
            SET real_gry_pct = ?, nominal_equivalent_gry_pct = ?, il_exclusion_reason = NULL
            WHERE cache_date = ? AND isin = ?
            """,
            il_updates,
        )

    if il_exclusion_updates:
        connection.executemany(
            """
            UPDATE gilt_price_cache
            SET il_exclusion_reason = ?
            WHERE cache_date = ? AND isin = ?
            """,
            il_exclusion_updates,
        )

    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _derive_benchmark_yields(connection, cache_date, fetched_at)
    return warnings
