from __future__ import annotations

import pandas as pd
import pytest

from investment_optimiser.friction_gate import GatedTrade
from investment_optimiser.policy_pack import load_policy_pack
from investment_optimiser.risk_gate import (
    RiskGatedTrade,
    apply_risk_gate_to_proposed_state,
    risk_gate_trades,
)
from investment_optimiser.trade_construction import Trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POLICY = load_policy_pack()

_LIQUIDITY_BUCKET = "liquidity_reserve"


def _trade(
    isin: str,
    delta_value_gbp: float,
    current_value_gbp: float = 0.0,
    *,
    asset_type: str = "gilt_conventional",
    bucket_id: str = "short_duration_nominal_gilts",
) -> Trade:
    return Trade(
        isin=isin,
        symbol=isin,
        bucket_id=bucket_id,
        asset_type=asset_type,
        is_new_position=delta_value_gbp > 0 and current_value_gbp == 0.0,
        current_value_gbp=current_value_gbp,
        target_value_gbp=current_value_gbp + delta_value_gbp,
        delta_value_gbp=delta_value_gbp,
    )


def _gated(
    isin: str,
    delta_value_gbp: float,
    current_value_gbp: float = 0.0,
    *,
    gate_outcome: str = "green",
    asset_type: str = "gilt_conventional",
    bucket_id: str = "short_duration_nominal_gilts",
) -> GatedTrade:
    t = _trade(isin, delta_value_gbp, current_value_gbp, asset_type=asset_type, bucket_id=bucket_id)
    return GatedTrade(
        trade=t,
        friction_class="conventional_gilts",
        commission_gbp=0.0,
        spread_cost_gbp=0.0,
        stamp_duty_gbp=0.0,
        total_friction_gbp=0.0,
        yield_improvement_bps=50.0,
        break_even_months=6.0,
        gate_outcome=gate_outcome,
        gate_note="Test gated trade",
    )


def _proposed_row(
    isin: str | None,
    bucket_id: str,
    asset_type: str,
    proposed_value_gbp: float,
) -> dict:
    return {
        "isin": isin,
        "symbol": isin,
        "bucket_id": bucket_id,
        "asset_type": asset_type,
        "proposed_value_gbp": proposed_value_gbp,
    }


def _liquidity_row(proposed_value_gbp: float) -> dict:
    return _proposed_row(None, _LIQUIDITY_BUCKET, "mmf", proposed_value_gbp)


# ---------------------------------------------------------------------------
# Cycle 1: Sell trade passes through as not_gated
# ---------------------------------------------------------------------------

def test_sell_trade_is_not_gated() -> None:
    gt = _gated("GB0001", -5_000.0, current_value_gbp=10_000.0, gate_outcome="not_gated")
    proposed = pd.DataFrame([
        _proposed_row("GB0001", "short_duration_nominal_gilts", "gilt_conventional", 5_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {})
    assert len(result) == 1
    rgt = result[0]
    assert rgt.risk_gate_outcome == "not_gated"
    assert "sell" in rgt.risk_gate_note.lower() or "not gated" in rgt.risk_gate_note.lower()


# ---------------------------------------------------------------------------
# Cycle 2: Already-red friction trade passes through as not_gated
# ---------------------------------------------------------------------------

def test_friction_red_trade_is_not_gated() -> None:
    gt = _gated("GB0002", 5_000.0, gate_outcome="red")
    proposed = pd.DataFrame([
        _proposed_row("GB0002", "short_duration_nominal_gilts", "gilt_conventional", 5_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {})
    assert result[0].risk_gate_outcome == "not_gated"
    assert "friction" in result[0].risk_gate_note.lower() or "already" in result[0].risk_gate_note.lower()


# ---------------------------------------------------------------------------
# Cycle 3: Buy trade under concentration cap → pass
# ---------------------------------------------------------------------------

def test_buy_under_concentration_cap_passes() -> None:
    # max_single_position_pct = 12.5%; proposed position = 12,000 / 100,000 = 12% → pass
    gt = _gated("GB0003", 12_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0003", "short_duration_nominal_gilts", "gilt_conventional", 12_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 78_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0003": 5.0})
    assert result[0].risk_gate_outcome == "pass"


# ---------------------------------------------------------------------------
# Cycle 4: Buy trade exceeding concentration cap → blocked_concentration
# ---------------------------------------------------------------------------

def test_buy_exceeding_concentration_cap_blocked() -> None:
    # 13,000 / 100,000 = 13% > 12.5% → blocked_concentration
    gt = _gated("GB0004", 13_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0004", "short_duration_nominal_gilts", "gilt_conventional", 13_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 77_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0004": 5.0})
    rgt = result[0]
    assert rgt.risk_gate_outcome == "blocked_concentration"
    assert "13.0" in rgt.risk_gate_note or "13%" in rgt.risk_gate_note
    assert "12.5" in rgt.risk_gate_note


# ---------------------------------------------------------------------------
# Cycle 5: Gilt buy under maturity ceiling → pass
# ---------------------------------------------------------------------------

def test_gilt_buy_under_maturity_ceiling_passes() -> None:
    # max_maturity_years = 15.0; maturity = 10.0 → pass
    gt = _gated("GB0005", 10_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0005", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 80_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0005": 10.0})
    assert result[0].risk_gate_outcome == "pass"


# ---------------------------------------------------------------------------
# Cycle 6: Gilt buy exceeding maturity ceiling → blocked_maturity
# ---------------------------------------------------------------------------

def test_gilt_buy_exceeding_maturity_ceiling_blocked() -> None:
    # maturity = 16.0 > 15.0 → blocked_maturity
    gt = _gated("GB0006", 10_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0006", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 80_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0006": 16.0})
    rgt = result[0]
    assert rgt.risk_gate_outcome == "blocked_maturity"
    assert "16" in rgt.risk_gate_note
    assert "15" in rgt.risk_gate_note


