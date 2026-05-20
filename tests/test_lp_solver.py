from __future__ import annotations

import pytest

from investment_optimiser.lp_solver import LPSolveResult, solve_bucket_weights

BUCKET_IDS = [
    "liquidity_reserve",
    "short_duration_nominal_gilts",
    "long_duration_nominal_gilts",
    "index_linked_gilts",
    "listed_risk_assets",
    "diversifiers_and_manual",
]

POLICY = {
    "policy_version": "v1",
    "scenario_set_name": "v1",
    "default_constraints": {
        "long_only": True,
        "fully_invested": True,
        "baseline_tilt_band_pct": 10.0,
        "turnover_limit_pct_by_regime": {
            "constructive": 10.0,
            "normal": 15.0,
            "defensive": 25.0,
        },
        "minimum_cash_mmf_pct": 5.0,
        "minimum_short_duration_pct": 10.0,
        "scenario_floor_pct_of_current_value": {
            "rates_up_parallel": 94.0,
            "bear_steepener": 92.0,
            "equity_drawdown": 88.0,
            "inflation_surprise": 90.0,
        },
    },
}

# Baseline weights summing to 100%
BASELINE = {
    "liquidity_reserve": 10.0,
    "short_duration_nominal_gilts": 15.0,
    "long_duration_nominal_gilts": 20.0,
    "index_linked_gilts": 10.0,
    "listed_risk_assets": 35.0,
    "diversifiers_and_manual": 10.0,
}

# Current weights identical to baseline → no turnover pressure
CURRENT_AT_BASELINE = dict(BASELINE)

# Flat attractiveness: no bucket is preferred over another
FLAT_SCORES = {bid: 0.0 for bid in BUCKET_IDS}


# ---------------------------------------------------------------------------
# Feasible scenarios
# ---------------------------------------------------------------------------


def test_returns_lp_solve_result():
    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
    )
    assert isinstance(result, LPSolveResult)


def test_feasible_returns_optimal_status():
    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    assert result.fallback_path is None


def test_feasible_weights_sum_to_100():
    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.target_weights is not None
    total = sum(result.target_weights.values())
    assert total == pytest.approx(100.0, abs=1e-4)


def test_feasible_weights_are_long_only():
    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.target_weights is not None
    for bid, w in result.target_weights.items():
        assert w >= -1e-6, f"{bid} weight is negative: {w}"


def test_feasible_weights_contain_all_bucket_ids():
    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.target_weights is not None
    assert set(result.target_weights.keys()) == set(BUCKET_IDS)


def test_score_tilts_weights_toward_preferred_bucket():
    # Strongly prefer long_duration_nominal_gilts
    scores = {bid: 0.0 for bid in BUCKET_IDS}
    scores["long_duration_nominal_gilts"] = 10.0

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=scores,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    assert result.target_weights is not None
    # Long gilts should be at or near the upper tilt band (20 + 10 = 30%)
    assert result.target_weights["long_duration_nominal_gilts"] >= 20.0


def test_minimum_cash_floor_is_respected():
    # Even with zero score for liquidity_reserve, floor must be honoured
    scores = {bid: 0.0 for bid in BUCKET_IDS}
    scores["liquidity_reserve"] = -100.0  # strongly penalise cash

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=scores,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    assert result.target_weights is not None
    assert result.target_weights["liquidity_reserve"] >= 5.0 - 1e-4


def test_minimum_short_duration_floor_is_respected():
    scores = {bid: 0.0 for bid in BUCKET_IDS}
    scores["short_duration_nominal_gilts"] = -100.0

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=scores,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    assert result.target_weights is not None
    assert result.target_weights["short_duration_nominal_gilts"] >= 10.0 - 1e-4


# ---------------------------------------------------------------------------
# Constraint-binding scenario
# ---------------------------------------------------------------------------


def test_binding_constraints_reported_when_tilt_band_is_tight():
    # Strong preference for long gilts — upper tilt band should bind
    scores = {bid: 0.0 for bid in BUCKET_IDS}
    scores["long_duration_nominal_gilts"] = 100.0

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=scores,
        regime_state="normal",
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    # At least one binding constraint should be reported
    assert len(result.binding_constraints) > 0


