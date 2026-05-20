from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from investment_optimiser.allocation_runs import (
    ALLOCATION_RUN_SCHEMA_VERSION,
    AllocationRunRecord,
)

LIQUIDITY_BUCKET = "liquidity_reserve"


@dataclass(frozen=True)
class CashDeploymentResult:
    current_cash_pct: float
    target_cash_pct: float
    excess_cash_gbp: float
    total_portfolio_gbp: float
    deployments: list[dict[str, Any]]
    notes: list[str]


def compute_cash_deployment(
    holdings_df: pd.DataFrame,
    baseline_weights: dict[str, float],
    policy: dict[str, Any],
) -> CashDeploymentResult:
    if LIQUIDITY_BUCKET not in baseline_weights:
        raise ValueError(
            f"baseline_weights must include '{LIQUIDITY_BUCKET}'"
        )

    bucket_labels = {
        b["id"]: b["label"]
        for b in policy["baseline_bucket_model"]["buckets"]
    }

    total = float(holdings_df["market_value_gbp"].sum()) if not holdings_df.empty else 0.0
    if total == 0.0:
        note = "No holdings data available." if holdings_df.empty else "Total portfolio value is zero."
        return CashDeploymentResult(
            current_cash_pct=0.0,
            target_cash_pct=baseline_weights[LIQUIDITY_BUCKET],
            excess_cash_gbp=0.0,
            total_portfolio_gbp=0.0,
            deployments=[],
            notes=[note],
        )

    cash_rows = holdings_df[holdings_df["bucket_id"] == LIQUIDITY_BUCKET]
    current_cash_gbp = float(cash_rows["market_value_gbp"].sum())
    current_cash_pct = current_cash_gbp / total * 100.0
    target_cash_pct = baseline_weights[LIQUIDITY_BUCKET]
    target_cash_gbp = target_cash_pct / 100.0 * total
    excess_cash_gbp = max(0.0, current_cash_gbp - target_cash_gbp)

    if excess_cash_gbp == 0.0:
        return CashDeploymentResult(
            current_cash_pct=current_cash_pct,
            target_cash_pct=target_cash_pct,
            excess_cash_gbp=0.0,
            total_portfolio_gbp=total,
            deployments=[],
            notes=[],
        )

    other_weights = {
        bid: w for bid, w in baseline_weights.items() if bid != LIQUIDITY_BUCKET
    }

    bucket_values: dict[str, float] = {}
    if not holdings_df.empty:
        for bid, grp in holdings_df.groupby("bucket_id"):
            bucket_values[str(bid)] = float(grp["market_value_gbp"].sum())

    gaps = {
        bid: max(0.0, w / 100.0 * total - bucket_values.get(bid, 0.0))
        for bid, w in other_weights.items()
    }
    total_gap = sum(gaps.values())

    deployments: list[dict[str, Any]] = []
    if total_gap == 0.0:
        other_total_weight = sum(other_weights.values())
        if other_total_weight > 0:
            for bid, weight in other_weights.items():
                deployments.append({
                    "bucket_id": bid,
                    "label": bucket_labels.get(bid, bid),
                    "deploy_gbp": (weight / other_total_weight) * excess_cash_gbp,
                    "target_pct_of_portfolio": weight,
                })
    elif total_gap >= excess_cash_gbp:
        for bid, gap in gaps.items():
            if gap > 0:
                deployments.append({
                    "bucket_id": bid,
                    "label": bucket_labels.get(bid, bid),
                    "deploy_gbp": (gap / total_gap) * excess_cash_gbp,
                    "target_pct_of_portfolio": other_weights[bid],
                })
    else:
        remainder = excess_cash_gbp - total_gap
        other_total_weight = sum(other_weights.values())
        for bid, gap in gaps.items():
            weight = other_weights[bid]
            deploy_gbp = gap + (weight / other_total_weight) * remainder
            if deploy_gbp > 0:
                deployments.append({
                    "bucket_id": bid,
                    "label": bucket_labels.get(bid, bid),
                    "deploy_gbp": deploy_gbp,
                    "target_pct_of_portfolio": weight,
                })

    return CashDeploymentResult(
        current_cash_pct=current_cash_pct,
        target_cash_pct=target_cash_pct,
        excess_cash_gbp=excess_cash_gbp,
        total_portfolio_gbp=total,
        deployments=deployments,
        notes=[],
    )


def build_cash_run_record(
    result: CashDeploymentResult,
    holdings_df: pd.DataFrame,
    baseline_label: str,
    policy: dict[str, Any],
    snapshot_date: str,
) -> AllocationRunRecord:
    created_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    policy_version = policy["policy_version"]
    scenario_set_name = policy["scenario_set_name"]

    positions = (
        holdings_df[["bucket_id", "market_value_gbp"]].to_dict("records")
        if not holdings_df.empty
        else []
    )

    snapshot: dict[str, Any] = {
        "schema_version": ALLOCATION_RUN_SCHEMA_VERSION,
        "policy_inputs": {
            "policy_version": policy_version,
            "baseline_version": baseline_label,
            "scenario_set_name": scenario_set_name,
            "regime_state": "normal",
            "constraints": [],
            "score_coefficients": {},
        },
        "current_holdings": {
            "snapshot_date": snapshot_date,
            "total_market_value_gbp": result.total_portfolio_gbp,
            "positions": positions,
        },
        "outputs": {
            "solver_status": "cash_only_prorata",
            "fallback_path": "cash_slice_only",
            "recommended_allocations": result.deployments,
            "scenario_results": [],
        },
        "diagnostics": {
            "binding_constraints": [],
            "warnings": result.notes,
            "notes": [
                f"current_cash_pct={result.current_cash_pct:.2f}",
                f"target_cash_pct={result.target_cash_pct:.2f}",
                f"excess_cash_gbp={result.excess_cash_gbp:.2f}",
            ],
        },
    }

    return AllocationRunRecord(
        created_at=created_at,
        policy_version=policy_version,
        baseline_version=baseline_label,
        current_snapshot_date=snapshot_date,
        regime_state="normal",
        scenario_set_name=scenario_set_name,
        solver_status="cash_only_prorata",
        fallback_path="cash_slice_only",
        snapshot=snapshot,
    )
