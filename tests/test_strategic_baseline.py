import sqlite3
from pathlib import Path

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.strategic_baseline import (
    BaselineRecord,
    fetch_current_baseline,
    insert_baseline,
    validate_baseline_weights,
)

_V1_BUCKET_IDS = [
    "liquidity_reserve",
    "short_duration_nominal_gilts",
    "long_duration_nominal_gilts",
    "index_linked_gilts",
    "listed_risk_assets",
    "diversifiers_and_manual",
]


def _valid_weights() -> dict[str, float]:
    return {
        "liquidity_reserve": 10.0,
        "short_duration_nominal_gilts": 20.0,
        "long_duration_nominal_gilts": 25.0,
        "index_linked_gilts": 10.0,
        "listed_risk_assets": 25.0,
        "diversifiers_and_manual": 10.0,
    }


def test_validate_weights_valid() -> None:
    validate_baseline_weights(_valid_weights(), _V1_BUCKET_IDS)


def test_validate_weights_wrong_sum() -> None:
    weights = _valid_weights()
    weights["liquidity_reserve"] = 5.0
    with pytest.raises(ValueError, match="100"):
        validate_baseline_weights(weights, _V1_BUCKET_IDS)


def test_validate_weights_negative() -> None:
    weights = _valid_weights()
    weights["liquidity_reserve"] = -5.0
    with pytest.raises(ValueError, match="liquidity_reserve"):
        validate_baseline_weights(weights, _V1_BUCKET_IDS)


def test_validate_weights_missing_bucket() -> None:
    weights = _valid_weights()
    del weights["index_linked_gilts"]
    with pytest.raises(ValueError, match="index_linked_gilts"):
        validate_baseline_weights(weights, _V1_BUCKET_IDS)


def test_validate_weights_extra_bucket() -> None:
    weights = _valid_weights()
    weights["unknown_bucket"] = 0.0
    with pytest.raises(ValueError, match="unknown_bucket"):
        validate_baseline_weights(weights, _V1_BUCKET_IDS)


def test_fetch_current_baseline_returns_none_when_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    with sqlite3.connect(db_path) as conn:
        result = fetch_current_baseline(conn)
    assert result is None


def test_insert_and_fetch_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    record = BaselineRecord(
        created_at="2026-05-20T10:00:00Z",
        label="initial",
        policy_version="v1",
        weights=_valid_weights(),
        notes="Starting baseline",
    )

    with sqlite3.connect(db_path) as conn:
        insert_baseline(conn, record)
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        fetched = fetch_current_baseline(conn)

    assert fetched is not None
    assert fetched.label == "initial"
    assert fetched.policy_version == "v1"
    assert fetched.weights == _valid_weights()
    assert fetched.notes == "Starting baseline"
    assert fetched.created_at == "2026-05-20T10:00:00Z"


def test_fetch_current_returns_latest_when_multiple(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    first = BaselineRecord(
        created_at="2026-05-20T09:00:00Z",
        label="first",
        policy_version="v1",
        weights=_valid_weights(),
        notes=None,
    )
    weights2 = _valid_weights()
    weights2["liquidity_reserve"] = 15.0
    weights2["listed_risk_assets"] = 20.0
    second = BaselineRecord(
        created_at="2026-05-20T10:00:00Z",
        label="revised",
        policy_version="v1",
        weights=weights2,
        notes="Revised after review",
    )

    with sqlite3.connect(db_path) as conn:
        insert_baseline(conn, first)
        insert_baseline(conn, second)
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        fetched = fetch_current_baseline(conn)

    assert fetched is not None
    assert fetched.label == "revised"
    assert fetched.weights["liquidity_reserve"] == 15.0


def test_insert_rejects_invalid_weights(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    bad_weights = _valid_weights()
    bad_weights["liquidity_reserve"] = 99.0  # sum > 100
    record = BaselineRecord(
        created_at="2026-05-20T10:00:00Z",
        label="bad",
        policy_version="v1",
        weights=bad_weights,
        notes=None,
    )

    with sqlite3.connect(db_path) as conn:
        with pytest.raises(ValueError, match="100"):
            insert_baseline(conn, record)
