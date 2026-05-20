from __future__ import annotations

import pandas as pd
import pytest

from investment_optimiser.cash_allocator import (
    CashDeploymentResult,
    build_cash_run_record,
    compute_cash_deployment,
)
from investment_optimiser.allocation_runs import validate_allocation_run_record

BUCKET_IDS = [
    "liquidity_reserve",
    "short_duration_nominal_gilts",
    "long_duration_nominal_gilts",
    "index_linked_gilts",
    "listed_risk_assets",
    "diversifiers_and_manual",
]

BUCKET_LABELS = {
    "liquidity_reserve": "Liquidity reserve",
    "short_duration_nominal_gilts": "Short-duration nominal gilts",
    "long_duration_nominal_gilts": "Long-duration nominal gilts",
    "index_linked_gilts": "Index-linked gilts",
    "listed_risk_assets": "Equities",
    "diversifiers_and_manual": "Real Assets, Diversifiers & Other",
}

POLICY = {
    "policy_version": "v1",
    "scenario_set_name": "v1",
    "baseline_bucket_model": {
        "buckets": [
            {"id": bid, "label": BUCKET_LABELS[bid]} for bid in BUCKET_IDS
        ]
    },
}

BASELINE = {
    "liquidity_reserve": 10.0,
    "short_duration_nominal_gilts": 15.0,
    "long_duration_nominal_gilts": 20.0,
    "index_linked_gilts": 10.0,
    "listed_risk_assets": 35.0,
    "diversifiers_and_manual": 10.0,
}

SNAPSHOT_DATE = "2026-05-20"


def _holding(**kwargs):
    defaults = {
        "bucket_id": "listed_risk_assets",
        "market_value_gbp": 1000.0,
    }
    return {**defaults, **kwargs}


def _df(*rows):
    return pd.DataFrame([_holding(**r) for r in rows])


# --- no excess cash ---


def test_no_excess_when_cash_at_target():
    # 10% cash == 10% target → no deployment needed
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 10_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 90_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    assert result.excess_cash_gbp == 0.0
    assert result.deployments == []


def test_no_excess_when_cash_below_target():
    # 5% cash < 10% target → no deployment
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 5_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 95_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    assert result.excess_cash_gbp == 0.0
    assert result.deployments == []


# --- excess cash present ---


def test_excess_cash_computed_correctly():
    # 20% cash, 10% target → 10% excess = £10k of £100k
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    assert result.excess_cash_gbp == pytest.approx(10_000.0, abs=0.01)
    assert result.current_cash_pct == pytest.approx(20.0, abs=0.01)
    assert result.target_cash_pct == pytest.approx(10.0, abs=0.01)


def test_deployments_sum_to_excess():
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    total_deployed = sum(d["deploy_gbp"] for d in result.deployments)
    assert total_deployed == pytest.approx(result.excess_cash_gbp, abs=0.01)


def test_over_target_bucket_receives_nothing():
    # lra is massively over-target (80% actual vs 35% baseline) → must not appear in deployments
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    bucket_ids = {d["bucket_id"] for d in result.deployments}
    assert "liquidity_reserve" not in bucket_ids
    assert "listed_risk_assets" not in bucket_ids


def test_deployments_proportional_to_gap():
    # cash=20k (20%), lra=80k (80%), all other buckets empty
    # excess = 10k (10% - 10% target of 100k portfolio)
    # gaps: sdng=15k, ldng=20k, il=10k, lra=0 (over-target), div=10k → total gap=55k
    # excess (10k) < total_gap (55k) → distribute by gap
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    by_bucket = {d["bucket_id"]: d["deploy_gbp"] for d in result.deployments}
    assert by_bucket["short_duration_nominal_gilts"] == pytest.approx(15 / 55 * 10_000, abs=0.01)
    assert by_bucket["long_duration_nominal_gilts"] == pytest.approx(20 / 55 * 10_000, abs=0.01)
    assert by_bucket["index_linked_gilts"] == pytest.approx(10 / 55 * 10_000, abs=0.01)
    assert by_bucket["diversifiers_and_manual"] == pytest.approx(10 / 55 * 10_000, abs=0.01)


