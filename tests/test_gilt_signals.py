from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.gilt_signals import build_gilt_candidate_universe, fetch_gilt_ranking


def _seed_reference(
    connection: sqlite3.Connection,
    *,
    isin: str,
    instrument_name: str = "Test Gilt",
    coupon_pct: float = 4.0,
    maturity_date: str = "2030-06-07",
    instrument_type: str = "Conventional",
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_reference (
            isin, instrument_name, coupon_pct, maturity_date,
            dividend_months, dividend_day, instrument_type, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (isin, instrument_name, coupon_pct, maturity_date, "Jun,Dec", 7, instrument_type, "2026-05-19T08:00:00Z"),
    )


def _seed_price(
    connection: sqlite3.Connection,
    *,
    isin: str,
    clean_price_gbp: float = 100.0,
    coupon_pct: float = 4.0,
    maturity_date: str = "2030-06-07",
    gry_pct: float | None = None,
    modified_duration_years: float | None = None,
    cache_date: str = "2026-05-19",
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_price_cache (
            cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years,
            coupon_pct, maturity_date, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years,
         coupon_pct, maturity_date, "2026-05-19T08:00:00Z"),
    )


@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        yield connection


def test_fetch_gilt_ranking_returns_rows_sorted_by_gry_descending(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2031", coupon_pct=4.0, maturity_date="2031-06-07")
    _seed_reference(db, isin="GB00BFWFPL34", instrument_name="Treasury 0.5% 2029", coupon_pct=0.5, maturity_date="2029-07-22")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5)
    _seed_price(db, isin="GB00BFWFPL34", gry_pct=0.0510, modified_duration_years=2.8)
    db.commit()

    df = fetch_gilt_ranking(db)

    assert len(df) == 2
    assert list(df["isin"]) == ["GB00BFWFPL34", "GB00B54HL0K3"]
    assert float(df.iloc[0]["gry_pct"]) > float(df.iloc[1]["gry_pct"])


def test_fetch_gilt_ranking_includes_instrument_name_from_reference(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2031", coupon_pct=4.0, maturity_date="2031-06-07")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5)
    db.commit()

    df = fetch_gilt_ranking(db)

    assert df.iloc[0]["instrument_name"] == "Treasury 4% 2031"


def test_fetch_gilt_ranking_excludes_index_linked_gilts(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Conventional", instrument_type="Conventional")
    _seed_reference(db, isin="GB00B7L9SL19", instrument_name="Index-linked", instrument_type="Index-linked")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5)
    _seed_price(db, isin="GB00B7L9SL19", gry_pct=0.011, modified_duration_years=15.0)
    db.commit()

    df = fetch_gilt_ranking(db)

    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"


def test_fetch_gilt_ranking_nulls_sort_to_bottom(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Has Analytics", maturity_date="2031-06-07")
    _seed_reference(db, isin="GB00BFWFPL34", instrument_name="No Analytics", maturity_date="2029-07-22")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5, maturity_date="2031-06-07")
    _seed_price(db, isin="GB00BFWFPL34", gry_pct=None, modified_duration_years=None, maturity_date="2029-07-22")
    db.commit()

    df = fetch_gilt_ranking(db)

    assert len(df) == 2
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"
    assert df.iloc[1]["isin"] == "GB00BFWFPL34"


def test_fetch_gilt_ranking_returns_empty_dataframe_when_cache_is_empty(db: sqlite3.Connection) -> None:
    df = fetch_gilt_ranking(db)

    assert df.empty


def test_fetch_gilt_ranking_scopes_to_latest_cache_date(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2031")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.039, cache_date="2026-05-18")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, cache_date="2026-05-19")
    db.commit()

    df = fetch_gilt_ranking(db)

    assert len(df) == 1
    assert float(df.iloc[0]["gry_pct"]) == pytest.approx(0.0425)


# --- build_gilt_candidate_universe ---


_REF_DATE = date(2026, 5, 20)


def test_build_universe_empty_reference_returns_empty(db: sqlite3.Connection) -> None:
    df, warnings = build_gilt_candidate_universe(db)

    assert df.empty
    assert warnings == []


def test_build_universe_fully_priced_gilt_no_warnings(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2030", maturity_date="2030-06-07")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5, maturity_date="2030-06-07")
    db.commit()

    df, warnings = build_gilt_candidate_universe(db)

    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"
    assert warnings == []


def test_build_universe_unpriced_gilt_excluded_with_warning(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2030", maturity_date="2030-06-07")
    db.commit()

    df, warnings = build_gilt_candidate_universe(db)

    assert df.empty
    assert len(warnings) == 1
    assert "no current price" in warnings[0]


def test_build_universe_price_only_gilt_in_frame_with_analytics_warning(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_name="Treasury 4% 2030", maturity_date="2030-06-07")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=None, modified_duration_years=None, maturity_date="2030-06-07")
    db.commit()

    df, warnings = build_gilt_candidate_universe(db)

    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"
    assert any("missing GRY analytics" in w for w in warnings)


def test_build_universe_maturity_cutoff_excludes_gilt_with_warning(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", maturity_date="2030-06-07")   # within 5y of 2026-05-20
    _seed_reference(db, isin="GB00BFWFPL34", maturity_date="2031-12-07")   # beyond 5y of 2026-05-20
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5, maturity_date="2030-06-07")
    _seed_price(db, isin="GB00BFWFPL34", gry_pct=0.0390, modified_duration_years=5.3, maturity_date="2031-12-07")
    db.commit()

    df, warnings = build_gilt_candidate_universe(db, max_maturity_years=5.0, reference_date=_REF_DATE)

    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"
    assert any("maturity" in w.lower() and "cutoff" in w.lower() for w in warnings)


def test_build_universe_index_linked_always_excluded(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", instrument_type="Conventional", maturity_date="2030-06-07")
    _seed_reference(db, isin="GB00B7L9SL19", instrument_type="Index-linked", maturity_date="2030-06-07")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5)
    _seed_price(db, isin="GB00B7L9SL19", gry_pct=0.011, modified_duration_years=15.0)
    db.commit()

    df, warnings = build_gilt_candidate_universe(db)

    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00B54HL0K3"


def test_build_universe_multiple_warnings_combined(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", maturity_date="2030-06-07")   # fully priced
    _seed_reference(db, isin="GB00BFWFPL34", maturity_date="2029-07-22")   # unpriced
    _seed_reference(db, isin="GB00B7F9SL34", maturity_date="2032-06-07")   # price, no analytics
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5, maturity_date="2030-06-07")
    _seed_price(db, isin="GB00B7F9SL34", gry_pct=None, modified_duration_years=None, maturity_date="2032-06-07")
    db.commit()

    df, warnings = build_gilt_candidate_universe(db)

    assert len(df) == 2
    assert any("no current price" in w for w in warnings)
    assert any("missing GRY analytics" in w for w in warnings)


def test_build_universe_sorted_gry_descending_nulls_last(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", maturity_date="2030-06-07")
    _seed_reference(db, isin="GB00BFWFPL34", maturity_date="2029-07-22")
    _seed_reference(db, isin="GB00B7F9SL34", maturity_date="2031-06-07")
    _seed_price(db, isin="GB00B54HL0K3", gry_pct=0.0425, modified_duration_years=4.5, maturity_date="2030-06-07")
    _seed_price(db, isin="GB00BFWFPL34", gry_pct=0.0510, modified_duration_years=2.8, maturity_date="2029-07-22")
    _seed_price(db, isin="GB00B7F9SL34", gry_pct=None, modified_duration_years=None, maturity_date="2031-06-07")
    db.commit()

    df, _ = build_gilt_candidate_universe(db)

    assert len(df) == 3
    assert df.iloc[0]["isin"] == "GB00BFWFPL34"
    assert df.iloc[1]["isin"] == "GB00B54HL0K3"
    assert df.iloc[2]["isin"] == "GB00B7F9SL34"
