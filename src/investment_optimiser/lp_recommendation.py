from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from investment_optimiser.allocation_runs import ALLOCATION_RUN_SCHEMA_VERSION, AllocationRunRecord
from investment_optimiser.constraint_explanations import explain_binding_constraints
from investment_optimiser.friction_gate import apply_gate_to_proposed_state, gate_trades
from investment_optimiser.holdings_translator import translate_bucket_targets_to_holdings
from investment_optimiser.lp_solver import solve_bucket_weights
from investment_optimiser.risk_gate import RiskGatedTrade, apply_risk_gate_to_proposed_state, risk_gate_trades
from investment_optimiser.scenario_engine import run_scenarios
from investment_optimiser.trade_construction import construct_trades


_REGIME_STATE_DEFAULT = "normal"


@dataclass(frozen=True)
class LPRecommendationResult:
    solver_status: str
    record: AllocationRunRecord
    trades_payload: list[dict[str, Any]]
    executable_df: pd.DataFrame
    warnings: list[str]


def build_lp_recommendation(
    enriched_holdings_df: pd.DataFrame,
    baseline_weights: dict[str, float],
    baseline_label: str,
    policy: dict[str, Any],
    snapshot_date: str,
    gilt_ranking_df: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> LPRecommendationResult:
    today = reference_date or date.today()
    total_portfolio = (
        float(enriched_holdings_df["market_value_gbp"].sum())
        if not enriched_holdings_df.empty
        else 0.0
    )

    current_weights = _current_weights(enriched_holdings_df, baseline_weights, total_portfolio)
    gilt_prices = _gilt_prices(gilt_ranking_df)
    maturity_by_isin = _maturity_by_isin(gilt_ranking_df, today)
    yield_improvement_bps = _yield_improvement_bps(gilt_ranking_df)
    score_coefficients = _score_coefficients(baseline_weights, current_weights)

    lp_result = solve_bucket_weights(
        baseline_weights=baseline_weights,
        current_weights=current_weights,
        score_coefficients=score_coefficients,
        regime_state=_REGIME_STATE_DEFAULT,
        policy=policy,
    )

    positions = (
        enriched_holdings_df[["bucket_id", "market_value_gbp"]].to_dict("records")
        if not enriched_holdings_df.empty
        else []
    )

    if lp_result.solver_status != "optimal":
        snapshot = _build_snapshot(
            policy=policy,
            baseline_label=baseline_label,
            snapshot_date=snapshot_date,
            total_portfolio=total_portfolio,
            positions=positions,
            score_coefficients=score_coefficients,
            solver_status=lp_result.solver_status,
            fallback_path=lp_result.fallback_path,
            target_weights={},
            trades_payload=[],
            executable_records=[],
            recommended_allocations=[],
            binding_constraints=[],
            warnings=[],
            notes=lp_result.notes,
        )
        return LPRecommendationResult(
            solver_status=lp_result.solver_status,
            record=_make_record(policy, baseline_label, snapshot_date, lp_result.solver_status, lp_result.fallback_path, snapshot),
            trades_payload=[],
            executable_df=pd.DataFrame(),
            warnings=lp_result.notes,
        )

    translation = translate_bucket_targets_to_holdings(
        bucket_target_weights=lp_result.target_weights,
        enriched_holdings_df=enriched_holdings_df,
        total_portfolio_value_gbp=total_portfolio,
        gilt_candidates_df=gilt_ranking_df if not gilt_ranking_df.empty else None,
        reference_date=today,
    )

    trade_result = construct_trades(translation.target_df, gilt_prices)
    gated_trades = gate_trades(trade_result.trades, yield_improvement_bps, policy)
    post_friction_df = apply_gate_to_proposed_state(gated_trades, trade_result.proposed_state_df)
    risk_gated = risk_gate_trades(gated_trades, post_friction_df, policy, maturity_by_isin)
    executable_df = apply_risk_gate_to_proposed_state(risk_gated, post_friction_df)

    trades_payload = _trades_payload(gated_trades, risk_gated)
    recommended_allocations = _recommended_allocations(executable_df, total_portfolio, policy)
    all_warnings = trade_result.warnings + translation.warnings
    scenario_results = run_scenarios(
        enriched_holdings_df, executable_df, policy, gilt_ranking_df, reference_date=today
    )

    bucket_labels = {b["id"]: b["label"] for b in policy["baseline_bucket_model"]["buckets"]}
    constraint_details = explain_binding_constraints(
        lp_result.binding_constraints, lp_result.marginals, policy, bucket_labels
    )

    snapshot = _build_snapshot(
        policy=policy,
        baseline_label=baseline_label,
        snapshot_date=snapshot_date,
        total_portfolio=total_portfolio,
        positions=positions,
        score_coefficients=score_coefficients,
        solver_status=lp_result.solver_status,
        fallback_path=lp_result.fallback_path,
        target_weights=lp_result.target_weights,
        trades_payload=trades_payload,
        executable_records=executable_df.to_dict("records"),
        recommended_allocations=recommended_allocations,
        binding_constraints=lp_result.binding_constraints,
        binding_constraint_details=constraint_details,
        marginals=lp_result.marginals,
        warnings=all_warnings,
        notes=lp_result.notes,
        scenario_results=scenario_results,
    )

    return LPRecommendationResult(
        solver_status=lp_result.solver_status,
        record=_make_record(policy, baseline_label, snapshot_date, lp_result.solver_status, None, snapshot),
        trades_payload=trades_payload,
        executable_df=executable_df,
        warnings=all_warnings,
    )

def _current_weights(
    enriched_holdings_df: pd.DataFrame,
    baseline_weights: dict[str, float],
    total_portfolio: float,
) -> dict[str, float]:
    weights: dict[str, float] = {bid: 0.0 for bid in baseline_weights}
    if enriched_holdings_df.empty or total_portfolio == 0.0:
        return weights
    for bid, grp in enriched_holdings_df.groupby("bucket_id"):
        if bid in weights:
            weights[str(bid)] = float(grp["market_value_gbp"].sum()) / total_portfolio * 100.0
    return weights


def _gilt_prices(gilt_ranking_df: pd.DataFrame) -> dict[str, float]:
    if gilt_ranking_df.empty:
        return {}
    return {
        str(row["isin"]): float(row["clean_price_gbp"])
        for _, row in gilt_ranking_df.iterrows()
        if pd.notna(row.get("clean_price_gbp")) and row.get("isin")
    }


def _maturity_by_isin(
    gilt_ranking_df: pd.DataFrame,
    today: date,
) -> dict[str, float | None]:
    if gilt_ranking_df.empty:
        return {}
    result: dict[str, float | None] = {}
    for _, row in gilt_ranking_df.iterrows():
        isin = row.get("isin")
        maturity_date = row.get("maturity_date")
        if isin and pd.notna(maturity_date):
            try:
                mat = date.fromisoformat(str(maturity_date))
                result[str(isin)] = (mat - today).days / 365.25
            except (ValueError, TypeError):
                result[str(isin)] = None
        elif isin:
            result[str(isin)] = None
    return result


def _yield_improvement_bps(gilt_ranking_df: pd.DataFrame) -> dict[str, float | None]:
    if gilt_ranking_df.empty:
        return {}
    return {
        str(row["isin"]): float(row["gry_pct"]) * 100.0
        for _, row in gilt_ranking_df.iterrows()
        if pd.notna(row.get("gry_pct")) and row.get("isin")
    }


def _score_coefficients(
    baseline_weights: dict[str, float],
    current_weights: dict[str, float],
) -> dict[str, float]:
    return {
        bid: round(baseline_weights.get(bid, 0.0) - current_weights.get(bid, 0.0), 4)
        for bid in baseline_weights
    }


def _trades_payload(
    gated_trades: list,
    risk_gated: list[RiskGatedTrade],
) -> list[dict[str, Any]]:
    risk_by_isin = {rgt.gated_trade.trade.isin: rgt for rgt in risk_gated}
    rows = []
    for gt in gated_trades:
        t = gt.trade
        rgt = risk_by_isin.get(t.isin)
        rows.append({
            "isin": t.isin,
            "symbol": t.symbol,
            "bucket_id": t.bucket_id,
            "asset_type": t.asset_type,
            "delta_value_gbp": round(t.delta_value_gbp, 2),
            "current_value_gbp": round(t.current_value_gbp, 2),
            "target_value_gbp": round(t.target_value_gbp, 2),
            "friction_outcome": gt.gate_outcome,
            "friction_note": gt.gate_note,
            "risk_outcome": rgt.risk_gate_outcome if rgt else "not_evaluated",
            "risk_note": rgt.risk_gate_note if rgt else "",
        })
    return rows


def _recommended_allocations(
    executable_df: pd.DataFrame,
    total_portfolio: float,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    if executable_df.empty or total_portfolio == 0.0:
        return []
    bucket_labels = {b["id"]: b["label"] for b in policy["baseline_bucket_model"]["buckets"]}
    result = []
    for bid, grp in executable_df.groupby("bucket_id"):
        value = float(grp["proposed_value_gbp"].sum())
        result.append({
            "bucket_id": str(bid),
            "label": bucket_labels.get(str(bid), str(bid)),
            "proposed_value_gbp": round(value, 2),
            "proposed_pct": round(value / total_portfolio * 100.0, 2),
        })
    return result


def _build_snapshot(
    *,
    policy: dict[str, Any],
    baseline_label: str,
    snapshot_date: str,
    total_portfolio: float,
    positions: list[dict],
    score_coefficients: dict[str, float],
    solver_status: str,
    fallback_path: str | None,
    target_weights: dict[str, float],
    trades_payload: list[dict],
    executable_records: list[dict],
    recommended_allocations: list[dict],
    binding_constraints: list[str],
    warnings: list[str],
    notes: list[str],
    binding_constraint_details: list[dict] | None = None,
    marginals: dict[str, float] | None = None,
    scenario_results: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": ALLOCATION_RUN_SCHEMA_VERSION,
        "policy_inputs": {
            "policy_version": policy["policy_version"],
            "baseline_version": baseline_label,
            "scenario_set_name": policy["scenario_set_name"],
            "regime_state": _REGIME_STATE_DEFAULT,
            "constraints": list(policy["default_constraints"].keys()),
            "score_coefficients": score_coefficients,
        },
        "current_holdings": {
            "snapshot_date": snapshot_date,
            "total_market_value_gbp": total_portfolio,
            "positions": positions,
        },
        "outputs": {
            "solver_status": solver_status,
            "fallback_path": fallback_path,
            "target_weights": target_weights,
            "trades": trades_payload,
            "executable_portfolio": executable_records,
            "recommended_allocations": recommended_allocations,
            "scenario_results": scenario_results or [],
        },
        "diagnostics": {
            "binding_constraints": binding_constraints,
            "binding_constraint_details": binding_constraint_details or [],
            "marginals": marginals or {},
            "warnings": warnings,
            "notes": notes,
        },
    }


def _make_record(
    policy: dict[str, Any],
    baseline_label: str,
    snapshot_date: str,
    solver_status: str,
    fallback_path: str | None,
    snapshot: dict[str, Any],
) -> AllocationRunRecord:
    return AllocationRunRecord(
        created_at=_utc_now(),
        policy_version=policy["policy_version"],
        baseline_version=baseline_label,
        current_snapshot_date=snapshot_date,
        regime_state=_REGIME_STATE_DEFAULT,
        scenario_set_name=policy["scenario_set_name"],
        solver_status=solver_status,
        fallback_path=fallback_path,
        snapshot=snapshot,
    )


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
