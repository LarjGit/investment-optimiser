from __future__ import annotations

from typing import Any

import pandas as pd


def build_allocation_change_df(
    prior_snap: dict[str, Any],
    current_snap: dict[str, Any],
    threshold: float = 0.001,
) -> pd.DataFrame:
    threshold_pct = threshold * 100

    prior_allocs = {
        row["bucket_id"]: row
        for row in prior_snap["outputs"]["recommended_allocations"]
    }
    current_allocs = {
        row["bucket_id"]: row
        for row in current_snap["outputs"]["recommended_allocations"]
    }

    all_buckets = sorted(set(prior_allocs) | set(current_allocs))
    rows = []
    for bid in all_buckets:
        prior_row = prior_allocs.get(bid)
        current_row = current_allocs.get(bid)
        prior_pct = prior_row["proposed_pct"] if prior_row else 0.0
        current_pct = current_row["proposed_pct"] if current_row else 0.0
        delta_pct = current_pct - prior_pct
        if abs(delta_pct) <= threshold_pct:
            continue
        label = (current_row or prior_row)["label"]
        rows.append({
            "bucket_id": bid,
            "label": label,
            "prior_pct": prior_pct,
            "current_pct": current_pct,
            "delta_pct": delta_pct,
        })

    if not rows:
        return pd.DataFrame(columns=["bucket_id", "label", "prior_pct", "current_pct", "delta_pct"])
    return pd.DataFrame(rows)


def build_headline_metrics(
    prior_snap: dict[str, Any],
    current_snap: dict[str, Any],
) -> dict[str, Any]:
    prior_value = prior_snap["current_holdings"]["total_market_value_gbp"]
    current_value = current_snap["current_holdings"]["total_market_value_gbp"]

    prior_trades = len(prior_snap["outputs"]["trades"])
    current_trades = len(current_snap["outputs"]["trades"])

    prior_regime = prior_snap["policy_inputs"]["regime_state"]
    current_regime = current_snap["policy_inputs"]["regime_state"]

    prior_scenario_set = prior_snap["policy_inputs"]["scenario_set_name"]
    current_scenario_set = current_snap["policy_inputs"]["scenario_set_name"]

    return {
        "prior_value_gbp": prior_value,
        "current_value_gbp": current_value,
        "value_delta_gbp": current_value - prior_value,
        "prior_trade_count": prior_trades,
        "current_trade_count": current_trades,
        "trade_count_delta": current_trades - prior_trades,
        "regime_changed": prior_regime != current_regime,
        "prior_regime": prior_regime,
        "current_regime": current_regime,
        "scenario_set_changed": prior_scenario_set != current_scenario_set,
        "prior_scenario_set": prior_scenario_set,
        "current_scenario_set": current_scenario_set,
    }
