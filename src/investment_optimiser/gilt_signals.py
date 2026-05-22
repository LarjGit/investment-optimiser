from __future__ import annotations

from datetime import date, timedelta
import sqlite3

import pandas as pd


_RANKING_SQL_CONVENTIONAL = """
    SELECT
        p.isin,
        r.tidm,
        r.instrument_name,
        r.instrument_type,
        p.maturity_date,
        p.coupon_pct,
        p.clean_price_gbp,
        p.gry_pct,
        p.modified_duration_years
    FROM gilt_price_cache p
    JOIN gilt_reference r ON r.isin = p.isin
    WHERE r.instrument_type = 'Conventional'
      AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
"""

_RANKING_SQL_WITH_IL = """
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

_CANDIDATE_SQL_CONVENTIONAL = """
    SELECT
        r.isin,
        r.tidm,
        r.instrument_name,
        r.instrument_type,
        r.maturity_date,
        r.coupon_pct,
        p.clean_price_gbp,
        p.gry_pct,
        p.modified_duration_years
    FROM gilt_reference r
    LEFT JOIN gilt_price_cache p
        ON p.isin = r.isin
        AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
    WHERE r.instrument_type = 'Conventional'
"""

_CANDIDATE_SQL_WITH_IL = """
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
    rpi_assumption_pct: float | None = None,
) -> pd.DataFrame:
    sql = _RANKING_SQL_WITH_IL if rpi_assumption_pct else _RANKING_SQL_CONVENTIONAL
    df = pd.read_sql_query(sql, connection, dtype_backend="numpy_nullable")
    return df.sort_values("gry_pct", ascending=False, na_position="last").reset_index(drop=True)


def build_gilt_candidate_universe(
    connection: sqlite3.Connection,
    max_maturity_years: float | None = None,
    reference_date: date | None = None,
    rpi_assumption_pct: float | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return (ranked_df, warnings): priced gilts ranked by GRY; omissions become warnings."""
    sql = _CANDIDATE_SQL_WITH_IL if rpi_assumption_pct else _CANDIDATE_SQL_CONVENTIONAL
    df = pd.read_sql_query(sql, connection, dtype_backend="numpy_nullable")

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
