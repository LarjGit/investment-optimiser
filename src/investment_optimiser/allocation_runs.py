from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Any


ALLOCATION_RUN_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class AllocationRunRecord:
    created_at: str
    policy_version: str
    baseline_version: str
    current_snapshot_date: str
    regime_state: str
    scenario_set_name: str
    solver_status: str
    fallback_path: str | None
    snapshot: dict[str, Any]


def insert_allocation_run(
    connection: sqlite3.Connection, record: AllocationRunRecord
) -> int:
    validate_allocation_run_record(record)
    snapshot_json = dump_allocation_run_snapshot_json(record.snapshot)
    cursor = connection.execute(
        """
        INSERT INTO allocation_runs (
            created_at,
            policy_version,
            baseline_version,
            current_snapshot_date,
            regime_state,
            scenario_set_name,
            solver_status,
            fallback_path,
            snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.created_at,
            record.policy_version,
            record.baseline_version,
            record.current_snapshot_date,
            record.regime_state,
            record.scenario_set_name,
            record.solver_status,
            record.fallback_path,
            snapshot_json,
        ),
    )
    return int(cursor.lastrowid)


def fetch_allocation_run(
    connection: sqlite3.Connection, allocation_run_id: int
) -> AllocationRunRecord:
    row = connection.execute(
        """
        SELECT
            created_at,
            policy_version,
            baseline_version,
            current_snapshot_date,
            regime_state,
            scenario_set_name,
            solver_status,
            fallback_path,
            snapshot_json
        FROM allocation_runs
        WHERE id = ?
        """,
        (allocation_run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Allocation run not found: {allocation_run_id}")

    record = AllocationRunRecord(
        created_at=row[0],
        policy_version=row[1],
        baseline_version=row[2],
        current_snapshot_date=row[3],
        regime_state=row[4],
        scenario_set_name=row[5],
        solver_status=row[6],
        fallback_path=row[7],
        snapshot=json.loads(row[8]),
    )
    validate_allocation_run_record(record)
    return record


def dump_allocation_run_snapshot_json(snapshot: dict[str, Any]) -> str:
    validate_allocation_run_snapshot(snapshot)
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


def validate_allocation_run_record(record: AllocationRunRecord) -> None:
    _require_string(record.created_at, "created_at")
    _require_string(record.policy_version, "policy_version")
    _require_string(record.baseline_version, "baseline_version")
    _require_string(record.current_snapshot_date, "current_snapshot_date")
    _require_string(record.regime_state, "regime_state")
    _require_string(record.scenario_set_name, "scenario_set_name")
    _require_string(record.solver_status, "solver_status")
    _require_optional_string(record.fallback_path, "fallback_path")

    validate_allocation_run_snapshot(record.snapshot)

    policy_inputs = record.snapshot["policy_inputs"]
    current_holdings = record.snapshot["current_holdings"]
    outputs = record.snapshot["outputs"]

    _require_equal(
        record.policy_version,
        policy_inputs["policy_version"],
        "policy_version",
    )
    _require_equal(
        record.baseline_version,
        policy_inputs["baseline_version"],
        "baseline_version",
    )
    _require_equal(
        record.current_snapshot_date,
        current_holdings["snapshot_date"],
        "current_snapshot_date",
    )
    _require_equal(
        record.regime_state,
        policy_inputs["regime_state"],
        "regime_state",
    )
    _require_equal(
        record.scenario_set_name,
        policy_inputs["scenario_set_name"],
        "scenario_set_name",
    )
    _require_equal(
        record.solver_status,
        outputs["solver_status"],
        "solver_status",
    )
    _require_equal(
        record.fallback_path,
        outputs["fallback_path"],
        "fallback_path",
    )


def validate_allocation_run_snapshot(snapshot: dict[str, Any]) -> None:
    _require_mapping(snapshot, "snapshot")
    _require_string(snapshot.get("schema_version"), "snapshot.schema_version")
    _require_equal(
        ALLOCATION_RUN_SCHEMA_VERSION,
        snapshot["schema_version"],
        "snapshot.schema_version",
    )

    policy_inputs = _require_mapping(
        snapshot.get("policy_inputs"), "snapshot.policy_inputs"
    )
    _require_string(
        policy_inputs.get("policy_version"),
        "snapshot.policy_inputs.policy_version",
    )
    _require_string(
        policy_inputs.get("baseline_version"),
        "snapshot.policy_inputs.baseline_version",
    )
    _require_string(
        policy_inputs.get("scenario_set_name"),
        "snapshot.policy_inputs.scenario_set_name",
    )
    _require_string(
        policy_inputs.get("regime_state"),
        "snapshot.policy_inputs.regime_state",
    )
    _require_list(
        policy_inputs.get("constraints"),
        "snapshot.policy_inputs.constraints",
    )
    _require_mapping(
        policy_inputs.get("score_coefficients"),
        "snapshot.policy_inputs.score_coefficients",
    )

    current_holdings = _require_mapping(
        snapshot.get("current_holdings"),
        "snapshot.current_holdings",
    )
    _require_string(
        current_holdings.get("snapshot_date"),
        "snapshot.current_holdings.snapshot_date",
    )
    _require_number(
        current_holdings.get("total_market_value_gbp"),
        "snapshot.current_holdings.total_market_value_gbp",
    )
    _require_list(
        current_holdings.get("positions"),
        "snapshot.current_holdings.positions",
    )

    outputs = _require_mapping(snapshot.get("outputs"), "snapshot.outputs")
    _require_string(outputs.get("solver_status"), "snapshot.outputs.solver_status")
    _require_optional_string(
        outputs.get("fallback_path"),
        "snapshot.outputs.fallback_path",
    )
    _require_list(
        outputs.get("recommended_allocations"),
        "snapshot.outputs.recommended_allocations",
    )
    _require_list(
        outputs.get("scenario_results"),
        "snapshot.outputs.scenario_results",
    )

    diagnostics = _require_mapping(
        snapshot.get("diagnostics"),
        "snapshot.diagnostics",
    )
    _require_list(
        diagnostics.get("binding_constraints"),
        "snapshot.diagnostics.binding_constraints",
    )
    _require_list(
        diagnostics.get("warnings"),
        "snapshot.diagnostics.warnings",
    )
    _require_list(
        diagnostics.get("notes"),
        "snapshot.diagnostics.notes",
    )


def _require_equal(expected: Any, actual: Any, field_name: str) -> None:
    if actual != expected:
        raise ValueError(
            f"{field_name} does not match the snapshot payload: "
            f"expected {expected!r}, got {actual!r}"
        )


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return value


def _require_number(value: Any, field_name: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number.")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _require_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)
