from __future__ import annotations

from datetime import date, timedelta
import sqlite3

import pandas as pd


_VALID_BRACKETS = frozenset({"ultra-short", "short", "medium", "long"})
_ULTRA_SHORT_ALIASES = frozenset({"ultra-short", "ultra short"})


def assign_bracket(
    maturity_date_str: str | None,
    dmo_bracket: str | None = None,
    reference_date: date | None = None,
) -> str:
    """Return 'ultra-short', 'short', 'medium', or 'long' for a gilt.

    Uses dmo_bracket when it maps to a recognised value, otherwise derives from
    time-to-maturity: short < 5y, medium 5–15y, long ≥ 15y.
    Falls back to 'short' when maturity_date_str is None.
    """
    if dmo_bracket:
        normalised = dmo_bracket.lower()
        if normalised in _ULTRA_SHORT_ALIASES:
            return "ultra-short"
        if normalised in _VALID_BRACKETS:
            return normalised

    if maturity_date_str is None:
        return "short"

    ref = reference_date or date.today()
    try:
        mat = date.fromisoformat(maturity_date_str)
    except ValueError:
        return "short"

    ttm_years = (mat - ref).days / 365.25
    if ttm_years >= 15.0:
        return "long"
    if ttm_years >= 5.0:
        return "medium"
    return "short"


_RANKING_SQL = """
    SELECT
        p.isin,
        r.tidm,
        r.instrument_name,
        r.instrument_type,
        p.maturity_date,
        p.coupon_pct,
        p.clean_price_gbp,
        COALESCE(p.nominal_equivalent_gry_pct, p.gry_pct) AS gry_pct,
        p.modified_duration_years
    FROM gilt_price_cache p
    JOIN gilt_reference r ON r.isin = p.isin
    WHERE (
        (r.instrument_type = 'Conventional')
        OR (r.instrument_type = 'Index-linked' AND p.nominal_equivalent_gry_pct IS NOT NULL)
    )
      AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
"""

_CANDIDATE_SQL = """
    SELECT
        r.isin,
        r.tidm,
        r.instrument_name,
        r.instrument_type,
        r.maturity_date,
        r.coupon_pct,
        p.clean_price_gbp,
        COALESCE(p.nominal_equivalent_gry_pct, p.gry_pct) AS gry_pct,
        p.modified_duration_years
    FROM gilt_reference r
    LEFT JOIN gilt_price_cache p
        ON p.isin = r.isin
        AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
    WHERE (
        (r.instrument_type = 'Conventional')
        OR (r.instrument_type = 'Index-linked' AND p.nominal_equivalent_gry_pct IS NOT NULL)
    )
"""


def fetch_gilt_ranking(
    connection: sqlite3.Connection,
) -> pd.DataFrame:
    df = pd.read_sql_query(_RANKING_SQL, connection, dtype_backend="numpy_nullable")
    return df.sort_values("gry_pct", ascending=False, na_position="last").reset_index(drop=True)


def build_gilt_candidate_universe(
    connection: sqlite3.Connection,
    max_maturity_years: float | None = None,
    reference_date: date | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return (ranked_df, warnings): priced gilts ranked by GRY; omissions become warnings."""
    df = pd.read_sql_query(_CANDIDATE_SQL, connection, dtype_backend="numpy_nullable")

    if df.empty:
        return df, []

    warnings: list[str] = []
    today = reference_date or date.today()

    if max_maturity_years is not None:
        cutoff = today + timedelta(days=int(max_maturity_years * 365.25))
        beyond_cutoff = pd.to_datetime(df["maturity_date"]).dt.date > cutoff
        excluded_count = int(beyond_cutoff.sum())
        if excluded_count:
            warnings.append(
                f"{excluded_count} gilt(s) excluded: maturity beyond "
                f"{max_maturity_years:.0f}y policy cutoff"
            )
        df = df[~beyond_cutoff].reset_index(drop=True)

    unpriced = df["clean_price_gbp"].isna()
    unpriced_count = int(unpriced.sum())
    if unpriced_count:
        warnings.append(
            f"{unpriced_count} gilt(s) have no current price in the market snapshot"
        )
    df = df[~unpriced].reset_index(drop=True)

    no_analytics_count = int(df["gry_pct"].isna().sum())
    if no_analytics_count:
        warnings.append(
            f"{no_analytics_count} gilt(s) have a price but missing GRY analytics"
            " — analytics refresh may be needed"
        )

    df = df.sort_values("gry_pct", ascending=False, na_position="last").reset_index(drop=True)
    return df, warnings
