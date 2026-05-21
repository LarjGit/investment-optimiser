from __future__ import annotations

from typing import Any

import pandas as pd

from investment_optimiser.blocked_trade_display import categorise_blocked_trades
from investment_optimiser.recommendation_change_summary import (
    build_allocation_change_df,
    build_headline_metrics,
)


def build_narrative_components(
    snapshot: dict[str, Any],
    prior_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trades = snapshot.get("outputs", {}).get("trades", [])
    friction_blocked, risk_blocked = categorise_blocked_trades(trades)
    blocked_ids = {id(t) for t in friction_blocked + risk_blocked}
    approved_trades = [t for t in trades if id(t) not in blocked_ids]

    diagnostics = snapshot.get("diagnostics", {})
    binding_constraints = diagnostics.get("binding_constraint_details", [])

    headline: dict[str, Any] | None = None
    allocation_deltas: pd.DataFrame | None = None
    if prior_snapshot is not None:
        headline = build_headline_metrics(prior_snapshot, snapshot)
        allocation_deltas = build_allocation_change_df(prior_snapshot, snapshot)

    return {
        "approved_trades": approved_trades,
        "friction_blocked": friction_blocked,
        "risk_blocked": risk_blocked,
        "binding_constraints": binding_constraints,
        "headline": headline,
        "allocation_deltas": allocation_deltas,
    }
