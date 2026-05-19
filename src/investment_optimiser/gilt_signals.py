from __future__ import annotations

import sqlite3

import pandas as pd


_RANKING_SQL = """
    SELECT
        p.isin,
        r.instrument_name,
        p.maturity_date,
        p.coupon_pct,
        p.clean_price_gbp,
        p.gry_pct,
        p.modified_duration_years
    FROM gilt_price_cache p
    JOIN gilt_reference r ON r.isin = p.isin
    WHERE r.instrument_type = 'Conventional'
      AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
    ORDER BY p.gry_pct DESC NULLS LAST, p.maturity_date ASC
"""


def fetch_gilt_ranking(connection: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(_RANKING_SQL, connection, dtype_backend="numpy_nullable")
    return df.sort_values("gry_pct", ascending=False, na_position="last").reset_index(drop=True)
