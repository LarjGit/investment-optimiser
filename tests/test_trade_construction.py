from __future__ import annotations

import pandas as pd

from investment_optimiser.trade_construction import (
    TradeConstructionResult,
    construct_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(
    isin: str | None,
    symbol: str | None,
    bucket_id: str,
    asset_type: str | None,
    current_value_gbp: float,
    target_value_gbp: float,
    *,
    is_new_position: bool = False,
) -> dict:
    return {
        "isin": isin,
        "symbol": symbol,
        "bucket_id": bucket_id,
        "asset_type": asset_type,
        "is_new_position": is_new_position,
        "current_value_gbp": current_value_gbp,
        "current_weight_pct": 0.0,
        "target_value_gbp": target_value_gbp,
        "target_weight_pct": 0.0,
        "delta_value_gbp": target_value_gbp - current_value_gbp,
    }


def _df(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------------------
# Cycle 1: gilt buy rounding
# ---------------------------------------------------------------------------

def test_gilt_buy_is_rounded_toward_zero():
    # delta_value_gbp = +350, price = 95.0 per 100 nominal
    # nominal_delta = 350 / 95 * 100 = 368.42
    # rounded = math.trunc(368.42 / 100) * 100 = 300
    # executable = 300 * 95 / 100 = 285.0
    # residual = 350 - 285.0 = 65.0
    target_df = _df(
        _row("GB0001", "TN25", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0, 10_350.0),
    )
    result = construct_trades(target_df, gilt_prices={"GB0001": 95.0})

    assert isinstance(result, TradeConstructionResult)
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.isin == "GB0001"
    assert t.rounded_nominal_delta == 300
    assert abs(t.executable_delta_gbp - 285.0) < 0.01
    assert abs(t.residual_cash_gbp - 65.0) < 0.01
    assert abs(result.total_residual_cash_gbp - 65.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 2: gilt sell rounding toward zero
# ---------------------------------------------------------------------------

def test_gilt_sell_is_rounded_toward_zero():
    # delta = -350, price = 95.0
    # nominal_delta = -350 / 95 * 100 = -368.42
    # math.trunc(-368.42 / 100) * 100 = -300
    # executable = -300 * 95 / 100 = -285.0
    # residual = -350 - (-285.0) = -65.0  (cash raised is £65 less than intended)
    target_df = _df(
        _row("GB0001", "TN25", "short_duration_nominal_gilts", "gilt_conventional", 10_350.0, 10_000.0),
    )
    result = construct_trades(target_df, gilt_prices={"GB0001": 95.0})

    t = result.trades[0]
    assert t.rounded_nominal_delta == -300
    assert abs(t.executable_delta_gbp - (-285.0)) < 0.01
    assert abs(t.residual_cash_gbp - (-65.0)) < 0.01
    assert abs(result.total_residual_cash_gbp - (-65.0)) < 0.01


# ---------------------------------------------------------------------------
# Cycle 3: non-gilt passes through unchanged
# ---------------------------------------------------------------------------

def test_non_gilt_passes_through_with_no_rounding():
    target_df = _df(
        _row("GB00B3X7QG63", "VUAG", "listed_risk_assets", "equity", 20_000.0, 20_500.0),
    )
    result = construct_trades(target_df, gilt_prices={})

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.clean_price_gbp is None
    assert t.nominal_delta is None
    assert t.rounded_nominal_delta is None
    assert t.executable_delta_gbp is None
    assert t.residual_cash_gbp is None
    assert result.total_residual_cash_gbp == 0.0


# ---------------------------------------------------------------------------
# Cycle 4: sentinel row (isin=None) excluded from trades with warning
# ---------------------------------------------------------------------------

def test_sentinel_row_excluded_with_warning():
    target_df = _df(
        _row(None, None, "index_linked_gilts", None, 0.0, 5_000.0),
    )
    result = construct_trades(target_df, gilt_prices={})

    assert result.trades == []
    assert len(result.warnings) == 1
    assert "isin=None" in result.warnings[0]


# ---------------------------------------------------------------------------
# Cycle 5: gilt with no price → warning, treated as non-gilt (no rounding)
# ---------------------------------------------------------------------------

def test_gilt_with_missing_price_emits_warning_and_skips_rounding():
    target_df = _df(
        _row("GB9999", "TN30", "long_duration_nominal_gilts", "gilt_conventional", 5_000.0, 5_500.0),
    )
    result = construct_trades(target_df, gilt_prices={})  # price not supplied

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.rounded_nominal_delta is None
    assert t.residual_cash_gbp is None
    assert result.total_residual_cash_gbp == 0.0
    assert len(result.warnings) == 1
    assert "GB9999" in result.warnings[0]


# ---------------------------------------------------------------------------
# Cycle 6: residual cash absorbed into existing liquidity_reserve row
# ---------------------------------------------------------------------------

def test_residual_added_to_existing_liquidity_reserve():
    # Gilt buy: residual = 65.0. Liquidity reserve currently holds £5,000.
    # Proposed liquidity_reserve value should be 5,000 + 65 = 5,065.
    target_df = _df(
        _row("GB0001", "TN25", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0, 10_350.0),
        _row("GB00MMF", "MMF", "liquidity_reserve", "mmf", 5_000.0, 5_000.0),
    )
    result = construct_trades(target_df, gilt_prices={"GB0001": 95.0})

    prop = result.proposed_state_df
    liq_row = prop[prop["bucket_id"] == "liquidity_reserve"].iloc[0]
    assert abs(liq_row["proposed_value_gbp"] - 5_065.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 7: no liquidity_reserve row → synthetic row created for residual
# ---------------------------------------------------------------------------

def test_residual_creates_liquidity_reserve_row_when_absent():
    target_df = _df(
        _row("GB0001", "TN25", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0, 10_350.0),
    )
    result = construct_trades(target_df, gilt_prices={"GB0001": 95.0})

    prop = result.proposed_state_df
    liq_rows = prop[prop["bucket_id"] == "liquidity_reserve"]
    assert len(liq_rows) == 1
    assert abs(liq_rows.iloc[0]["proposed_value_gbp"] - 65.0) < 0.01


# ---------------------------------------------------------------------------
# Cycle 8: proposed_state_df has correct values for mixed portfolio
# ---------------------------------------------------------------------------

def test_proposed_state_reflects_rounded_gilt_and_full_non_gilt():
    # Gilt: current=10000, delta=350, rounded executable=285 → proposed=10285
    # Equity: current=20000, delta=500 → proposed=20500
    # Liquidity: current=5000 + gilt residual 65 → proposed=5065
    target_df = _df(
        _row("GB0001", "TN25", "short_duration_nominal_gilts", "gilt_conventional", 10_000.0, 10_350.0),
        _row("IE0031442068", "VUAG", "listed_risk_assets", "equity", 20_000.0, 20_500.0),
        _row("GB00MMF", "CMMF", "liquidity_reserve", "mmf", 5_000.0, 5_000.0),
    )
    result = construct_trades(target_df, gilt_prices={"GB0001": 95.0})

    prop = result.proposed_state_df.set_index("isin")
    assert abs(prop.loc["GB0001", "proposed_value_gbp"] - 10_285.0) < 0.01
    assert abs(prop.loc["IE0031442068", "proposed_value_gbp"] - 20_500.0) < 0.01
    assert abs(prop.loc["GB00MMF", "proposed_value_gbp"] - 5_065.0) < 0.01
