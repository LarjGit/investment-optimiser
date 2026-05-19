from __future__ import annotations

from pathlib import Path
import sqlite3
from unittest.mock import patch

from investment_optimiser.db import initialize_database
from investment_optimiser.lse_gilt_prices import lse_gilt_prices_handler


def test_gilt_price_cache_allows_price_rows_before_analytics_exist(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(gilt_price_cache)")
        }

    assert columns["gry_pct"][3] == 0
    assert columns["modified_duration_years"][3] == 0


def test_lse_gilt_prices_handler_persists_price_rows_for_known_gilts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO gilt_reference (
                isin,
                tidm,
                instrument_name,
                coupon_pct,
                maturity_date,
                dividend_months,
                dividend_day,
                ex_div_date,
                instrument_type,
                maturity_bracket,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "GB00TEST0001",
                "TG26",
                "1 1/2% Treasury Gilt 2026",
                1.5,
                "2026-07-22",
                "Jan,Jul",
                22,
                None,
                "Conventional",
                "0-5",
                "2026-05-19T09:00:00Z",
            ),
        )

        with patch(
            "investment_optimiser.lse_gilt_prices._fetch_instrument_data",
            return_value={
                "currency": "GBP",
                "category": "BONDS",
                "segment": "UKGT",
                "midPrice": 100.25,
                "isin": "GB00TEST0001",
                "maturitydate": "2026-07-22T00:00:00",
            },
        ):
            warning_messages = lse_gilt_prices_handler(connection)

        rows = connection.execute(
            """
            SELECT
                cache_date,
                isin,
                clean_price_gbp,
                gry_pct,
                modified_duration_years,
                coupon_pct,
                maturity_date
            FROM gilt_price_cache
            """
        ).fetchall()

    assert warning_messages == []
    assert len(rows) == 1
    assert rows[0][1] == "GB00TEST0001"
    assert rows[0][2] == 100.25
    assert rows[0][3] is None
    assert rows[0][4] is None
    assert rows[0][5] == 1.5
    assert rows[0][6] == "2026-07-22"


def test_lse_gilt_prices_handler_continues_after_per_instrument_failure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO gilt_reference (
                isin,
                tidm,
                instrument_name,
                coupon_pct,
                maturity_date,
                dividend_months,
                dividend_day,
                ex_div_date,
                instrument_type,
                maturity_bracket,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "GB00GOOD0001",
                    "TG26",
                    "1 1/2% Treasury Gilt 2026",
                    1.5,
                    "2026-07-22",
                    "Jan,Jul",
                    22,
                    None,
                    "Conventional",
                    "0-5",
                    "2026-05-19T09:00:00Z",
                ),
                (
                    "GB00BAD00001",
                    "BAD1",
                    "4% Treasury Gilt 2030",
                    4.0,
                    "2030-01-22",
                    "Jan,Jul",
                    22,
                    None,
                    "Conventional",
                    "5-10",
                    "2026-05-19T09:00:00Z",
                ),
            ],
        )

        def fake_fetch(tidm: str) -> dict[str, object]:
            if tidm == "TG26":
                return {
                    "currency": "GBP",
                    "category": "BONDS",
                    "segment": "UKGT",
                    "bid": 99.5,
                    "offer": 100.5,
                    "isin": "GB00GOOD0001",
                }
            raise ValueError("404 not found")

        with patch(
            "investment_optimiser.lse_gilt_prices._fetch_instrument_data",
            side_effect=fake_fetch,
        ):
            warning_messages = lse_gilt_prices_handler(connection)

        rows = connection.execute(
            """
            SELECT isin, clean_price_gbp
            FROM gilt_price_cache
            ORDER BY isin ASC
            """
        ).fetchall()

    assert rows == [("GB00GOOD0001", 100.0)]
    assert len(warning_messages) == 1
    assert "BAD1" in warning_messages[0]
