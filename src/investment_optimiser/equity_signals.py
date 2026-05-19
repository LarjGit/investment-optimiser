from __future__ import annotations

import datetime
from dataclasses import dataclass
import sqlite3

import pandas as pd


ERP_STALE_TRADING_DAYS = 5


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