# ---------------------------------------------------------------------------
# Cycle 7: Buy trade with unknown maturity (None) → not blocked for maturity
# ---------------------------------------------------------------------------

def test_buy_with_none_maturity_not_blocked_for_maturity() -> None:
    gt = _gated("GB0007", 10_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0007", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 80_000.0),
        _liquidity_row(10_000.0),
    ])
    # isin not in dict → maturity unknown → no maturity block
    result = risk_gate_trades([gt], proposed, _POLICY, {})
    assert result[0].risk_gate_outcome != "blocked_maturity"


# ---------------------------------------------------------------------------
# Cycle 8: Portfolio with sufficient liquidity → buy passes liquidity check
# ---------------------------------------------------------------------------

def test_sufficient_liquidity_buy_passes() -> None:
    # liquidity = 6,000 / 100,000 = 6% > 5% → pass
    gt = _gated("GB0008", 10_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0008", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 84_000.0),
        _liquidity_row(6_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0008": 5.0})
    assert result[0].risk_gate_outcome == "pass"


# ---------------------------------------------------------------------------
# Cycle 9: Portfolio with insufficient liquidity → all buy trades blocked_liquidity
# ---------------------------------------------------------------------------

def test_insufficient_liquidity_blocks_all_buys() -> None:
    # liquidity = 4,000 / 100,000 = 4% < 5% → blocked_liquidity
    gt1 = _gated("GB0009A", 10_000.0)
    gt2 = _gated("GB0009B", 8_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0009A", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _proposed_row("GB0009B", "short_duration_nominal_gilts", "gilt_conventional", 8_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 78_000.0),
        _liquidity_row(4_000.0),
    ])
    result = risk_gate_trades([gt1, gt2], proposed, _POLICY, {})
    assert result[0].risk_gate_outcome == "blocked_liquidity"
    assert result[1].risk_gate_outcome == "blocked_liquidity"
    assert "4" in result[0].risk_gate_note or "4.0" in result[0].risk_gate_note
    assert "5" in result[0].risk_gate_note


# ---------------------------------------------------------------------------
# Cycle 10: Concentration blocks before maturity is evaluated (first rule wins)
# ---------------------------------------------------------------------------

def test_concentration_blocks_before_maturity() -> None:
    # 13% > 12.5% (concentration) AND maturity 16y > 15y — should be blocked_concentration
    gt = _gated("GB0010", 13_000.0)
    proposed = pd.DataFrame([
        _proposed_row("GB0010", "short_duration_nominal_gilts", "gilt_conventional", 13_000.0),
        _proposed_row("OTHER", "long_duration_nominal_gilts", "gilt_conventional", 77_000.0),
        _liquidity_row(10_000.0),
    ])
    result = risk_gate_trades([gt], proposed, _POLICY, {"GB0010": 16.0})
    assert result[0].risk_gate_outcome == "blocked_concentration"


# ---------------------------------------------------------------------------
# Cycle 11: apply_risk_gate_to_proposed_state reverts blocked trades,
#           freed cash → liquidity_reserve
# ---------------------------------------------------------------------------

def test_apply_risk_gate_reverts_blocked_and_frees_to_liquidity() -> None:
    # Buy trade blocked_concentration — current_value=5_000, proposed=13_000
    # After revert: position back to 5_000; freed 8_000 added to liquidity
    gt = _gated("GB0011", 8_000.0, current_value_gbp=5_000.0)
    rgt = RiskGatedTrade(
        gated_trade=gt,
        risk_gate_outcome="blocked_concentration",
        risk_gate_note="Position would be 13.0% — limit is 12.5%",
    )
    proposed = pd.DataFrame([
        _proposed_row("GB0011", "short_duration_nominal_gilts", "gilt_conventional", 13_000.0),
        _liquidity_row(5_000.0),
    ])
    result_df = apply_risk_gate_to_proposed_state([rgt], proposed)

    gb11_val = result_df.loc[result_df["isin"] == "GB0011", "proposed_value_gbp"].iloc[0]
    liq_val = result_df.loc[result_df["bucket_id"] == _LIQUIDITY_BUCKET, "proposed_value_gbp"].iloc[0]
    assert gb11_val == pytest.approx(5_000.0)
    assert liq_val == pytest.approx(13_000.0)  # 5_000 + 8_000 freed


# ---------------------------------------------------------------------------
# Cycle 12: apply_risk_gate_to_proposed_state leaves unblocked trades unchanged
# ---------------------------------------------------------------------------

def test_apply_risk_gate_leaves_passing_trades_unchanged() -> None:
    gt = _gated("GB0012", 8_000.0, current_value_gbp=2_000.0)
    rgt = RiskGatedTrade(
        gated_trade=gt,
        risk_gate_outcome="pass",
        risk_gate_note="All checks passed",
    )
    proposed = pd.DataFrame([
        _proposed_row("GB0012", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0),
        _liquidity_row(5_000.0),
    ])
    result_df = apply_risk_gate_to_proposed_state([rgt], proposed)

    gb12_val = result_df.loc[result_df["isin"] == "GB0012", "proposed_value_gbp"].iloc[0]
    liq_val = result_df.loc[result_df["bucket_id"] == _LIQUIDITY_BUCKET, "proposed_value_gbp"].iloc[0]
    assert gb12_val == pytest.approx(10_000.0)
    assert liq_val == pytest.approx(5_000.0)
