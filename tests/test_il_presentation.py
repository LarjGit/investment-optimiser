"""Tests for il_presentation sidebar panel and exclusion reason helpers.

Each test exercises a single observable behaviour through the public interface
of il_presentation.py. AppTest.from_function creates a minimal Streamlit app
so we can drive the functions in a real Streamlit context.

Freshness data is injected via session_state rather than closures because
AppTest serialises the app function and cannot capture outer-scope variables.
"""
from __future__ import annotations

from datetime import date, timedelta

from streamlit.testing.v1 import AppTest


# ---------------------------------------------------------------------------
# Standalone app stubs (module-level so AppTest can serialise them cleanly)
# ---------------------------------------------------------------------------

def _panel_app() -> None:
    import streamlit as _st
    from investment_optimiser.il_presentation import render_observed_inflation_sidebar_panel

    freshness = _st.session_state.get("_test_freshness")
    with _st.sidebar:
        render_observed_inflation_sidebar_panel(freshness)


def _exclusions_app() -> None:
    import streamlit as _st
    import pandas as _pd
    from investment_optimiser.il_presentation import render_il_exclusion_reasons

    reasons = _st.session_state.get("_test_reasons", [])
    il_df = _pd.DataFrame({"il_exclusion_reason": reasons})
    render_il_exclusion_reasons(il_df)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_panel(freshness) -> AppTest:
    at = AppTest.from_function(_panel_app)
    at.session_state["_test_freshness"] = freshness
    at.run()
    return at


def _fresh_today() -> dict:
    # fetched_at uses the same timestamp format as dmo_d10c_handler stores it.
    today = date.today()
    return {
        "fetched_at": f"{today.isoformat()}T08:00:00Z",
        "provider": "DMO_D10C",
        "confidence_tier": "authoritative",
        "is_degraded": False,
        "gilt_count": 8,
    }


# ---------------------------------------------------------------------------
# render_observed_inflation_sidebar_panel
# ---------------------------------------------------------------------------

def test_panel_warns_when_no_data() -> None:
    """No freshness → a warning prompting the user to run a market refresh."""
    at = _run_panel(None)

    assert not at.exception
    assert len(at.sidebar.warning) == 1
    msg = at.sidebar.warning[0].value.lower()
    assert "refresh" in msg or "no observed" in msg


def test_panel_shows_info_for_fresh_healthy_data() -> None:
    """Fresh, non-degraded data → info message; no warning."""
    at = _run_panel(_fresh_today())

    assert not at.exception
    assert len(at.sidebar.warning) == 0
    assert len(at.sidebar.info) == 1


def test_panel_shows_gilt_count_when_present() -> None:
    """Gilt count appears as a caption when included in freshness."""
    at = _run_panel(_fresh_today())

    assert not at.exception
    caption_texts = [c.value for c in at.sidebar.caption]
    assert any("8" in t for t in caption_texts), f"Expected gilt count in captions: {caption_texts}"


def test_panel_warns_for_degraded_data() -> None:
    """Degraded data → warning containing 'degraded'."""
    freshness = {**_fresh_today(), "is_degraded": True, "confidence_tier": "degraded"}
    at = _run_panel(freshness)

    assert not at.exception
    assert len(at.sidebar.warning) == 1
    assert "degraded" in at.sidebar.warning[0].value.lower()


def test_panel_warns_for_stale_data() -> None:
    """Data older than staleness threshold → warning containing 'stale'."""
    stale_ts = f"{(date.today() - timedelta(days=10)).isoformat()}T08:00:00Z"
    freshness = {**_fresh_today(), "fetched_at": stale_ts}
    at = _run_panel(freshness)

    assert not at.exception
    assert len(at.sidebar.warning) == 1
    assert "stale" in at.sidebar.warning[0].value.lower()


def test_panel_does_not_warn_for_data_within_threshold() -> None:
    """Data exactly at the staleness threshold → no stale warning."""
    recent_ts = f"{(date.today() - timedelta(days=5)).isoformat()}T08:00:00Z"
    freshness = {**_fresh_today(), "fetched_at": recent_ts}
    at = _run_panel(freshness)

    assert not at.exception
    assert len(at.sidebar.warning) == 0


# ---------------------------------------------------------------------------
# render_il_exclusion_reasons
# ---------------------------------------------------------------------------

def test_exclusion_reasons_rendered_as_warnings() -> None:
    """Each non-null exclusion reason produces a st.warning."""
    at = AppTest.from_function(_exclusions_app)
    at.session_state["_test_reasons"] = [
        "GB00B: no observed data",
        "GB00C: forward assumption missing",
    ]
    at.run()

    assert not at.exception
    assert len(at.warning) == 2


def test_exclusion_reasons_silent_when_all_null() -> None:
    """All-null exclusion reasons produce no output."""
    at = AppTest.from_function(_exclusions_app)
    at.session_state["_test_reasons"] = []
    at.run()

    assert not at.exception
    assert len(at.warning) == 0
