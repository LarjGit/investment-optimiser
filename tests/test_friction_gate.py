from __future__ import annotations

import pandas as pd

from investment_optimiser.friction_gate import (
    GatedTrade,
    apply_gate_to_proposed_state,
    break_even_estimate,
    derive_friction_class,
    gate_trades,
)
from investment_optimiser.policy_pack import load_policy_pack
from investment_optimiser.trade_construction import Trade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(
    isin: str,
    asset_type: str | None,
    current_value_gbp: float,
    delta_value_gbp: float,
    *,
    bucket_id: str = "test_bucket",
    symbol: str = "SYM",
    is_new_position: bool = False,
) -> Trade:
    return Trade(
        isin=isin,
        symbol=symbol,
        bucket_id=bucket_id,
        asset_type=asset_type,
        is_new_position=is_new_position,
        current_value_gbp=current_value_gbp,
        target_value_gbp=current_value_gbp + delta_value_gbp,
        delta_value_gbp=delta_value_gbp,
    )


def _proposed_df(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _proposed_row(
    isin: str,
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


# ---------------------------------------------------------------------------
# Cycle 1: friction class routing — gilt types
# ---------------------------------------------------------------------------

def test_gilt_conventional_routes_to_conventional_gilts():
    assert derive_friction_class("gilt_conventional") == "conventional_gilts"


def test_gilt_index_linked_routes_to_index_linked_gilts():
    assert derive_friction_class("gilt_index_linked") == "index_linked_gilts"


# ---------------------------------------------------------------------------
# Cycle 2: friction class routing — cash and equities
# ---------------------------------------------------------------------------

def test_mmf_routes_to_cash_and_mmf():
    assert derive_friction_class("mmf") == "cash_and_mmf"


def test_equity_routes_to_equities_and_investment_trusts():
    assert derive_friction_class("equity") == "equities_and_investment_trusts"


def test_etf_routes_to_equities_and_investment_trusts():
    assert derive_friction_class("etf") == "equities_and_investment_trusts"


def test_none_asset_type_routes_to_equities_and_investment_trusts():
    assert derive_friction_class(None) == "equities_and_investment_trusts"


# ---------------------------------------------------------------------------
# Cycle 3: stamp duty — equity buy vs gilt buy
# ---------------------------------------------------------------------------

def test_gilt_buy_has_zero_stamp_duty():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 25.0}, policy)
    assert abs(gated[0].stamp_duty_gbp - 0.0) < 0.01


def test_equity_buy_has_stamp_duty_of_half_percent():
    policy = load_policy_pack()
    trade = _trade("EQ001", "equity", 0.0, +5_000.0, is_new_position=True)
    gated = gate_trades([trade], {"EQ001": 50.0}, policy)
    assert abs(gated[0].stamp_duty_gbp - 25.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 4: total friction for a gilt buy
# ---------------------------------------------------------------------------

def test_gilt_buy_friction_cost():
    # commission = 2 × 3.99 = 7.98
    # spread = 5.0/10000 × 5000 = 2.50
    # stamp_duty = 0.0
    # total = 10.48
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 25.0}, policy)
    g = gated[0]
    assert abs(g.commission_gbp - 7.98) < 0.01
    assert abs(g.spread_cost_gbp - 2.50) < 0.01
    assert abs(g.total_friction_gbp - 10.48) < 0.01


# ---------------------------------------------------------------------------
# Cycle 5: total friction for an equity buy
# ---------------------------------------------------------------------------

def test_equity_buy_friction_cost():
    # commission = 2 × 3.99 = 7.98
    # spread = 10.0/10000 × 5000 = 5.00
    # stamp_duty = 0.5/100 × 5000 = 25.00
    # total = 37.98
    policy = load_policy_pack()
    trade = _trade("EQ001", "equity", 0.0, +5_000.0, is_new_position=True)
    gated = gate_trades([trade], {"EQ001": 50.0}, policy)
    g = gated[0]
    assert abs(g.commission_gbp - 7.98) < 0.01
    assert abs(g.spread_cost_gbp - 5.00) < 0.01
    assert abs(g.total_friction_gbp - 37.98) < 0.01


# ---------------------------------------------------------------------------
# Cycle 6: break-even calculation for a gilt switch
# ---------------------------------------------------------------------------

