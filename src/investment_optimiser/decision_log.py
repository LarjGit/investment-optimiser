from __future__ import annotations

import json
import sqlite3


def insert_decision(
    conn: sqlite3.Connection,
    *,
    decision_date: str,
    action: str,
    instruments_affected: list[str],
    notes: str,
    signal_event_id: int | None,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO decision_log
            (decision_date, signal_event_id, action, instruments_affected, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            decision_date,
            signal_event_id,
            action,
            json.dumps(instruments_affected),
            notes,
            created_at,
        ),
    )
