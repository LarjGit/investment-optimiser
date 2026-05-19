from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from investment_optimiser.db import initialize_database
from investment_optimiser.gilt_analytics import compute_gry, gilt_analytics_handler

_SETTLEMENT = date(2026, 5, 20)


def _seed_reference_row(
    connection: sqlite3.Connection,
    *,
    isin: str,
    coupon_pct: float,
    maturity_date: str,
    instrument_type: str = "Conventional",
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_reference (
            isin, instrument_name, coupon_pct, maturity_date,
            dividend_months, dividend_day, instrument_type, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (isin, "Test Gilt", coupon_pct, maturity_date, "May,Nov", 7, instrument_type, "2026-05-19T08:00:00Z"),
    )


def _seed_price_row(
    connection: sqlite3.Connection,
    *,
    isin: str,
    clean_price: float,
    coupon_pct: float,
    maturity_date: str,
    gry_pct: float | None = None,
    modified_duration_years: float | None = None,
    cache_date: str = date.today().isoformat(),
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_price_cache (
            cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years,
            coupon_pct, maturity_date, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cache_date,
            isin,
            clean_price,
            gry_pct,
            modified_duration_years,
            coupon_pct,
            maturity_date,
            "2026-05-20T08:00:00Z",
        ),
    )


def test_compute_gry_standard_coupon_gilt() -> None:
    # 4% coupon, matures 2031-05-07, settlement 2026-05-20 (~5 years)
    # priced at par → GRY ≈ 4%
    gry, mod_dur = compute_gry(100.0, 4.0, date(2031, 5, 7), _SETTLEMENT)

    assert gry is not None
    assert mod_dur is not None
    assert abs(gry - 0.04) < 0.02
    assert 0 < mod_dur < 5.5


def test_compute_gry_final_period_gilt() -> None:
    # matures in ~3 months — n==0 branch
    gry, mod_dur = compute_gry(100.5, 1.5, date(2026, 8, 7), _SETTLEMENT)

    assert gry is not None
    assert mod_dur is not None
    assert mod_dur < 0.5


def test_compute_gry_returns_none_on_impossible_price() -> None:
    # Price of 200 exceeds the undiscounted sum of all cash flows (~120 for a
    # 5-year 4% gilt), so no valid discount factor exists and both solvers fail.
    result = compute_gry(200.0, 4.0, date(2031, 5, 7), _SETTLEMENT)

    assert result == (None, None)


def test_gilt_analytics_handler_fills_in_null_analytics(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        _seed_reference_row(connection, isin="GB0002404191", coupon_pct=4.0, maturity_date="2031-05-07")
        _seed_price_row(
            connection,
            isin="GB0002404191",
            clean_price=98.0,
            coupon_pct=4.0,
            maturity_date="2031-05-07",
        )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        warnings = gilt_analytics_handler(connection)
        row = connection.execute(
            "SELECT gry_pct, modified_duration_years FROM gilt_price_cache WHERE isin = ?",
            ("GB0002404191",),
        ).fetchone()

    assert warnings == []
    assert row[0] is not None
    assert row[1] is not None


def test_gilt_analytics_handler_returns_warning_on_failed_solve(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        _seed_reference_row(connection, isin="GB0002404191", coupon_pct=4.0, maturity_date="2031-05-07")
        _seed_price_row(
            connection,
            isin="GB0002404191",
            clean_price=200.0,
            coupon_pct=4.0,
            maturity_date="2031-05-07",
        )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        warnings = gilt_analytics_handler(connection)
        row = connection.execute(
            "SELECT gry_pct FROM gilt_price_cache WHERE isin = ?",
            ("GB0002404191",),
        ).fetchone()

    assert len(warnings) == 1
    assert "GB0002404191" in warnings[0]
    assert row[0] is None


def test_gilt_analytics_handler_skips_already_solved_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        _seed_reference_row(connection, isin="GB0002404191", coupon_pct=4.0, maturity_date="2031-05-07")
        _seed_reference_row(connection, isin="GB00B84Z3S63", coupon_pct=3.5, maturity_date="2032-01-22")
        _seed_price_row(
            connection,
            isin="GB0002404191",
            clean_price=98.0,
            coupon_pct=4.0,
            maturity_date="2031-05-07",
            gry_pct=0.045,
            modified_duration_years=4.5,
        )
        _seed_price_row(
            connection,
            isin="GB00B84Z3S63",
            clean_price=97.0,
            coupon_pct=3.5,
            maturity_date="2032-01-22",
        )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        warnings = gilt_analytics_handler(connection)
        rows = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT isin, gry_pct, modified_duration_years FROM gilt_price_cache"
            ).fetchall()
        }

    assert warnings == []
    assert rows["GB0002404191"] == (0.045, 4.5)
    assert rows["GB00B84Z3S63"][0] is not None
    assert rows["GB00B84Z3S63"][1] is not None
