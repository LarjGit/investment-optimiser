from __future__ import annotations

from investment_optimiser.blocked_trade_display import categorise_blocked_trades


def _trade(
    friction_outcome: str,
    risk_outcome: str,
    delta: float = 5000.0,
    symbol: str = "TR00",
) -> dict:
    return {
        "symbol": symbol,
        "bucket_id": "test",
        "delta_value_gbp": delta,
        "friction_outcome": friction_outcome,
        "friction_note": f"friction note for {friction_outcome}",
        "risk_outcome": risk_outcome,
        "risk_note": f"risk note for {risk_outcome}",
    }


def test_no_blocked_trades_returns_empty_lists() -> None:
    trades = [
        _trade("green", "pass"),
        _trade("amber", "pass"),
        _trade("not_gated", "not_gated", delta=-5000.0),
    ]
    friction, risk = categorise_blocked_trades(trades)
    assert friction == []
    assert risk == []


def test_empty_input_returns_empty_lists() -> None:
    friction, risk = categorise_blocked_trades([])
    assert friction == []
    assert risk == []


def test_friction_blocked_trade_goes_to_friction_list() -> None:
    blocked = _trade("red", "not_gated", symbol="TR32")
    trades = [blocked, _trade("green", "pass")]
    friction, risk = categorise_blocked_trades(trades)
    assert len(friction) == 1
    assert friction[0]["symbol"] == "TR32"
    assert risk == []


def test_risk_blocked_trade_goes_to_risk_list() -> None:
    blocked = _trade("green", "blocked_concentration", symbol="TR50")
    trades = [blocked, _trade("green", "pass")]
    friction, risk = categorise_blocked_trades(trades)
    assert friction == []
    assert len(risk) == 1
    assert risk[0]["symbol"] == "TR50"


def test_friction_blocked_trade_not_duplicated_in_risk_list() -> None:
    # A friction-blocked trade has risk_outcome="not_gated" (per design); it must
    # not appear in the risk list even if that outcome is technically non-passing.
    blocked = _trade("red", "not_gated")
    friction, risk = categorise_blocked_trades([blocked])
    assert len(friction) == 1
    assert risk == []


def test_all_risk_block_outcomes_categorised_correctly() -> None:
    trades = [
        _trade("green", "blocked_concentration", symbol="A"),
        _trade("green", "blocked_maturity", symbol="B"),
        _trade("green", "blocked_liquidity", symbol="C"),
    ]
    friction, risk = categorise_blocked_trades(trades)
    assert friction == []
    assert len(risk) == 3
    assert {t["symbol"] for t in risk} == {"A", "B", "C"}


def test_multiple_friction_and_risk_blocks_separated() -> None:
    trades = [
        _trade("red", "not_gated", symbol="F1"),
        _trade("red", "not_gated", symbol="F2"),
        _trade("green", "blocked_concentration", symbol="R1"),
        _trade("green", "pass", symbol="P1"),
    ]
    friction, risk = categorise_blocked_trades(trades)
    assert {t["symbol"] for t in friction} == {"F1", "F2"}
    assert {t["symbol"] for t in risk} == {"R1"}
