"""Tests for security_selection.select_trades — TDD vertical slice.

Each test group builds on the last; run the full file to see cumulative progress.
"""
from __future__ import annotations

import pandas as pd
import pytest

from investment_optimiser.security_selection import SecuritySelectionResult, select_trades


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_policy(min_trade_size_gbp: float = 500.0, tilt_band_pct: float = 10.0) -> dict:
    return {
        "shared_assumption_schema": {
            "fields": [
                {"key": "interactive_investor_trade_fee_gbp", "default": 3.99},
                {"key": "expected_hold_period_years", "default": 2.0},
                {
                    "key": "spread_bps_by_friction_class",
                    "default": {
                        "conventional_gilts": 5.0,
                        "index_linked_gilts": 8.0,
                        "equities_and_investment_trusts": 10.0,
                        "cash_and_mmf": 0.0,
                    },
                },
                {"key": "minimum_trade_size_gbp", "default": min_trade_size_gbp},
            ]
        },
        "default_constraints": {
            "tilt_band_pct": tilt_band_pct,
            "max_single_position_pct": 25.0,
            "minimum_cash_mmf_pct": 5.0,
            "max_maturity_years": 15.0,
        },
    }


def _make_holdings(*rows: tuple) -> pd.DataFrame:
    """Build a minimal holdings DataFrame.

    Each row: (isin, symbol, asset_type, market_value_gbp, bucket_id)
    """
    return pd.DataFrame(
        [
            {
                "isin": r[0],
                "symbol": r[1],
                "asset_type": r[2],
                "market_value_gbp": float(r[3]),
                "bucket_id": r[4],
                "quantity": 0,
            }
            for r in rows
        ]
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 1 — Tracer bullet: module exists, return type correct
# ──────────────────────────────────────────────────────────────────────────────

def test_select_trades_returns_security_selection_result():
    """select_trades returns a SecuritySelectionResult with all required attributes."""
    holdings = _make_holdings(
        ("GB0001234567", "TN25", "gilt_conventional", 10_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 5_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 66.67,
        "liquidity_reserve": 33.33,
    }
    result = select_trades(holdings, target_weights, 15_000.0, None, _make_policy())

    assert isinstance(result, SecuritySelectionResult)
    assert isinstance(result.proposed_state_df, pd.DataFrame)
    assert isinstance(result.gated_trades, list)
    assert isinstance(result.solver_status, str)
    assert isinstance(result.warnings, list)


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 2 — proposed_state_df schema
# ──────────────────────────────────────────────────────────────────────────────

def test_proposed_state_df_has_required_columns():
    """proposed_state_df must contain the columns expected by risk_gate_trades."""
    holdings = _make_holdings(
        ("GB0001234567", "TN25", "gilt_conventional", 10_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 5_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 66.67,
        "liquidity_reserve": 33.33,
    }
    result = select_trades(holdings, target_weights, 15_000.0, None, _make_policy())

    required = {"isin", "symbol", "bucket_id", "asset_type", "proposed_value_gbp"}
    assert required.issubset(set(result.proposed_state_df.columns))


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 3 — Cash balance preserved
# ──────────────────────────────────────────────────────────────────────────────

def test_cash_balance_preserved_after_rebalancing():
    """Sum of proposed_value_gbp must equal total_portfolio_gbp within £1 (lot rounding)."""
    total = 30_000.0
    holdings = _make_holdings(
        ("GB0001111111", "T26", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0002222222", "T30", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0003333333", "T34", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0004444444", "T38", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0005555555", "T41", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0006666666", "T45", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 9_000.0, "liquidity_reserve"),
    )
    # Target: reduce long gilts from 70% to 56%, grow MMF from 30% to 44%
    target_weights = {
        "long_duration_nominal_gilts": 56.0,
        "liquidity_reserve": 44.0,
    }
    result = select_trades(holdings, target_weights, total, None, _make_policy())

    proposed_total = result.proposed_state_df["proposed_value_gbp"].sum()
    assert abs(proposed_total - total) < 1.0, (
        f"Cash not balanced: proposed={proposed_total:.2f}, expected={total:.2f}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 4 — No-change case
# ──────────────────────────────────────────────────────────────────────────────

def test_no_change_when_weights_already_match():
    """When current weights already equal target weights, no trades should be generated."""
    total = 20_000.0
    holdings = _make_holdings(
        ("GB0001234567", "TN25", "gilt_conventional", 14_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 6_000.0, "liquidity_reserve"),
    )
    # Target matches current weights exactly (70% gilts, 30% MMF)
    target_weights = {
        "long_duration_nominal_gilts": 70.0,
        "liquidity_reserve": 30.0,
    }
    result = select_trades(holdings, target_weights, total, None, _make_policy())

    assert result.gated_trades == [], (
        f"Expected no trades when weights already match, got {len(result.gated_trades)}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 5 — Minimum trade size suppresses micro-trades
# ──────────────────────────────────────────────────────────────────────────────

def test_minimum_trade_size_suppresses_tiny_rebalancing():
    """A required change smaller than minimum_trade_size_gbp produces no trades."""
    total = 20_000.0
    holdings = _make_holdings(
        ("GB0001234567", "TN25", "gilt_conventional", 14_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 6_000.0, "liquidity_reserve"),
    )
    # Target: £20 away from current (14000 → 13980, so 69.9% gilts vs 70% current)
    target_weights = {
        "long_duration_nominal_gilts": 69.9,
        "liquidity_reserve": 30.1,
    }
    result = select_trades(
        holdings, target_weights, total, None, _make_policy(min_trade_size_gbp=500.0)
    )

    assert result.gated_trades == [], (
        f"Expected no trades for sub-threshold change, got {len(result.gated_trades)}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 6 — Consolidation: the core business rule
# ──────────────────────────────────────────────────────────────────────────────

def test_consolidation_produces_few_large_sells_not_many_small_ones():
    """The key regression test.

    Six equal gilt holdings, total £21,000.  LP says reduce by £4,200 (20%).

    Old behaviour: 6 sells of £700 each — all blocked by the friction gate.
    New behaviour: 1–2 sells totalling ≈£4,200 — each large enough to be viable.
    """
    total = 30_000.0
    holdings = _make_holdings(
        ("GB0001111111", "T26", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0002222222", "T30", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0003333333", "T34", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0004444444", "T38", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0005555555", "T41", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0006666666", "T45", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 9_000.0, "liquidity_reserve"),
    )
    # Target: reduce long gilts from 70% to 56% (−£4,200), grow MMF from 30% to 44%
    target_weights = {
        "long_duration_nominal_gilts": 56.0,
        "liquidity_reserve": 44.0,
    }
    result = select_trades(holdings, target_weights, total, None, _make_policy())

    sell_trades = [gt for gt in result.gated_trades if gt.trade.delta_value_gbp < 0]
    assert len(sell_trades) <= 2, (
        f"Expected ≤2 sell trades (consolidation), got {len(sell_trades)}: "
        f"{[round(gt.trade.delta_value_gbp, 0) for gt in sell_trades]}"
    )
    # Each individual sell must be a meaningful trade (not a micro-trade)
    for gt in sell_trades:
        assert abs(gt.trade.delta_value_gbp) >= 500.0, (
            f"Sub-threshold sell trade generated: £{gt.trade.delta_value_gbp:.0f}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 7 — All gated_trades have gate_outcome "green"
# ──────────────────────────────────────────────────────────────────────────────

def test_all_mip_trades_are_friction_viable():
    """Every trade in gated_trades must have gate_outcome='green' (MIP guarantees viability)."""
    total = 30_000.0
    holdings = _make_holdings(
        ("GB0001111111", "T26", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0002222222", "T30", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0003333333", "T34", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0004444444", "T38", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0005555555", "T41", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB0006666666", "T45", "gilt_conventional", 3_500.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 9_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 56.0,
        "liquidity_reserve": 44.0,
    }
    result = select_trades(holdings, target_weights, total, None, _make_policy())

    for gt in result.gated_trades:
        assert gt.gate_outcome == "green", (
            f"Trade {gt.trade.isin} has gate_outcome='{gt.gate_outcome}', expected 'green'"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 8 — Equity buys are approved (not unconditionally blocked)
# ──────────────────────────────────────────────────────────────────────────────

def test_equity_buy_is_approved_when_bucket_underweight():
    """Equity buy trades must receive gate_outcome='green', not be unconditionally blocked.

    Old behaviour: equity buys always blocked (yield_improvement_bps is None for equities).
    New behaviour: equity buys evaluated on weight-deviation merit.
    """
    total = 50_000.0
    holdings = _make_holdings(
        # Equities: 30% (underweight; target is 40%)
        ("GB00B3FBWWG1", "VWRL", "etf", 7_500.0, "listed_risk_assets"),
        ("GB00B0CNHX13", "CTY",  "investment_trust", 7_500.0, "listed_risk_assets"),
        # Long gilts: 50%
        ("GB0001111111", "T30",  "gilt_conventional", 25_000.0, "long_duration_nominal_gilts"),
        # MMF: 20%
        ("GB9999999999", "CSBF", "mmf", 10_000.0, "liquidity_reserve"),
    )
    # Move 10% from long_gilts to listed_risk_assets
    target_weights = {
        "listed_risk_assets": 40.0,
        "long_duration_nominal_gilts": 40.0,
        "liquidity_reserve": 20.0,
    }
    result = select_trades(holdings, target_weights, total, None, _make_policy())

    equity_buys = [
        gt for gt in result.gated_trades
        if gt.trade.bucket_id == "listed_risk_assets" and gt.trade.delta_value_gbp > 0
    ]
    assert len(equity_buys) >= 1, (
        "Expected at least one equity buy trade to be generated"
    )
    for gt in equity_buys:
        assert gt.gate_outcome == "green", (
            f"Equity buy {gt.trade.isin} has gate_outcome='{gt.gate_outcome}', expected 'green'"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 9 — Empty gilt candidates handled gracefully
# ──────────────────────────────────────────────────────────────────────────────

def test_none_gilt_candidates_does_not_crash():
    """Passing gilt_candidates_df=None must not raise; warnings list may be empty."""
    holdings = _make_holdings(
        ("GB0001234567", "TN25", "gilt_conventional", 10_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 5_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 60.0,
        "liquidity_reserve": 40.0,
    }
    # Must not raise
    result = select_trades(holdings, target_weights, 15_000.0, None, _make_policy())
    assert result.solver_status in ("optimal", "infeasible", "error")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for new-position tests
# ──────────────────────────────────────────────────────────────────────────────

def _make_candidates(*rows: tuple) -> pd.DataFrame:
    """Build a minimal gilt candidates DataFrame.

    Each row: (isin, tidm, asset_type, bucket_id, clean_price_gbp, gry_pct)
    """
    return pd.DataFrame(
        [
            {
                "isin": r[0],
                "tidm": r[1],
                "asset_type": r[2],
                "bucket_id": r[3],
                "clean_price_gbp": float(r[4]),
                "gry_pct": float(r[5]),
            }
            for r in rows
        ]
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 10 — New position in empty IL bucket (tracer bullet)
# ──────────────────────────────────────────────────────────────────────────────

def test_new_position_opened_when_bucket_empty():
    """MIP opens a new-position trade for a candidate gilt when the target bucket is empty.

    Scenario:
      Holdings: T26 conventional gilt (£30k, long_duration) + MMF (£20k). Total £50k.
      LP target: long_duration=40% (sell £10k), index_linked=20% (buy £10k), liquidity=40%.
      Candidate: one IL gilt in index_linked bucket.

    Expected: gated_trades contains a new-position buy for the IL gilt candidate.
    Cash flow: sell £10k T26 → buy £10k TLIG; MMF unchanged.
    """
    total = 50_000.0
    holdings = _make_holdings(
        ("GB0001234567", "T26", "gilt_conventional", 30_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 20_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 40.0,   # £20k — sell £10k from T26
        "index_linked_gilts": 20.0,            # £10k — empty bucket, use candidate
        "liquidity_reserve": 40.0,             # £20k — unchanged
    }
    candidates = _make_candidates(
        ("GB_IL_001", "TLIG", "gilt_index_linked", "index_linked_gilts", 95.0, 0.02),
    )

    result = select_trades(holdings, target_weights, total, candidates, _make_policy())

    new_pos = [
        gt for gt in result.gated_trades
        if gt.trade.is_new_position and gt.trade.isin == "GB_IL_001"
    ]
    assert len(new_pos) >= 1, (
        f"Expected a new-position trade for GB_IL_001; solver={result.solver_status}; "
        f"warnings={result.warnings}; trades="
        f"{[(gt.trade.isin, gt.trade.is_new_position, gt.trade.delta_value_gbp) for gt in result.gated_trades]}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 11 — New position for conventional gilt when no gilts are held
# ──────────────────────────────────────────────────────────────────────────────

def test_new_conventional_gilt_position_when_no_gilts_held():
    """MIP opens a conventional gilt position when no gilts are currently held.

    Scenario:
      Holdings: VWRL equity (£20k, listed_risk_assets) + MMF (£20k). Total £40k.
      LP target: long_duration=20% (£8k, empty bucket, within 25% concentration cap),
                 equities=50% (£20k, unchanged), mmf=30% (£12k, sell £8k).
      Candidate: T28 conventional gilt in long_duration bucket.

    Expected: new-position trade for T28 with is_new_position=True.
    Cash flow: sell £8k MMF → buy £8k T28; VWRL unchanged.
    """
    total = 40_000.0
    holdings = _make_holdings(
        ("GB00B3FBWWG1", "VWRL", "etf", 20_000.0, "listed_risk_assets"),
        ("GB9999999999", "CSBF", "mmf",  20_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 20.0,   # £8k — empty bucket, within 25% cap
        "listed_risk_assets": 50.0,            # £20k — unchanged
        "liquidity_reserve": 30.0,             # £12k — MMF absorbs via cash balance
    }
    candidates = _make_candidates(
        ("GB_CONV_001", "T28", "gilt_conventional", "long_duration_nominal_gilts", 98.0, 0.04),
    )

    result = select_trades(holdings, target_weights, total, candidates, _make_policy())

    new_pos = [
        gt for gt in result.gated_trades
        if gt.trade.is_new_position and gt.trade.isin == "GB_CONV_001"
    ]
    assert len(new_pos) >= 1, (
        f"Expected a new-position trade for GB_CONV_001; solver={result.solver_status}; "
        f"warnings={result.warnings}; trades="
        f"{[(gt.trade.isin, gt.trade.is_new_position, gt.trade.delta_value_gbp) for gt in result.gated_trades]}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Cycle 12 — Cash balance preserved when a new position is added
# ──────────────────────────────────────────────────────────────────────────────

def test_cash_balance_preserved_with_new_position():
    """Sum of proposed_value_gbp must equal total portfolio within £1 when a new position is created.

    Uses the same IL-gilt empty-bucket scenario as the tracer bullet.
    The new-position row must appear in proposed_state_df so that the total is correct.
    """
    total = 50_000.0
    holdings = _make_holdings(
        ("GB0001234567", "T26", "gilt_conventional", 30_000.0, "long_duration_nominal_gilts"),
        ("GB9999999999", "CSBF", "mmf", 20_000.0, "liquidity_reserve"),
    )
    target_weights = {
        "long_duration_nominal_gilts": 40.0,   # £20k — sell £10k
        "index_linked_gilts": 20.0,            # £10k — new IL position
        "liquidity_reserve": 40.0,             # £20k — unchanged
    }
    candidates = _make_candidates(
        ("GB_IL_001", "TLIG", "gilt_index_linked", "index_linked_gilts", 95.0, 0.02),
    )

    result = select_trades(holdings, target_weights, total, candidates, _make_policy())

    proposed_total = result.proposed_state_df["proposed_value_gbp"].sum()
    assert abs(proposed_total - total) < 1.0, (
        f"Cash not balanced after new-position trade: proposed={proposed_total:.2f}, expected={total:.2f}; "
        f"rows={result.proposed_state_df[['isin','proposed_value_gbp']].to_dict('records')}"
    )
