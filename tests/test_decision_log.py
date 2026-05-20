from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from investment_optimiser.db import initialize_database
from investment_optimiser.decision_log import insert_decision


def _make_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _all_decisions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM decision_log ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def test_insert_decision_round_trip(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    insert_decision(
        conn,
        decision_date="2026-05-20",
        action="acted",
        instruments_affected=["SWDA.L", "TN25.L"],
        notes="Switched gilt.",
        signal_event_id=None,
        created_at="2026-05-20T09:00:00Z",
    )
    conn.commit()

    rows = _all_decisions(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision_date"] == "2026-05-20"
    assert row["action"] == "acted"
    assert json.loads(row["instruments_affected"]) == ["SWDA.L", "TN25.L"]
    assert row["notes"] == "Switched gilt."
    assert row["signal_event_id"] is None


def test_newest_first_ordering(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    insert_decision(
        conn,
        decision_date="2026-05-19",
        action="passed",
        instruments_affected=[],
        notes="Earlier entry.",
        signal_event_id=None,
        created_at="2026-05-19T08:00:00Z",
    )
    insert_decision(
        conn,
        decision_date="2026-05-20",
        action="deferred",
        instruments_affected=[],
        notes="Later entry.",
        signal_event_id=None,
        created_at="2026-05-20T09:00:00Z",
    )
    conn.commit()

    rows = _all_decisions(conn)
    assert rows[0]["decision_date"] == "2026-05-20"
    assert rows[1]["decision_date"] == "2026-05-19"


def test_signal_event_id_nullable(tmp_path: Path) -> None:
    conn = _make_db(tmp_path)
    insert_decision(
        conn,
        decision_date="2026-05-20",
        action="passed",
        instruments_affected=[],
        notes="No linked signal.",
        signal_event_id=None,
        created_at="2026-05-20T10:00:00Z",
    )
    conn.commit()

    rows = _all_decisions(conn)
    assert rows[0]["signal_event_id"] is None
