from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sqlite3

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.gilt_analytics import compute_gry, compute_real_gry, gilt_analytics_handler

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


def test_gilt_analytics_handler_derives_lse_benchmark_yields(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    today = date.today()

    gilts = [
        ("GB0000000001", (today + timedelta(days=365)).isoformat(),  4.25, 0.042),
        ("GB0000000002", (today + timedelta(days=730)).isoformat(),  4.00, 0.040),
        ("GB0000000003", (today + timedelta(days=1825)).isoformat(), 3.75, 0.038),
        ("GB0000000004", (today + timedelta(days=10950)).isoformat(), 1.50, 0.045),
    ]

    with sqlite3.connect(db_path) as connection:
        for isin, maturity, coupon, gry in gilts:
            _seed_reference_row(connection, isin=isin, coupon_pct=coupon, maturity_date=maturity)
            _seed_price_row(
                connection,
                isin=isin,
                clean_price=100.0,
                coupon_pct=coupon,
                maturity_date=maturity,
                gry_pct=gry,
            )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        gilt_analytics_handler(connection)
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        rows = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT curve_key, rate_pct, series_code FROM yield_curve_cache"
            ).fetchall()
        }

    assert "lse_derived_1y" in rows
    assert "lse_derived_2y" in rows
    assert "lse_derived_30y" in rows
    assert rows["lse_derived_1y"][1] == "LSE_DERIVED"
    assert rows["lse_derived_2y"][1] == "LSE_DERIVED"
    assert rows["lse_derived_30y"][1] == "LSE_DERIVED"
    # nearest gilt to 1y has gry=0.042, nearest to 2y has gry=0.040, nearest to 30y has gry=0.045
    assert rows["lse_derived_1y"][0] == pytest.approx(0.042)
    assert rows["lse_derived_2y"][0] == pytest.approx(0.040)
    assert rows["lse_derived_30y"][0] == pytest.approx(0.045)


def test_gilt_analytics_handler_skips_benchmark_when_no_gry_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        gilt_analytics_handler(connection)
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM yield_curve_cache").fetchone()[0]
    assert count == 0


# --- compute_real_gry ---


def test_compute_real_gry_par_il_gilt() -> None:
    # 2% real coupon, priced at par, ~5 years to maturity
    # real GRY should ≈ 2%; at 3% RPI nominal-equiv ≈ 5.03%
    real_gry, nominal_equiv = compute_real_gry(
        100.0, 2.0, date(2031, 5, 7), _SETTLEMENT, 3.0
    )

    assert real_gry is not None
    assert nominal_equiv is not None
    assert abs(real_gry - 0.02) < 0.002
    assert abs(nominal_equiv - 0.0503) < 0.005


def test_compute_real_gry_returns_none_on_impossible_price() -> None:
    # gilt matured before settlement — future_coupons is empty, no yield can be computed
    result = compute_real_gry(100.0, 2.0, date(2020, 5, 7), _SETTLEMENT, 3.0)

    assert result == (None, None)


def test_fisher_conversion() -> None:
    # exact semi-annual Fisher: n = 2*((1+r/2)*(1+i/2)-1)  ← decimal, not %
    # r=0.02, i=0.03 → n = 2*(1.01*1.015-1) = 0.0503
    _, nominal_equiv = compute_real_gry(100.0, 2.0, date(2031, 5, 7), _SETTLEMENT, 3.0)

    assert nominal_equiv is not None
    expected = 2.0 * ((1.0 + 0.02 / 2.0) * (1.0 + 0.03 / 2.0) - 1.0)
    assert abs(nominal_equiv - expected) < 0.0001


# --- gilt_analytics_handler IL gilt extension ---


def test_il_gilt_analytics_handler_fills_real_gry_when_rpi_present(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        _seed_reference_row(
            connection,
            isin="GB00B4RVKJ67",
            coupon_pct=2.0,
            maturity_date="2031-05-07",
            instrument_type="Index-linked",
        )
        _seed_price_row(
            connection,
            isin="GB00B4RVKJ67",
            clean_price=100.0,
            coupon_pct=2.0,
            maturity_date="2031-05-07",
        )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        warnings = gilt_analytics_handler(connection, rpi_assumption_pct=3.0)
        row = connection.execute(
            "SELECT real_gry_pct, nominal_equivalent_gry_pct FROM gilt_price_cache WHERE isin = ?",
            ("GB00B4RVKJ67",),
        ).fetchone()

    assert warnings == []
    assert row[0] is not None
    assert row[1] is not None


def test_compute_real_gry_negative_real_yield() -> None:
    # 2% coupon, ~1 year to maturity, priced just above its undiscounted cash-flow sum
    # → real yield is slightly negative; requires the v>1 solver branch
    real_gry, nominal_equiv = compute_real_gry(
        103.0, 2.0, date(2027, 5, 7), _SETTLEMENT, 3.0
    )

    assert real_gry is not None
    assert real_gry < 0
    assert nominal_equiv is not None


def test_il_gilt_analytics_handler_skips_il_gilts_when_no_rpi(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")

    with sqlite3.connect(db_path) as connection:
        _seed_reference_row(
            connection,
            isin="GB00B4RVKJ67",
            coupon_pct=2.0,
            maturity_date="2031-05-07",
            instrument_type="Index-linked",
        )
        _seed_price_row(
            connection,
            isin="GB00B4RVKJ67",
            clean_price=100.0,
            coupon_pct=2.0,
            maturity_date="2031-05-07",
        )
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        gilt_analytics_handler(connection)
        row = connection.execute(
            "SELECT real_gry_pct, nominal_equivalent_gry_pct FROM gilt_price_cache WHERE isin = ?",
            ("GB00B4RVKJ67",),
        ).fetchone()

    assert row[0] is None
    assert row[1] is None