def test_turnover_limit_constrains_large_shift():
    # Long gilts 10% over baseline, equities 10% under — still within tilt bands.
    # Strong preference for equities / against long gilts, but 15% turnover cap
    # prevents moving more than 15% total.
    off_baseline_current = {
        "liquidity_reserve": 10.0,
        "short_duration_nominal_gilts": 15.0,
        "long_duration_nominal_gilts": 30.0,  # 10 over baseline
        "index_linked_gilts": 10.0,
        "listed_risk_assets": 25.0,  # 10 under baseline
        "diversifiers_and_manual": 10.0,
    }
    scores = {bid: 0.0 for bid in BUCKET_IDS}
    scores["listed_risk_assets"] = 100.0
    scores["long_duration_nominal_gilts"] = -100.0

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=off_baseline_current,
        score_coefficients=scores,
        regime_state="normal",  # 15% turnover limit
        policy=POLICY,
    )
    assert result.solver_status == "optimal"
    assert result.target_weights is not None
    total_turnover = sum(
        abs(result.target_weights[bid] - off_baseline_current[bid])
        for bid in BUCKET_IDS
    )
    assert total_turnover <= 15.0 + 1e-3


# ---------------------------------------------------------------------------
# Infeasible scenario
# ---------------------------------------------------------------------------


def test_infeasible_when_floors_exceed_100():
    # Force minimum floors that are mutually exclusive with full-investment
    impossible_policy = {
        "policy_version": "v1",
        "scenario_set_name": "v1",
        "default_constraints": {
            "long_only": True,
            "fully_invested": True,
            "baseline_tilt_band_pct": 50.0,
            "turnover_limit_pct_by_regime": {"normal": 100.0},
            "minimum_cash_mmf_pct": 60.0,   # 60% + 60% > 100%
            "minimum_short_duration_pct": 60.0,
            "scenario_floor_pct_of_current_value": {},
        },
    }

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=impossible_policy,
    )
    assert result.solver_status == "infeasible"
    assert result.target_weights is None
    assert result.fallback_path == "infeasible_at_constraints"
    assert len(result.notes) > 0


# ---------------------------------------------------------------------------
# Optional scenario sensitivities
# ---------------------------------------------------------------------------


def test_scenario_sensitivities_accepted_without_error():
    # Approximate: rates_up_parallel shocks short gilts by -1%, long gilts by -5%
    sensitivities = {
        "rates_up_parallel": {
            "liquidity_reserve": 0.0,
            "short_duration_nominal_gilts": -0.01,
            "long_duration_nominal_gilts": -0.05,
            "index_linked_gilts": -0.03,
            "listed_risk_assets": -0.05,
            "diversifiers_and_manual": -0.04,
        }
    }

    result = solve_bucket_weights(
        baseline_weights=BASELINE,
        current_weights=CURRENT_AT_BASELINE,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=POLICY,
        bucket_scenario_sensitivities=sensitivities,
    )
    assert result.solver_status == "optimal"
    assert result.target_weights is not None


def test_scenario_floor_enforced_when_sensitivities_provided():
    # Set up sensitivities so equity drawdown is very severe for equities.
    # Then force baseline to be all equities within tilt band.
    all_equity_baseline = {bid: 0.0 for bid in BUCKET_IDS}
    all_equity_baseline["listed_risk_assets"] = 80.0
    all_equity_baseline["liquidity_reserve"] = 10.0
    all_equity_baseline["short_duration_nominal_gilts"] = 10.0

    # This sensitivity would cause a large portfolio loss under equity_drawdown.
    # With a tight floor of 99%, the solver should be infeasible.
    tight_policy = {
        "policy_version": "v1",
        "scenario_set_name": "v1",
        "default_constraints": {
            "long_only": True,
            "fully_invested": True,
            "baseline_tilt_band_pct": 50.0,
            "turnover_limit_pct_by_regime": {"normal": 100.0},
            "minimum_cash_mmf_pct": 0.0,
            "minimum_short_duration_pct": 0.0,
            "scenario_floor_pct_of_current_value": {
                "equity_drawdown": 99.0,  # must retain 99% — impossible with any equity
            },
        },
    }
    sensitivities = {
        "equity_drawdown": {bid: -0.50 for bid in BUCKET_IDS}  # -50% on everything
    }

    result = solve_bucket_weights(
        baseline_weights=all_equity_baseline,
        current_weights=all_equity_baseline,
        score_coefficients=FLAT_SCORES,
        regime_state="normal",
        policy=tight_policy,
        bucket_scenario_sensitivities=sensitivities,
    )
    assert result.solver_status == "infeasible"
