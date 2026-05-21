from __future__ import annotations

import re
from typing import Any

NEAR_BINDING_THRESHOLD = 0.005  # 0.5 percentage point

_BUCKET_FLOOR_FIELDS: dict[str, str] = {
    "liquidity_reserve": "minimum_cash_mmf_pct",
    "short_duration_nominal_gilts": "minimum_short_duration_pct",
}

_DEFAULT_REGIME = "normal"


def explain_binding_constraints(
    binding_constraints: list[str],
    marginals: dict[str, float],
    policy: dict[str, Any],
    bucket_labels: dict[str, str],
) -> list[dict]:
    constraints = policy.get("default_constraints", {})
    results = []
    for label in binding_constraints:
        shadow = marginals.get(label)
        status = (
            "binding"
            if shadow is not None and abs(shadow) > NEAR_BINDING_THRESHOLD
            else "near_binding"
        )
        results.append({
            "label": label,
            "short": _explain(label, constraints, bucket_labels),
            "shadow_price": shadow,
            "status": status,
        })
    return results


def _explain(label: str, constraints: dict, bucket_labels: dict[str, str]) -> str:
    if label == "total_turnover_limit":
        limit = constraints.get("turnover_limit_pct_by_regime", {}).get(_DEFAULT_REGIME, "?")
        return f"Portfolio-wide turnover cap reached ({limit}% in normal regime)"

    m = re.fullmatch(r"upper_bound\[(.+)\]", label)
    if m:
        bid = m.group(1)
        tilt = constraints.get("baseline_tilt_band_pct", "?")
        return f"{bucket_labels.get(bid, bid)} at tilt band ceiling (baseline + {tilt}%)"

    m = re.fullmatch(r"lower_bound\[(.+)\]", label)
    if m:
        bid = m.group(1)
        bucket = bucket_labels.get(bid, bid)
        floor_field = _BUCKET_FLOOR_FIELDS.get(bid)
        if floor_field:
            floor = constraints.get(floor_field, "?")
            return f"{bucket} at minimum floor ({floor}%)"
        tilt = constraints.get("baseline_tilt_band_pct", "?")
        return f"{bucket} at tilt band floor (baseline − {tilt}%)"

    m = re.fullmatch(r"turnover_upper\[(.+)\]", label)
    if m:
        bid = m.group(1)
        return f"{bucket_labels.get(bid, bid)} turnover upper bound reached"

    m = re.fullmatch(r"turnover_lower\[(.+)\]", label)
    if m:
        bid = m.group(1)
        return f"{bucket_labels.get(bid, bid)} turnover lower bound reached"

    m = re.fullmatch(r"scenario_floor\[(.+)\]", label)
    if m:
        scenario_id = m.group(1)
        floors = constraints.get("scenario_floor_pct_of_current_value", {})
        floor_pct = floors.get(scenario_id, "?")
        return f"Scenario floor: {scenario_id} requires portfolio ≥ {floor_pct}% of current value"

    return label
