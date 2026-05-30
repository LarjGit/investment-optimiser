from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from investment_optimiser.allocation_runs import ALLOCATION_RUN_SCHEMA_VERSION, AllocationRunRecord
from investment_optimiser.bucket_assignment import assign_bucket
from investment_optimiser.constraint_explanations import explain_binding_constraints
from investment_optimiser.lp_solver import solve_bucket_weights
from investment_optimiser.risk_gate import RiskGatedTrade, apply_risk_gate_to_proposed_state, risk_gate_trades
from investment_optimiser.scenario_engine import run_scenarios
from investment_optimiser.security_selection import select_trades

# Minimum GRY advantage (in decimal) for a candidate to qualify as a switch opportunity.
# Matches the threshold used in app.py:_build_switch_rows so both subsystems agree.
_SWITCH_GAP_THRESHOLD = 0.001   # 10 basis points

# Maximum candidates per bucket when a bucket has no current gilt holdings.
_MAX_EMPTY_BUCKET_CANDIDATES = 3

_INSTRUMENT_TO_ASSET_TYPE: dict[str, str] = {
    "Conventional": "gilt_conventional",
    "Index-linked": "gilt_index_linked",
}


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
    maturity_by_isin = _maturity_by_isin(gilt_ranking_df, today)
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

    filtered_candidates = _filter_gilt_candidates(
        gilt_ranking_df=gilt_ranking_df,
        current_holdings_df=enriched_holdings_df,
        today=today,
    )
    selection = select_trades(
        current_holdings_df=enriched_holdings_df,
        target_bucket_weights=lp_result.target_weights,
        total_portfolio_gbp=total_portfolio,
        gilt_candidates_df=filtered_candidates if not filtered_candidates.empty else None,
        policy=policy,
        gilt_price_lookup_df=gilt_ranking_df if not gilt_ranking_df.empty else None,
    )
    risk_gated = risk_gate_trades(
        selection.gated_trades, selection.proposed_state_df, policy, maturity_by_isin
    )
    executable_df = apply_risk_gate_to_proposed_state(risk_gated, selection.proposed_state_df)

    trades_payload = _trades_payload(selection.gated_trades, risk_gated)
    recommended_allocations = _recommended_allocations(executable_df, total_portfolio, policy)
    all_warnings = selection.warnings
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


def _maturity_by_isin(
    gilt_ranking_df: pd.DataFrame,
    today: date,
) -> dict[str, float | None]:
    if gilt_ranking_df.empty:
        return {}
    result: dict[str, float | None] = {}
    for _, row in gilt_ranking_df.iterrows():
        isin = row.get("isin")
        if isin:
            result[str(isin)] = _parse_maturity_years(row.get("maturity_date"), today)
    return result


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
            "is_new_position": t.is_new_position,
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


def _parse_maturity_years(mat_date_val: Any, today: date) -> float | None:
    """Return years to maturity from a maturity_date value, or None if unparseable."""
    if mat_date_val is None or pd.isna(mat_date_val):
        return None
    try:
        return (date.fromisoformat(str(mat_date_val)) - today).days / 365.25
    except (ValueError, TypeError):
        return None


def _derive_bucket_id(row: pd.Series) -> str | None:
    """Return bucket_id for a row that already has ``asset_type`` and ``_maturity_years``."""
    asset_type = row.get("asset_type")
    if not asset_type or pd.isna(asset_type):
        return None
    return assign_bucket({"asset_type": asset_type, "maturity_years": row.get("_maturity_years")}).bucket_id


def _enrich_gilt_ranking(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Add ``asset_type``, ``_maturity_years``, and ``bucket_id`` columns to a gilt ranking DataFrame."""
    df = df.copy()
    if "asset_type" not in df.columns:
        df["asset_type"] = df["instrument_type"].map(_INSTRUMENT_TO_ASSET_TYPE)
    df["_maturity_years"] = df["maturity_date"].map(lambda v: _parse_maturity_years(v, today))
    df["bucket_id"] = df.apply(_derive_bucket_id, axis=1)
    return df


def _filter_gilt_candidates(
    gilt_ranking_df: pd.DataFrame,
    current_holdings_df: pd.DataFrame,
    today: date,
) -> pd.DataFrame:
    """Return a pre-filtered candidate DataFrame for new-position MIP variables.

    Enriches gilt_ranking_df with ``asset_type`` and ``bucket_id`` columns, then
    applies signal-aligned filtering so only worthwhile candidates enter the MIP:

    * Gilts already held (by ISIN) are excluded — they are existing variables.
    * Rows missing ``clean_price_gbp`` or ``gry_pct`` are excluded.
    * Per bucket with held gilts: only candidates whose ``gry_pct`` exceeds the
      best held GRY by at least ``_SWITCH_GAP_THRESHOLD`` (same 10 bps the
      Signals tab uses).
    * For buckets with no held gilts: the top-``_MAX_EMPTY_BUCKET_CANDIDATES``
      candidates by GRY are included.
    """
    if gilt_ranking_df.empty:
        return pd.DataFrame()

    held_isins: set[str] = set()
    if not current_holdings_df.empty and "isin" in current_holdings_df.columns:
        held_isins = {str(v) for v in current_holdings_df["isin"].dropna()}

    df = _enrich_gilt_ranking(gilt_ranking_df, today)
    df = df[~df["isin"].isin(held_isins)]
    df = df[df["clean_price_gbp"].notna() & df["gry_pct"].notna() & df["bucket_id"].notna()]

    if df.empty:
        return pd.DataFrame()

    # Best held GRY per bucket — used to set the switch-opportunity threshold
    held_gry_by_bucket: dict[str, float] = {}
    if held_isins:
        held_df = _enrich_gilt_ranking(gilt_ranking_df[gilt_ranking_df["isin"].isin(held_isins)], today)
        for bucket, grp in held_df.groupby("bucket_id"):
            gry_vals = grp["gry_pct"].dropna()
            if not gry_vals.empty:
                held_gry_by_bucket[str(bucket)] = float(gry_vals.max())

    result_frames: list[pd.DataFrame] = []
    for bucket_id, grp in df.groupby("bucket_id"):
        bucket_str = str(bucket_id)
        if bucket_str in held_gry_by_bucket:
            threshold = held_gry_by_bucket[bucket_str] + _SWITCH_GAP_THRESHOLD
            eligible = grp[grp["gry_pct"] > threshold]
        else:
            eligible = grp.nlargest(_MAX_EMPTY_BUCKET_CANDIDATES, "gry_pct")
        result_frames.append(eligible)

    if not result_frames:
        return pd.DataFrame()

    out = pd.concat(result_frames, ignore_index=True)
    keep = [c for c in ["isin", "tidm", "asset_type", "bucket_id", "clean_price_gbp", "gry_pct",
                         "maturity_date", "instrument_name"] if c in out.columns]
    return out[keep].reset_index(drop=True)
