from __future__ import annotations

from typing import Any

import pandas as pd

_FLOAT_TOLERANCE = 1e-4


def _floats_differ(a: float | None, b: float | None) -> bool:
    """Return True when two nullable floats differ by more than _FLOAT_TOLERANCE."""
    if a is None or b is None:
        return a != b
    return abs(a - b) > _FLOAT_TOLERANCE


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


def build_inflation_attribution(
    prior_snap: dict[str, Any],
    current_snap: dict[str, Any],
) -> dict[str, Any]:
    """Classify why a recommendation changed relative to inflation inputs.

    Returns a dict with:
      change_category: "observed_data" | "forward_assumptions" | "both"
                       | "non_inflation" | "unknown"
      observed_data_changed: bool
      forward_assumptions_changed: bool
      prior/current_observed_as_of_date: str | None
      prior/current_forward_pre_2030_pct: float | None
      prior/current_forward_post_2030_pct: float | None

    When either snapshot lacks ``inflation_inputs`` the category is "unknown".
    """
    prior_infl = prior_snap.get("policy_inputs", {}).get("inflation_inputs")
    current_infl = current_snap.get("policy_inputs", {}).get("inflation_inputs")

    p = prior_infl or {}
    c = current_infl or {}
    prior_obs_date = p.get("observed_as_of_date")
    current_obs_date = c.get("observed_as_of_date")
    prior_pre = p.get("forward_rpi_pre_2030_pct")
    current_pre = c.get("forward_rpi_pre_2030_pct")
    prior_post = p.get("forward_rpi_post_2030_pct")
    current_post = c.get("forward_rpi_post_2030_pct")

    if prior_infl is None or current_infl is None:
        category = "unknown"
        observed_data_changed = False
        forward_assumptions_changed = False
    else:
        observed_data_changed = prior_obs_date != current_obs_date
        forward_assumptions_changed = _floats_differ(prior_pre, current_pre) or _floats_differ(prior_post, current_post)
        if observed_data_changed and forward_assumptions_changed:
            category = "both"
        elif observed_data_changed:
            category = "observed_data"
        elif forward_assumptions_changed:
            category = "forward_assumptions"
        else:
            category = "non_inflation"

    return {
        "change_category": category,
        "observed_data_changed": observed_data_changed,
        "forward_assumptions_changed": forward_assumptions_changed,
        "prior_observed_as_of_date": prior_obs_date,
        "current_observed_as_of_date": current_obs_date,
        "prior_forward_pre_2030_pct": prior_pre,
        "current_forward_pre_2030_pct": current_pre,
        "prior_forward_post_2030_pct": prior_post,
        "current_forward_post_2030_pct": current_post,
    }


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
