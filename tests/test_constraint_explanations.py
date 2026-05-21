from __future__ import annotations

import pytest

from investment_optimiser.constraint_explanations import explain_binding_constraints


@pytest.fixture
def policy() -> dict:
    return {
        "default_constraints": {
            "baseline_tilt_band_pct": 10.0,
            "minimum_cash_mmf_pct": 5.0,
            "minimum_short_duration_pct": 10.0,
            "turnover_limit_pct_by_regime": {"normal": 50.0, "constructive": 10.0},
            "scenario_floor_pct_of_current_value": {"rates_up_parallel": 94.0},
        },
        "baseline_bucket_model": {
            "buckets": [
                {"id": "liquidity_reserve", "label": "Liquidity reserve"},
                {"id": "short_duration_nominal_gilts", "label": "Short-duration gilts"},
                {"id": "listed_risk_assets", "label": "Equities"},
            ]
        },
    }


@pytest.fixture
def bucket_labels() -> dict[str, str]:
    return {
        "liquidity_reserve": "Liquidity reserve",
        "short_duration_nominal_gilts": "Short-duration gilts",
        "listed_risk_assets": "Equities",
    }


def test_empty_input_returns_empty_list(policy, bucket_labels) -> None:
    result = explain_binding_constraints([], {}, policy, bucket_labels)
    assert result == []


def test_total_turnover_limit_binding(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["total_turnover_limit"],
        {"total_turnover_limit": 0.02},
        policy,
        bucket_labels,
    )
    assert len(result) == 1
    row = result[0]
    assert row["label"] == "total_turnover_limit"
    assert "turnover" in row["short"].lower()
    assert "50" in row["short"]
    assert row["shadow_price"] == pytest.approx(0.02)
    assert row["status"] == "binding"


def test_upper_bound_references_bucket_label_and_tilt(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["upper_bound[listed_risk_assets]"],
        {"upper_bound[listed_risk_assets]": 0.03},
        policy,
        bucket_labels,
    )
    row = result[0]
    assert "Equities" in row["short"]
    assert "10" in row["short"]  # tilt band value
    assert row["status"] == "binding"


def test_lower_bound_references_bucket_label_and_floor(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["lower_bound[liquidity_reserve]"],
        {"lower_bound[liquidity_reserve]": 0.01},
        policy,
        bucket_labels,
    )
    row = result[0]
    assert "Liquidity reserve" in row["short"]
    assert "5" in row["short"]  # minimum_cash_mmf_pct
    assert row["status"] == "binding"


def test_turnover_upper_references_bucket(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["turnover_upper[short_duration_nominal_gilts]"],
        {"turnover_upper[short_duration_nominal_gilts]": 0.01},
        policy,
        bucket_labels,
    )
    row = result[0]
    assert "Short-duration gilts" in row["short"]
    assert row["status"] == "binding"


def test_scenario_floor_references_scenario_name(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["scenario_floor[rates_up_parallel]"],
        {"scenario_floor[rates_up_parallel]": 0.02},
        policy,
        bucket_labels,
    )
    row = result[0]
    assert "rates_up_parallel" in row["short"] or "rates up" in row["short"].lower()
    assert "94" in row["short"]
    assert row["status"] == "binding"


def test_unknown_label_falls_back_gracefully(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["mystery_constraint[foo]"],
        {"mystery_constraint[foo]": 0.05},
        policy,
        bucket_labels,
    )
    assert len(result) == 1
    row = result[0]
    assert row["label"] == "mystery_constraint[foo]"
    assert row["short"] != ""  # something is returned, not blank


def test_missing_marginal_gives_none_shadow_price_and_near_binding(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["total_turnover_limit"],
        {},  # no marginals supplied
        policy,
        bucket_labels,
    )
    row = result[0]
    assert row["shadow_price"] is None
    assert row["status"] == "near_binding"


def test_marginal_at_threshold_is_near_binding(policy, bucket_labels) -> None:
    # exactly at threshold (0.005) → near_binding
    result = explain_binding_constraints(
        ["total_turnover_limit"],
        {"total_turnover_limit": 0.005},
        policy,
        bucket_labels,
    )
    assert result[0]["status"] == "near_binding"


def test_marginal_above_threshold_is_binding(policy, bucket_labels) -> None:
    result = explain_binding_constraints(
        ["total_turnover_limit"],
        {"total_turnover_limit": 0.0051},
        policy,
        bucket_labels,
    )
    assert result[0]["status"] == "binding"
