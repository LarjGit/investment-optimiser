import copy

import pandas as pd
import pytest

from investment_optimiser.recommendation_change_summary import (
    build_allocation_change_df,
    build_headline_metrics,
    build_inflation_attribution,
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


# ---------------------------------------------------------------------------
# build_inflation_attribution
# ---------------------------------------------------------------------------

_BASE_INFLATION_INPUTS = {
    "forward_rpi_pre_2030_pct": 3.0,
    "forward_rpi_post_2030_pct": 2.5,
    "observed_as_of_date": "2026-05-27",
    "observed_provider": "DMO_D10C",
    "observed_confidence_tier": "authoritative",
    "observed_is_degraded": False,
}


def _snap_with_inflation(**inflation_overrides) -> dict:
    """Return a snap whose policy_inputs includes inflation_inputs."""
    infl = {**_BASE_INFLATION_INPUTS, **inflation_overrides}
    s = _snap()
    s["policy_inputs"]["inflation_inputs"] = infl
    return s


def test_build_inflation_attribution_unknown_when_both_missing():
    prior = _snap()   # no inflation_inputs
    current = _snap()
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "unknown"
    assert result["observed_data_changed"] is False
    assert result["forward_assumptions_changed"] is False


def test_build_inflation_attribution_unknown_when_prior_missing():
    prior = _snap()   # no inflation_inputs
    current = _snap_with_inflation()
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "unknown"


def test_build_inflation_attribution_unknown_when_current_missing():
    prior = _snap_with_inflation()
    current = _snap()  # no inflation_inputs
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "unknown"


def test_build_inflation_attribution_non_inflation_when_no_change():
    snap = _snap_with_inflation()
    result = build_inflation_attribution(snap, snap)
    assert result["change_category"] == "non_inflation"
    assert result["observed_data_changed"] is False
    assert result["forward_assumptions_changed"] is False


def test_build_inflation_attribution_observed_data_changed():
    prior = _snap_with_inflation(observed_as_of_date="2026-05-01")
    current = _snap_with_inflation(observed_as_of_date="2026-05-27")
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "observed_data"
    assert result["observed_data_changed"] is True
    assert result["forward_assumptions_changed"] is False
    assert result["prior_observed_as_of_date"] == "2026-05-01"
    assert result["current_observed_as_of_date"] == "2026-05-27"


def test_build_inflation_attribution_forward_assumptions_changed_pre_2030():
    prior = _snap_with_inflation(forward_rpi_pre_2030_pct=3.0)
    current = _snap_with_inflation(forward_rpi_pre_2030_pct=3.5)
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "forward_assumptions"
    assert result["forward_assumptions_changed"] is True
    assert result["observed_data_changed"] is False
    assert result["prior_forward_pre_2030_pct"] == pytest.approx(3.0)
    assert result["current_forward_pre_2030_pct"] == pytest.approx(3.5)


def test_build_inflation_attribution_forward_assumptions_changed_post_2030():
    prior = _snap_with_inflation(forward_rpi_post_2030_pct=2.5)
    current = _snap_with_inflation(forward_rpi_post_2030_pct=2.0)
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "forward_assumptions"
    assert result["forward_assumptions_changed"] is True
    assert result["prior_forward_post_2030_pct"] == pytest.approx(2.5)
    assert result["current_forward_post_2030_pct"] == pytest.approx(2.0)


def test_build_inflation_attribution_both_changed():
    prior = _snap_with_inflation(observed_as_of_date="2026-05-01", forward_rpi_pre_2030_pct=3.0)
    current = _snap_with_inflation(observed_as_of_date="2026-05-27", forward_rpi_pre_2030_pct=3.5)
    result = build_inflation_attribution(prior, current)
    assert result["change_category"] == "both"
    assert result["observed_data_changed"] is True
    assert result["forward_assumptions_changed"] is True


def test_build_inflation_attribution_float_tolerance_within():
    """A sub-1e-4 RPI difference must NOT count as a forward-assumptions change."""
    prior = _snap_with_inflation(forward_rpi_pre_2030_pct=3.0)
    current = _snap_with_inflation(forward_rpi_pre_2030_pct=3.0 + 5e-5)
    result = build_inflation_attribution(prior, current)
    assert result["forward_assumptions_changed"] is False
    assert result["change_category"] == "non_inflation"


def test_build_inflation_attribution_float_tolerance_outside():
    """A diff just above 1e-4 MUST count as a forward-assumptions change."""
    prior = _snap_with_inflation(forward_rpi_pre_2030_pct=3.0)
    current = _snap_with_inflation(forward_rpi_pre_2030_pct=3.0 + 2e-4)
    result = build_inflation_attribution(prior, current)
    assert result["forward_assumptions_changed"] is True
    assert result["change_category"] == "forward_assumptions"


def test_build_inflation_attribution_carries_all_values():
    """Result dict exposes both prior and current values for display."""
    prior = _snap_with_inflation(
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
        observed_as_of_date="2026-05-01",
    )
    current = _snap_with_inflation(
        forward_rpi_pre_2030_pct=3.5,
        forward_rpi_post_2030_pct=2.8,
        observed_as_of_date="2026-05-27",
    )
    result = build_inflation_attribution(prior, current)
    assert result["prior_forward_pre_2030_pct"] == pytest.approx(3.0)
    assert result["current_forward_pre_2030_pct"] == pytest.approx(3.5)
    assert result["prior_forward_post_2030_pct"] == pytest.approx(2.5)
    assert result["current_forward_post_2030_pct"] == pytest.approx(2.8)
    assert result["prior_observed_as_of_date"] == "2026-05-01"
    assert result["current_observed_as_of_date"] == "2026-05-27"
