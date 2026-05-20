from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3

from investment_optimiser.policy_pack import load_policy_pack


@dataclass(frozen=True)
class BaselineRecord:
    created_at: str
    label: str
    policy_version: str
    weights: dict[str, float]
    notes: str | None


def validate_baseline_weights(
    weights: dict[str, float], expected_bucket_ids: list[str]
) -> None:
    expected = set(expected_bucket_ids)
    actual = set(weights.keys())

    missing = expected - actual
    if missing:
        raise ValueError(
            f"Missing bucket(s) from baseline weights: {', '.join(sorted(missing))}"
        )

    extra = actual - expected
    if extra:
        raise ValueError(
            f"Unknown bucket(s) in baseline weights: {', '.join(sorted(extra))}"
        )

    for bucket_id, weight in weights.items():
        if weight < 0.0:
            raise ValueError(
                f"Weight for '{bucket_id}' must be >= 0, got {weight}"
            )

    total = sum(weights.values())
    if abs(total - 100.0) > 0.01:
        raise ValueError(
            f"Baseline weights must sum to 100.0%, got {total:.2f}%"
        )


def insert_baseline(
    connection: sqlite3.Connection, record: BaselineRecord
) -> int:
    pack = load_policy_pack()
    expected_bucket_ids = [b["id"] for b in pack["baseline_bucket_model"]["buckets"]]
    validate_baseline_weights(record.weights, expected_bucket_ids)

    weights_json = json.dumps(record.weights, sort_keys=True, separators=(",", ":"))
    cursor = connection.execute(
        """
        INSERT INTO strategic_baseline (created_at, label, policy_version, weights_json, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            record.created_at,
            record.label,
            record.policy_version,
            weights_json,
            record.notes,
        ),
    )
    return int(cursor.lastrowid)


def fetch_current_baseline(
    connection: sqlite3.Connection,
) -> BaselineRecord | None:
    row = connection.execute(
        """
        SELECT created_at, label, policy_version, weights_json, notes
        FROM strategic_baseline
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return BaselineRecord(
        created_at=row[0],
        label=row[1],
        policy_version=row[2],
        weights=json.loads(row[3]),
        notes=row[4],
    )
