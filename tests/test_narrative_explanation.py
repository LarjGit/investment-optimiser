from __future__ import annotations

import pytest

from investment_optimiser.narrative_explanation import build_narrative_components


def _make_snapshot(
    trades: list | None = None,
    binding_constraint_details: list | None = None,
    recommended_allocations: list | None = None,
    total_market_value_gbp: float = 100_000.0,
    regime: str = "normal",
    scenario_set: str = "base",
) -> dict:
    return {
        "policy_inputs": {
            "regime_state": regime,
            "scenario_set_name": scenario_set,
        },
        "current_holdings": {
            "total_market_value_gbp": total_market_value_gbp,
        },
        "outputs": {
            "trades": trades or [],
            "recommended_allocations": recommended_allocations or [],
        },
        "diagnostics": {
            "binding_constraint_details": binding_constraint_details or [],
        },
    }


def _trade(
    symbol: str,
    friction_outcome: str = "green",
    risk_outcome: str = "pass",
    delta: float = 1_000.0,
    friction_note: str = "",
    risk_note: str = "",
) -> dict:
    return {
        "symbol": symbol,
        "isin": None,
        "bucket_id": "bucket_a",
        "asset_type": None,
        "delta_value_gbp": delta,
        "current_value_gbp": 10_000.0,
        "target_value_gbp": 11_000.0,
        "friction_outcome": friction_outcome,
        "friction_note": friction_note,
        "risk_outcome": risk_outcome,
        "risk_note": risk_note,
    }


# --- basic structure ---


def test_empty_snapshot_returns_empty_collections() -> None:
    result = build_narrative_components(_make_snapshot())
    assert result["approved_trades"] == []
    assert result["friction_blocked"] == []
    assert result["risk_blocked"] == []
    assert result["binding_constraints"] == []
    assert result["headline"] is None
    assert result["allocation_deltas"] is None


# --- trade categorisation ---


def test_approved_trades_returned() -> None:
    trades = [
        _trade("TR27", friction_outcome="green", risk_outcome="pass"),
        _trade("TR30", friction_outcome="amber", risk_outcome="pass"),
    ]
    result = build_narrative_components(_make_snapshot(trades=trades))
    assert len(result["approved_trades"]) == 2
    assert result["friction_blocked"] == []
    assert result["risk_blocked"] == []


def test_friction_blocked_separated() -> None:
    trades = [
        _trade("TR27", friction_outcome="red", risk_outcome="not_gated"),
        _trade("TR30", friction_outcome="green", risk_outcome="pass"),
    ]
    result = build_narrative_components(_make_snapshot(trades=trades))
    assert len(result["friction_blocked"]) == 1
    assert result["friction_blocked"][0]["symbol"] == "TR27"
    assert len(result["approved_trades"]) == 1
    assert result["approved_trades"][0]["symbol"] == "TR30"


def test_risk_blocked_separated() -> None:
    trades = [
        _trade("EQ1", friction_outcome="green", risk_outcome="blocked_concentration"),
        _trade("TR27", friction_outcome="green", risk_outcome="pass"),
    ]
    result = build_narrative_components(_make_snapshot(trades=trades))
    assert len(result["risk_blocked"]) == 1
    assert result["risk_blocked"][0]["symbol"] == "EQ1"
    assert len(result["approved_trades"]) == 1


def test_friction_blocked_takes_priority_over_risk() -> None:
    trades = [_trade("TR27", friction_outcome="red", risk_outcome="blocked_maturity")]
    result = build_narrative_components(_make_snapshot(trades=trades))
    assert len(result["friction_blocked"]) == 1
    assert result["risk_blocked"] == []
    assert result["approved_trades"] == []


def test_not_gated_sell_trade_is_approved() -> None:
    trades = [_trade("TR27", friction_outcome="not_gated", risk_outcome="not_gated", delta=-5_000.0)]
    result = build_narrative_components(_make_snapshot(trades=trades))
    assert len(result["approved_trades"]) == 1
    assert result["friction_blocked"] == []


# --- binding constraints ---


def test_binding_constraints_read_from_diagnostics() -> None:
    details = [
        {
            "label": "total_turnover_limit",
            "short": "Portfolio-wide turnover cap reached",
            "shadow_price": 0.02,
            "status": "binding",
        }
    ]
    result = build_narrative_components(_make_snapshot(binding_constraint_details=details))
    assert len(result["binding_constraints"]) == 1
    assert result["binding_constraints"][0]["label"] == "total_turnover_limit"


def test_missing_diagnostics_key_returns_empty_constraints() -> None:
    snapshot = _make_snapshot()
    del snapshot["diagnostics"]
    result = build_narrative_components(snapshot)
    assert result["binding_constraints"] == []


def test_empty_binding_constraint_details_returns_empty() -> None:
    result = build_narrative_components(_make_snapshot(binding_constraint_details=[]))
    assert result["binding_constraints"] == []


# --- prior-snapshot comparison ---


def test_no_prior_snapshot_headline_and_deltas_are_none() -> None:
    result = build_narrative_components(_make_snapshot())
    assert result["headline"] is None
    assert result["allocation_deltas"] is None


def test_with_prior_snapshot_headline_value_delta() -> None:
    prior = _make_snapshot(total_market_value_gbp=90_000.0)
    current = _make_snapshot(total_market_value_gbp=100_000.0)
    result = build_narrative_components(current, prior_snapshot=prior)
    assert result["headline"] is not None
    assert result["headline"]["value_delta_gbp"] == pytest.approx(10_000.0)


def test_with_prior_snapshot_allocation_deltas_populated() -> None:
    prior_allocs = [{"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 50_000.0, "proposed_pct": 50.0}]
    current_allocs = [{"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 60_000.0, "proposed_pct": 60.0}]
    prior = _make_snapshot(recommended_allocations=prior_allocs)
    current = _make_snapshot(recommended_allocations=current_allocs)
    result = build_narrative_components(current, prior_snapshot=prior)
    assert result["allocation_deltas"] is not None
    assert len(result["allocation_deltas"]) == 1
    assert result["allocation_deltas"].iloc[0]["delta_pct"] == pytest.approx(10.0)


def test_with_prior_snapshot_no_change_returns_empty_deltas() -> None:
    allocs = [{"bucket_id": "equity", "label": "Equity", "proposed_value_gbp": 50_000.0, "proposed_pct": 50.0}]
    snap = _make_snapshot(recommended_allocations=allocs)
    result = build_narrative_components(snap, prior_snapshot=snap)
    assert result["allocation_deltas"] is not None
    assert result["allocation_deltas"].empty
