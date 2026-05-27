"""Presentation helpers for index-linked gilt display.

Keeps IL-specific sidebar and exclusion rendering out of the app monolith.
All functions write into the current Streamlit rendering context.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

_STALENESS_THRESHOLD_DAYS = 7


def render_observed_inflation_sidebar_panel(freshness: dict[str, Any] | None) -> None:
    """Render the read-only observed inflation data panel.

    *freshness* is a dict with keys ``fetched_at`` (ISO timestamp of the last
    successful DMO D10C fetch), ``provider``, ``confidence_tier``,
    ``is_degraded``, and ``gilt_count``.  Pass ``None`` when no data has
    been loaded yet.

    Call this inside the current sidebar context.
    """
    if freshness is None:
        st.warning(
            "No observed inflation data available — "
            "run a Market Data refresh to populate DMO D10C index ratios.",
            icon="⚠️",
        )
        return

    fetched_at_str: str = freshness["fetched_at"]
    try:
        # fetched_at is stored as "YYYY-MM-DDTHH:MM:SSZ" — take the date part only.
        fetched_date = date.fromisoformat(fetched_at_str[:10])
    except (TypeError, ValueError):
        fetched_date = None

    display_date = fetched_date.strftime("%d %b %Y") if fetched_date is not None else fetched_at_str
    st.metric("Last refreshed", display_date)

    gilt_count = freshness.get("gilt_count")
    if gilt_count is not None:
        st.caption(f"IL gilts covered: {gilt_count}")
    st.caption(f"Source: {freshness['provider']} · {freshness['confidence_tier']}")

    is_degraded = bool(freshness.get("is_degraded", False))
    age_days = (date.today() - fetched_date).days if fetched_date is not None else 0
    if is_degraded:
        st.warning(
            "Observed inflation data is degraded — results may be less reliable.",
            icon="⚠️",
        )
    elif age_days > _STALENESS_THRESHOLD_DAYS:
        st.warning(
            f"Observed inflation data may be stale ({age_days} days old) — "
            "consider running a Market Data refresh.",
            icon="⚠️",
        )
    else:
        st.info("Observed data is current.", icon="ℹ️")


def render_il_exclusion_reasons(il_df: pd.DataFrame) -> None:
    """Render per-gilt IL exclusion warnings below the gilt ranking table.

    Shows a warning for each row in *il_df* that has a non-null
    ``il_exclusion_reason``, so the user understands why certain
    index-linked gilts are absent from the ranking.
    """
    if il_df.empty or "il_exclusion_reason" not in il_df.columns:
        return

    reasons = il_df["il_exclusion_reason"].dropna().tolist()
    if not reasons:
        return

    st.caption("Index-linked gilt exclusions:")
    for reason in reasons:
        st.warning(str(reason), icon="⚠️")