def test_gilt_buy_break_even_months():
    # total_friction = 10.48, yield_improvement_bps = 25, position_size = 5000
    # annual_gain = 25/10000 × 5000 = 12.50
    # break_even_years = 10.48 / 12.50 = 0.8384
    # break_even_months ≈ 10.06
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 25.0}, policy)
    assert gated[0].break_even_months is not None
    assert abs(gated[0].break_even_months - 10.06) < 0.1


# ---------------------------------------------------------------------------
# Cycle 7: break-even edge cases → None → gate = red
# ---------------------------------------------------------------------------

def test_break_even_is_none_when_yield_improvement_is_none():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": None}, policy)
    assert gated[0].break_even_months is None
    assert gated[0].gate_outcome == "red"


def test_break_even_is_none_when_yield_improvement_is_zero():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 0.0}, policy)
    assert gated[0].break_even_months is None
    assert gated[0].gate_outcome == "red"


def test_break_even_is_none_when_yield_improvement_is_negative():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": -5.0}, policy)
    assert gated[0].break_even_months is None
    assert gated[0].gate_outcome == "red"


# ---------------------------------------------------------------------------
# Cycle 8: gate classification — green / amber / red
# (default hold = 2 years → thresholds: green < 12 months, amber 12–24, red > 24)
# ---------------------------------------------------------------------------

def test_gate_is_green_when_break_even_under_12_months():
    # 10 months < 12 = 50% of 24 months
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    # yield_improvement_bps=25 gives break_even≈10 months → green
    gated = gate_trades([trade], {"GB001": 25.0}, policy)
    assert gated[0].gate_outcome == "green"


def test_gate_is_amber_when_break_even_between_12_and_24_months():
    # Need break_even in [12, 24] months
    # break_even_months = (total_friction / (bps/10000 × size)) × 12
    # total_friction for gilt £5000 = 10.48
    # target: ~18 months → annual_gain = 10.48 / 1.5 = 6.987
    # bps = 6.987 / 5000 × 10000 = 13.97 bps
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 14.0}, policy)
    assert gated[0].gate_outcome == "amber"


def test_gate_is_red_when_break_even_over_24_months():
    # Need break_even > 24 months
    # total_friction=10.48, position=5000
    # 30 months → annual_gain = 10.48 / 2.5 = 4.192 → bps = 8.38
    # Use 8 bps (just under threshold so break_even > 24)
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 8.0}, policy)
    assert gated[0].gate_outcome == "red"


# ---------------------------------------------------------------------------
# Cycle 9: sell trades are not independently gated
# ---------------------------------------------------------------------------

def test_sell_trade_has_gate_outcome_not_gated():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, -5_000.0)
    gated = gate_trades([trade], {}, policy)
    assert len(gated) == 1
    assert gated[0].gate_outcome == "not_gated"


# ---------------------------------------------------------------------------
# Cycle 10: gate_trades() — mixed portfolio
# ---------------------------------------------------------------------------

def test_gate_trades_mixed_portfolio():
    policy = load_policy_pack()
    gilt_buy = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)   # green
    equity_buy = _trade("EQ001", "equity", 0.0, +5_000.0, is_new_position=True)  # red (no improvement)
    gilt_sell = _trade("GB002", "gilt_conventional", 8_000.0, -5_000.0)   # not_gated

    gated = gate_trades(
        [gilt_buy, equity_buy, gilt_sell],
        {"GB001": 25.0, "EQ001": None},
        policy,
    )

    assert len(gated) == 3
    outcomes = {g.trade.isin: g.gate_outcome for g in gated}
    assert outcomes["GB001"] == "green"
    assert outcomes["EQ001"] == "red"
    assert outcomes["GB002"] == "not_gated"


# ---------------------------------------------------------------------------
# Cycle 11: apply_gate_to_proposed_state — red buy reverts, liquidity adjusted
# ---------------------------------------------------------------------------

def test_red_buy_reverts_to_current_value_and_liquidity_absorbs_delta():
    # New position (cash deployment): current=0, proposed=5000
    # Red gate → proposed reverts to 0; liquidity_reserve rises by 5000
    policy = load_policy_pack()
    trade = _trade("EQ001", "equity", 0.0, +5_000.0, is_new_position=True)
    gated = gate_trades([trade], {"EQ001": None}, policy)

    proposed = _proposed_df(
        _proposed_row("EQ001", "listed_risk_assets", "equity", 5_000.0),
        _proposed_row("MMF001", "liquidity_reserve", "mmf", 10_000.0),
    )

    result = apply_gate_to_proposed_state(gated, proposed)
    result = result.set_index("isin")

    assert abs(result.loc["EQ001", "proposed_value_gbp"] - 0.0) < 0.01
    assert abs(result.loc["MMF001", "proposed_value_gbp"] - 15_000.0) < 0.01


