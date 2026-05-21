import copy

import pandas as pd
import pytest

from investment_optimiser.recommendation_change_summary import (
    build_allocation_change_df,
    build_headline_metrics,
)

_BASE_SNAP = {
    "schema_version": "v1",
    "policy_inputs": {
        "policy_version": "v1",
        "baseline_version": "b1",
        "scenario_set_name": "default",
        "regime_state": "normal",
        "constraints": ["max_gilt_weight"],
        "score_coefficients": {"yield": 1.0},
    },
    "current_holdings": {
        "snapshot_date": "2026-05-01",
        "total_market_value_gbp": 100000.0,
        "positions": [{"bucket_id": "gilt", "market_value_gbp": 50000.0}],
    },
    "outputs": {
        "solver_status": "optimal",
        "fallback_path": None,
        "target_weights": {"gilt": 0.50, "equity": 0.30, "mmf": 0.20},
        "trades": [{"symbol": "TR27", "delta_value_gbp": 5000.0}],
        "executable_portfolio": [],
        "recommended_allocations": [
            {"bucket_id": "gilt", "label": "Gilts", "proposed_value_gbp": 50000.0, "proposed_pct": 50.0},
            {"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 30000.0, "proposed_pct": 30.0},
            {"bucket_id": "mmf", "label": "MMF", "proposed_value_gbp": 20000.0, "proposed_pct": 20.0},
        ],
        "scenario_results": [],
    },
    "diagnostics": {
        "binding_constraints": [],
        "warnings": [],
        "notes": [],
    },
}


def _snap(**overrides) -> dict:
    s = copy.deepcopy(_BASE_SNAP)
    for path, value in overrides.items():
        parts = path.split(".")
        node = s
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = value
    return s


# ---------------------------------------------------------------------------
# build_allocation_change_df
# ---------------------------------------------------------------------------


def test_build_allocation_change_df_no_change():
    snap = _snap()
    result = build_allocation_change_df(snap, snap)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_build_allocation_change_df_detects_shift():
    prior = _snap()
    current = _snap()
    current["outputs"]["recommended_allocations"] = [
        {"bucket_id": "gilt", "label": "Gilts", "proposed_value_gbp": 60000.0, "proposed_pct": 60.0},
        {"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 20000.0, "proposed_pct": 20.0},
        {"bucket_id": "mmf", "label": "MMF", "proposed_value_gbp": 20000.0, "proposed_pct": 20.0},
    ]
    result = build_allocation_change_df(prior, current)
    assert set(result["bucket_id"]) == {"gilt", "equity"}
    gilt_row = result[result["bucket_id"] == "gilt"].iloc[0]
    assert gilt_row["prior_pct"] == pytest.approx(50.0)
    assert gilt_row["current_pct"] == pytest.approx(60.0)
    assert gilt_row["delta_pct"] == pytest.approx(10.0)
    equity_row = result[result["bucket_id"] == "equity"].iloc[0]
    assert equity_row["delta_pct"] == pytest.approx(-10.0)


def test_build_allocation_change_df_handles_new_bucket():
    prior = _snap()
    current = _snap()
    current["outputs"]["recommended_allocations"] = [
        {"bucket_id": "gilt", "label": "Gilts", "proposed_value_gbp": 50000.0, "proposed_pct": 50.0},
        {"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 30000.0, "proposed_pct": 30.0},
        {"bucket_id": "mmf", "label": "MMF", "proposed_value_gbp": 10000.0, "proposed_pct": 10.0},
        {"bucket_id": "corp_bond", "label": "Corp Bond", "proposed_value_gbp": 10000.0, "proposed_pct": 10.0},
    ]
    result = build_allocation_change_df(prior, current)
    assert "corp_bond" in result["bucket_id"].values
    new_row = result[result["bucket_id"] == "corp_bond"].iloc[0]
    assert new_row["prior_pct"] == pytest.approx(0.0)
    assert new_row["current_pct"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# build_headline_metrics
# ---------------------------------------------------------------------------


def test_build_headline_metrics_value_delta():
    prior = _snap()
    current = _snap()
    current["current_holdings"]["total_market_value_gbp"] = 105000.0
    metrics = build_headline_metrics(prior, current)
    assert metrics["prior_value_gbp"] == pytest.approx(100000.0)
    assert metrics["current_value_gbp"] == pytest.approx(105000.0)
    assert metrics["value_delta_gbp"] == pytest.approx(5000.0)


def test_build_headline_metrics_trade_count():
    prior = _snap()
    current = _snap()
    current["outputs"]["trades"] = [
        {"symbol": "TR27", "delta_value_gbp": 1000.0},
        {"symbol": "TR30", "delta_value_gbp": 2000.0},
        {"symbol": "TR35", "delta_value_gbp": 3000.0},
    ]
    metrics = build_headline_metrics(prior, current)
    assert metrics["prior_trade_count"] == 1
    assert metrics["current_trade_count"] == 3
    assert metrics["trade_count_delta"] == 2


def test_build_headline_metrics_regime_change():
    prior = _snap()
    current = _snap()
    current["policy_inputs"]["regime_state"] = "risk_off"
    metrics = build_headline_metrics(prior, current)
    assert metrics["regime_changed"] is True
    assert metrics["prior_regime"] == "normal"
    assert metrics["current_regime"] == "risk_off"


def test_build_headline_metrics_no_change():
    snap = _snap()
    metrics = build_headline_metrics(snap, snap)
    assert metrics["value_delta_gbp"] == pytest.approx(0.0)
    assert metrics["trade_count_delta"] == 0
    assert metrics["regime_changed"] is False
    assert metrics["scenario_set_changed"] is False
