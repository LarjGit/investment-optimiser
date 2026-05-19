from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.signal_persistence import (
    reconcile_signal_event,
    run_signal_persistence,
    write_signal_readings,
)


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _active_events(conn: sqlite3.Connection, alert_type: str, scope_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM signal_events WHERE alert_type=? AND scope_key=? AND cleared_at IS NULL",
        (alert_type, scope_key),
    ).fetchall()
    return [dict(r) for r in rows]


def _all_events(conn: sqlite3.Connection, alert_type: str, scope_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM signal_events WHERE alert_type=? AND scope_key=? ORDER BY id",
        (alert_type, scope_key),
    ).fetchall()
    return [dict(r) for r in rows]


def _readings(conn: sqlite3.Connection, signal_name: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM signal_readings WHERE signal_name=? ORDER BY reading_date, metric_name",
        (signal_name,),
    ).fetchall()
    return [dict(r) for r in rows]


def test_reconcile_insert_on_first_fire(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=True,
        severity="warning",
        message="ERP is negative",
        details_json='{"erp_pct": -0.5}',
        now="2026-05-20T08:00:00Z",
    )
    conn.commit()

    events = _active_events(conn, "erp_warning", "global")
    assert len(events) == 1
    assert events[0]["started_at"] == "2026-05-20T08:00:00Z"
    assert events[0]["last_seen_at"] == "2026-05-20T08:00:00Z"
    assert events[0]["cleared_at"] is None
    assert events[0]["message"] == "ERP is negative"
    assert events[0]["severity"] == "warning"


def test_reconcile_update_last_seen_when_already_active(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=True,
        severity="warning",
        message="ERP is negative",
        details_json='{"erp_pct": -0.5}',
        now="2026-05-19T08:00:00Z",
    )
    conn.commit()

    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=True,
        severity="warning",
        message="ERP still negative",
        details_json='{"erp_pct": -0.3}',
        now="2026-05-20T08:00:00Z",
    )
    conn.commit()

    events = _active_events(conn, "erp_warning", "global")
    assert len(events) == 1
    assert events[0]["last_seen_at"] == "2026-05-20T08:00:00Z"
    assert events[0]["started_at"] == "2026-05-19T08:00:00Z"
    assert events[0]["message"] == "ERP is negative"


def test_reconcile_clear_when_no_longer_firing(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=True,
        severity="warning",
        message="ERP is negative",
        details_json='{"erp_pct": -0.5}',
        now="2026-05-19T08:00:00Z",
    )
    conn.commit()

    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=False,
        severity="warning",
        message="",
        details_json="{}",
        now="2026-05-20T08:00:00Z",
    )
    conn.commit()

    active = _active_events(conn, "erp_warning", "global")
    assert len(active) == 0

    all_rows = _all_events(conn, "erp_warning", "global")
    assert len(all_rows) == 1
    assert all_rows[0]["cleared_at"] == "2026-05-20T08:00:00Z"
    assert all_rows[0]["last_seen_at"] == "2026-05-20T08:00:00Z"


def test_reconcile_noop_when_not_firing_and_no_active_row(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=False,
        severity="warning",
        message="",
        details_json="{}",
        now="2026-05-20T08:00:00Z",
    )
    conn.commit()

    all_rows = _all_events(conn, "erp_warning", "global")
    assert len(all_rows) == 0


def test_write_signal_readings_upsert(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)

    write_signal_readings(
        conn,
        reading_date="2026-05-20",
        signal_name="erp",
        metrics=[("erp_pct", 0.5, "pct"), ("earnings_yield_pct", 5.0, "pct")],
    )
    conn.commit()

    rows = _readings(conn, "erp")
    assert len(rows) == 2

    write_signal_readings(
        conn,
        reading_date="2026-05-20",
        signal_name="erp",
        metrics=[("erp_pct", 0.6, "pct")],
    )
    conn.commit()

    rows = _readings(conn, "erp")
    erp_row = next(r for r in rows if r["metric_name"] == "erp_pct")
    assert erp_row["value"] == pytest.approx(0.6)
    assert len(rows) == 2

    write_signal_readings(
        conn,
        reading_date="2026-05-21",
        signal_name="erp",
        metrics=[("erp_pct", 0.7, "pct")],
    )
    conn.commit()

    rows = _readings(conn, "erp")
    assert len(rows) == 3


def _seed_market_data(conn: sqlite3.Connection, reading_date: str) -> None:
    for curve_key, maturity, rate in [
        ("boe_5y", 5.0, 4.0),
        ("boe_10y", 10.0, 4.5),
        ("boe_20y", 20.0, 4.8),
    ]:
        conn.execute(
            """
            INSERT INTO yield_curve_cache
                (cache_date, curve_key, maturity_years, rate_pct, series_code, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (reading_date, curve_key, maturity, rate, curve_key.upper(), f"{reading_date}T08:00:00Z"),
        )

    conn.execute(
        """
        INSERT INTO equity_valuation_cache
            (cache_date, source_name, pe_ratio, pe_as_of, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (reading_date, "yfinance_equities", 20.0, reading_date, f"{reading_date}T08:00:00Z"),
    )

    conn.execute(
        """
        INSERT INTO gilt_reference
            (isin, instrument_name, coupon_pct, maturity_date,
             dividend_months, dividend_day, instrument_type, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("GB0000000001", "4.5% Treasury 2035", 4.5, "2035-12-07", "May,Nov", 7,
         "Conventional", f"{reading_date}T08:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO gilt_price_cache
            (isin, cache_date, clean_price_gbp, gry_pct, modified_duration_years,
             coupon_pct, maturity_date, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("GB0000000001", reading_date, 100.0, 0.045, 7.5, 4.5, "2035-12-07",
         f"{reading_date}T08:00:00Z"),
    )
    conn.commit()


def test_run_signal_persistence_creates_readings_and_events(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    reading_date = "2026-05-20"
    _seed_market_data(conn, reading_date)

    run_signal_persistence(conn, reading_date=reading_date, now="2026-05-20T09:00:00Z")
    conn.commit()

    erp_rows = _readings(conn, "erp")
    assert len(erp_rows) >= 1
    assert "erp_pct" in {r["metric_name"] for r in erp_rows}

    curve_rows = _readings(conn, "yield_curve_shape")
    assert len(curve_rows) >= 1

    active = conn.execute(
        "SELECT COUNT(*) FROM signal_events WHERE cleared_at IS NULL"
    ).fetchone()[0]
    assert active == 0