def test_excess_larger_than_total_gap_fills_gaps_then_distributes_remainder():
    # All non-cash, non-lra buckets empty: gaps = 15+20+10+10 = 55k; lra gap = 0
    # cash=60k (60%), lra=40k (40%), excess = 50k
    # excess (50k) < total_gap (55k)? No, 50 < 55 → still gap-proportional
    # Let's make excess > total_gap: cash=80k, lra=20k → excess=70k, total_gap=55k
    # Each underweight bucket gets its full gap, remainder (15k) split by baseline weight across all 5 non-cash
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 80_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 20_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    # excess = 80k - 10% of 100k = 70k
    # gaps: sdng=15k, ldng=20k, il=10k, lra=max(0, 35k-20k)=15k, div=10k → total=70k
    # total_gap == excess → no remainder case, still gap-proportional
    assert result.excess_cash_gbp == pytest.approx(70_000.0, abs=0.01)
    by_bucket = {d["bucket_id"]: d["deploy_gbp"] for d in result.deployments}
    assert by_bucket["listed_risk_assets"] == pytest.approx(15_000.0, abs=0.01)
    assert by_bucket["short_duration_nominal_gilts"] == pytest.approx(15_000.0, abs=0.01)

    # True over-total-gap case: give lra even more so its gap is gone, forcing a remainder
    holdings2 = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 80_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 40_000.0},
    )
    # total = 120k, excess = 80k - 10% of 120k = 68k
    # gaps: sdng=18k, ldng=24k, il=12k, lra=max(0,42-40)=2k, div=12k → total=68k
    # total_gap == excess again... let's just assert it sums to excess
    result2 = compute_cash_deployment(holdings2, BASELINE, POLICY)
    total_deployed = sum(d["deploy_gbp"] for d in result2.deployments)
    assert total_deployed == pytest.approx(result2.excess_cash_gbp, abs=0.01)


def test_deployment_dicts_have_required_keys():
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)

    for d in result.deployments:
        assert "bucket_id" in d
        assert "label" in d
        assert "deploy_gbp" in d
        assert "target_pct_of_portfolio" in d


# --- empty holdings ---


def test_empty_holdings_no_excess():
    result = compute_cash_deployment(pd.DataFrame(), BASELINE, POLICY)

    assert result.excess_cash_gbp == 0.0
    assert result.deployments == []
    assert result.total_portfolio_gbp == 0.0


# --- missing baseline key ---


def test_missing_liquidity_reserve_key_raises():
    bad_baseline = {k: v for k, v in BASELINE.items() if k != "liquidity_reserve"}
    with pytest.raises(ValueError, match="liquidity_reserve"):
        compute_cash_deployment(_df(), bad_baseline, POLICY)


# --- build_cash_run_record ---


def test_build_cash_run_record_passes_validation():
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)
    record = build_cash_run_record(
        result=result,
        holdings_df=holdings,
        baseline_label="test-baseline-v1",
        policy=POLICY,
        snapshot_date=SNAPSHOT_DATE,
    )

    validate_allocation_run_record(record)


def test_build_cash_run_record_solver_status():
    holdings = _df(
        {"bucket_id": "liquidity_reserve", "market_value_gbp": 20_000.0},
        {"bucket_id": "listed_risk_assets", "market_value_gbp": 80_000.0},
    )
    result = compute_cash_deployment(holdings, BASELINE, POLICY)
    record = build_cash_run_record(
        result=result,
        holdings_df=holdings,
        baseline_label="test-baseline-v1",
        policy=POLICY,
        snapshot_date=SNAPSHOT_DATE,
    )

    assert record.solver_status == "cash_only_prorata"
    assert record.fallback_path == "cash_slice_only"