def test_green_buy_proposed_value_is_not_reverted():
    policy = load_policy_pack()
    trade = _trade("GB001", "gilt_conventional", 10_000.0, +5_000.0)
    gated = gate_trades([trade], {"GB001": 25.0}, policy)

    proposed = _proposed_df(
        _proposed_row("GB001", "short_duration_nominal_gilts", "gilt_conventional", 15_000.0),
        _proposed_row("MMF001", "liquidity_reserve", "mmf", 5_000.0),
    )

    result = apply_gate_to_proposed_state(gated, proposed)
    result = result.set_index("isin")

    assert abs(result.loc["GB001", "proposed_value_gbp"] - 15_000.0) < 0.01
    assert abs(result.loc["MMF001", "proposed_value_gbp"] - 5_000.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 12: apply_gate_to_proposed_state — no liquidity_reserve row → one created
# ---------------------------------------------------------------------------

def test_red_buy_creates_liquidity_reserve_when_absent():
    policy = load_policy_pack()
    trade = _trade("EQ001", "equity", 0.0, +3_000.0, is_new_position=True)
    gated = gate_trades([trade], {"EQ001": None}, policy)

    proposed = _proposed_df(
        _proposed_row("EQ001", "listed_risk_assets", "equity", 3_000.0),
    )

    result = apply_gate_to_proposed_state(gated, proposed)
    liq_rows = result[result["bucket_id"] == "liquidity_reserve"]
    assert len(liq_rows) == 1
    assert abs(liq_rows.iloc[0]["proposed_value_gbp"] - 3_000.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 13: break_even_estimate — standalone signal-layer helper
# ---------------------------------------------------------------------------

def test_break_even_estimate_green():
    # position £10k, 77 bps gap, £3.99 commission, 5 bps spread, 2y hold
    # total_friction = 2*3.99 + (5/10000)*10000 = 7.98 + 5.0 = 12.98
    # annual_gain = 0.0077 * 10000 = 77.0
    # break_even = (12.98/77) * 12 ≈ 2.02 months → green
    months, outcome = break_even_estimate(
        position_size_gbp=10_000.0,
        yield_gap_pct=0.0077,
        commission_gbp=3.99,
        spread_bps=5.0,
        hold_period_years=2.0,
    )
    assert months is not None
    assert abs(months - 2.02) < 0.1
    assert outcome == "green"


def test_break_even_estimate_amber():
    # position £10k, 8 bps gap, £3.99 commission, 5 bps spread, 2y hold
    # total_friction = 12.98, annual_gain = 8.0
    # break_even = (12.98/8) * 12 ≈ 19.47 months → amber (12–24)
    months, outcome = break_even_estimate(
        position_size_gbp=10_000.0,
        yield_gap_pct=0.0008,
        commission_gbp=3.99,
        spread_bps=5.0,
        hold_period_years=2.0,
    )
    assert months is not None
    assert 12.0 < months < 24.0
    assert outcome == "amber"


def test_break_even_estimate_red():
    # position £10k, 5 bps gap, £3.99 commission, 5 bps spread, 2y hold
    # total_friction = 12.98, annual_gain = 5.0
    # break_even = (12.98/5) * 12 ≈ 31.15 months → red (> 24)
    months, outcome = break_even_estimate(
        position_size_gbp=10_000.0,
        yield_gap_pct=0.0005,
        commission_gbp=3.99,
        spread_bps=5.0,
        hold_period_years=2.0,
    )
    assert months is not None
    assert months > 24.0
    assert outcome == "red"


def test_break_even_estimate_zero_gap():
    months, outcome = break_even_estimate(
        position_size_gbp=10_000.0,
        yield_gap_pct=0.0,
        commission_gbp=3.99,
        spread_bps=5.0,
        hold_period_years=2.0,
    )
    assert months is None
    assert outcome == "red"


def test_break_even_estimate_negative_gap():
    months, outcome = break_even_estimate(
        position_size_gbp=10_000.0,
        yield_gap_pct=-0.01,
        commission_gbp=3.99,
        spread_bps=5.0,
        hold_period_years=2.0,
    )
    assert months is None
    assert outcome == "red"
