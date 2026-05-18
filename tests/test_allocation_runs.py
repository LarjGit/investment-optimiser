import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.allocation_runs import (
    AllocationRunRecord,
    dump_allocation_run_snapshot_json,
    fetch_allocation_run,
    insert_allocation_run,
)


def sample_allocation_run_record() -> AllocationRunRecord:
    return AllocationRunRecord(
        created_at="2026-05-18T09:30:00Z",
        policy_version="v1",
        baseline_version="sixty_forty",
        current_snapshot_date="2026-05-17",
        regime_state="defensive",
        scenario_set_name="v1",
        solver_status="optimal",
        fallback_path=None,
        snapshot={
            "schema_version": "v1",
            "policy_inputs": {
                "policy_version": "v1",
                "baseline_version": "sixty_forty",
                "scenario_set_name": "v1",
                "regime_state": "defensive",
                "constraints": [
                    {"name": "minimum_cash_mmf_pct", "value": 5.0}
                ],
                "score_coefficients": {"carry": 0.6, "drawdown": 0.4},
            },
            "current_holdings": {
                "snapshot_date": "2026-05-17",
                "total_market_value_gbp": 100000.0,
                "positions": [
                    {
                        "symbol": "TR68",
                        "name": "Treasury 2068",
                        "asset_type": "gilt_conventional",
                        "market_value_gbp": 45000.0,
                        "weight_pct": 45.0,
                    },
                    {
                        "symbol": "CSH2",
                        "name": "Cash Reserve",
                        "asset_type": "mmf",
                        "market_value_gbp": 55000.0,
                        "weight_pct": 55.0,
                    },
                ],
            },
            "outputs": {
                "solver_status": "optimal",
                "fallback_path": None,
                "recommended_allocations": [
                    {"bucket_name": "gilts", "target_weight_pct": 40.0},
                    {"bucket_name": "cash_mmf", "target_weight_pct": 60.0},
                ],
                "scenario_results": [
                    {
                        "scenario_name": "stagflation",
                        "portfolio_value_gbp": 97250.0,
                    }
                ],
            },
            "diagnostics": {
                "binding_constraints": ["minimum_cash_mmf_pct"],
                "warnings": [],
                "notes": ["Kept a higher cash sleeve due to scenario floor."],
            },
        },
    )


def test_insert_and_fetch_allocation_run_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "allocation_runs.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    record = sample_allocation_run_record()

    with sqlite3.connect(db_path) as connection:
        allocation_run_id = insert_allocation_run(connection, record)
        connection.commit()

    with sqlite3.connect(db_path) as connection:
        stored_record = fetch_allocation_run(connection, allocation_run_id)

    assert stored_record == record


def test_dump_allocation_run_snapshot_json_is_canonical_and_round_trips() -> None:
    record = sample_allocation_run_record()

    dumped_snapshot = dump_allocation_run_snapshot_json(record.snapshot)

    assert dumped_snapshot == json.dumps(
        record.snapshot,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert json.loads(dumped_snapshot) == record.snapshot


def test_insert_allocation_run_rejects_mismatched_scalar_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "allocation_runs.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    record = sample_allocation_run_record()
    mismatched_snapshot = dict(record.snapshot)
    mismatched_policy_inputs = dict(mismatched_snapshot["policy_inputs"])
    mismatched_policy_inputs["policy_version"] = "v2"
    mismatched_snapshot["policy_inputs"] = mismatched_policy_inputs
    invalid_record = replace(record, snapshot=mismatched_snapshot)

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(ValueError, match="policy_version"):
            insert_allocation_run(connection, invalid_record)
