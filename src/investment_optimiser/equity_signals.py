from __future__ import annotations

import datetime
from dataclasses import dataclass
import sqlite3

import pandas as pd

try:
    from govuk_bank_holidays.bank_holidays import BankHolidays
    _bh = BankHolidays()
    _UK_HOLIDAYS: set[datetime.date] = {
        h["date"]
        for h in _bh.get_holidays(division=BankHolidays.ENGLAND_AND_WALES)
    }
except Exception:
    _UK_HOLIDAYS = set()


ERP_STALE_TRADING_DAYS = 5
CURVE_FLAT_THRESHOLD_BPS = 10.0
CURVE_PERSISTENCE_DAYS = 5


@dataclass(frozen=True)
class YieldCurveSignal:
    state: str
    curve_state: str | None
    consecutive_days: int | None
    spread_bps: float | None
    five_year_pct: float | None
    ten_year_pct: float | None
    twenty_year_pct: float | None
    cache_date: str | None
    explanation: str


@dataclass(frozen=True)
class ErpSignal:
    state: str
    erp_pct: float | None
    earnings_yield_pct: float | None
    best_gilt_gry_pct: float | None
    explanation: str


def fetch_equity_valuation(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        """
        SELECT cache_date, source_name, pe_ratio, pe_as_of, fetched_at
        FROM equity_valuation_cache
        WHERE source_name = 'yfinance_equities'
        ORDER BY cache_date DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "cache_date": row[0],
        "source_name": row[1],
        "pe_ratio": row[2],
        "pe_as_of": row[3],
        "fetched_at": row[4],
    }


def fetch_best_conventional_gry(connection: sqlite3.Connection) -> float | None:
    row = connection.execute(
        """
        SELECT MAX(p.gry_pct)
        FROM gilt_price_cache p
        JOIN gilt_reference r ON r.isin = p.isin
        WHERE r.instrument_type = 'Conventional'
          AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
        """
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def trading_days_since(cache_date: str) -> int:
    """Approximate Mon–Fri count; no UK bank-holiday awareness."""
    today = datetime.date.today().isoformat()
    if today <= cache_date:
        return 0
    return len(pd.bdate_range(cache_date, today)) - 1


def evaluate_erp_signal(
    pe_ratio: float | None,
    best_gry: float | None,
    cache_date: str | None,
    erp_threshold_pct: float,
) -> ErpSignal:
    if pe_ratio is None or best_gry is None or cache_date is None:
        return ErpSignal(
            state="unavailable",
            erp_pct=None,
            earnings_yield_pct=None,
            best_gilt_gry_pct=None,
            explanation="Equity valuation data is unavailable.",
        )

    earnings_yield = 1.0 / pe_ratio
    erp = earnings_yield - best_gry
    erp_pct = round(erp * 100, 6)
    earnings_yield_pct = round(earnings_yield * 100, 6)
    best_gilt_gry_pct = round(best_gry * 100, 6)

    if trading_days_since(cache_date) > ERP_STALE_TRADING_DAYS:
        state = "stale"
        explanation = (
            f"Data is stale (last fetched {cache_date}). "
            f"ERP was {erp_pct:+.2f}% "
            f"(earnings yield {earnings_yield_pct:.2f}% vs gilt GRY {best_gilt_gry_pct:.2f}%)."
        )
    elif erp < erp_threshold_pct / 100:
        state = "warning"
        explanation = (
            f"ERP is {erp_pct:+.2f}% — below the {erp_threshold_pct:+.2f}% threshold. "
            f"Gilt GRY ({best_gilt_gry_pct:.2f}%) exceeds equity earnings yield ({earnings_yield_pct:.2f}%)."
        )
    else:
        state = "quiet"
        explanation = (
            f"ERP is {erp_pct:+.2f}% — equities retain a positive risk premium over gilts. "
            f"Earnings yield {earnings_yield_pct:.2f}% vs gilt GRY {best_gilt_gry_pct:.2f}%."
        )

    return ErpSignal(
        state=state,
        erp_pct=erp_pct,
        earnings_yield_pct=earnings_yield_pct,
        best_gilt_gry_pct=best_gilt_gry_pct,
        explanation=explanation,
    )


def classify_curve_state(
    five_y: float,
    ten_y: float,
    twenty_y: float,
    flat_threshold_bps: float = CURVE_FLAT_THRESHOLD_BPS,
) -> str:
    five_to_ten_bps = (ten_y - five_y) * 100
    ten_to_twenty_bps = (ten_y - twenty_y) * 100
    if five_to_ten_bps > flat_threshold_bps and ten_to_twenty_bps > flat_threshold_bps:
        return "humped"
    if five_to_ten_bps > flat_threshold_bps:
        return "normal"
    if five_to_ten_bps < -flat_threshold_bps:
        return "inverted"
    return "flat"


def count_consecutive_bdays_with_state(
    history: list[tuple[str, str]],
    target_state: str,
    holiday_set: set[datetime.date],
) -> int:
    if not history:
        return 0

    date_state = {datetime.date.fromisoformat(d): s for d, s in history}
    most_recent = max(date_state)
    earliest = min(date_state)

    count = 0
    current = most_recent
    while current >= earliest:
        is_bday = current.weekday() < 5 and current not in holiday_set
        if is_bday:
            if current not in date_state or date_state[current] != target_state:
                break
            count += 1
        current -= datetime.timedelta(days=1)

    return count


def evaluate_yield_curve_shape_signal(
    five_y: float | None,
    ten_y: float | None,
    twenty_y: float | None,
    cache_date: str | None,
    history: list[tuple[str, str]],
    flat_threshold_bps: float = CURVE_FLAT_THRESHOLD_BPS,
    persistence_days: int = CURVE_PERSISTENCE_DAYS,
) -> YieldCurveSignal:
    if five_y is None or ten_y is None or twenty_y is None or cache_date is None:
        return YieldCurveSignal(
            state="unavailable",
            curve_state=None,
            consecutive_days=None,
            spread_bps=None,
            five_year_pct=None,
            ten_year_pct=None,
            twenty_year_pct=None,
            cache_date=cache_date,
            explanation="Yield curve data is unavailable.",
        )

    spread_bps = round((ten_y - five_y) * 100, 2)
    curve_state = classify_curve_state(five_y, ten_y, twenty_y, flat_threshold_bps)
    consecutive_days = count_consecutive_bdays_with_state(history, curve_state, _UK_HOLIDAYS)
    label = curve_state.capitalize()

    if trading_days_since(cache_date) > ERP_STALE_TRADING_DAYS:
        return YieldCurveSignal(
            state="stale",
            curve_state=curve_state,
            consecutive_days=consecutive_days,
            spread_bps=spread_bps,
            five_year_pct=round(five_y, 4),
            ten_year_pct=round(ten_y, 4),
            twenty_year_pct=round(twenty_y, 4),
            cache_date=cache_date,
            explanation=(
                f"Data is stale (last fetched {cache_date}). "
                f"Curve was {label} with 10y−5y spread {spread_bps:+.0f}bps."
            ),
        )

    if curve_state != "normal" and consecutive_days >= persistence_days:
        state = "warning"
        explanation = (
            f"Curve is {label} — 10y−5y spread {spread_bps:+.0f}bps "
            f"({five_y:.2f}% / {ten_y:.2f}% / {twenty_y:.2f}%). "
            f"This shape has held for {consecutive_days} consecutive UK business days "
            f"(≥{persistence_days}-day persistence threshold)."
        )
    else:
        state = "quiet"
        if curve_state == "normal":
            explanation = (
                f"Curve is Normal — 10y−5y spread {spread_bps:+.0f}bps "
                f"({five_y:.2f}% / {ten_y:.2f}% / {twenty_y:.2f}%). "
                "No warning condition active."
            )
        else:
            explanation = (
                f"Curve is {label} — 10y−5y spread {spread_bps:+.0f}bps "
                f"({five_y:.2f}% / {ten_y:.2f}% / {twenty_y:.2f}%). "
                f"Held for {consecutive_days} of {persistence_days} required consecutive "
                "UK business days before this triggers a warning."
            )

    return YieldCurveSignal(
        state=state,
        curve_state=curve_state,
        consecutive_days=consecutive_days,
        spread_bps=spread_bps,
        five_year_pct=round(five_y, 4),
        ten_year_pct=round(ten_y, 4),
        twenty_year_pct=round(twenty_y, 4),
        cache_date=cache_date,
        explanation=explanation,
    )
