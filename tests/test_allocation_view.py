import pandas as pd
import pytest

from investment_optimiser.allocation_view import build_allocation_table

BUCKET_LABELS = {
    "liquidity_reserve": "Liquidity reserve",
    "short_duration_nominal_gilts": "Short-duration nominal gilts",
    "long_duration_nominal_gilts": "Long-duration nominal gilts",
    "index_linked_gilts": "Index-linked gilts",
    "listed_risk_assets": "Equities",
    "diversifiers_and_manual": "Real Assets, Diversifiers & Other",
}

BASELINE = {
    "liquidity_reserve": 10.0,
    "short_duration_nominal_gilts": 15.0,
    "long_duration_nominal_gilts": 20.0,
    "index_linked_gilts": 10.0,
    "listed_risk_assets": 35.0,
    "diversifiers_and_manual": 10.0,
}


def _holding(**kwargs):
    defaults = {
        "symbol": "X",
        "instrument_name": "",
        "asset_type": "equity",
        "market_value_gbp": 1000.0,
        "maturity_years": None,
    }
    return {**defaults, **kwargs}


# --- Tracer bullet ---


def test_all_six_buckets_always_present():
    holdings = pd.DataFrame([_holding(asset_type="equity", market_value_gbp=1000.0)])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    assert set(result["bucket_id"]) == set(BASELINE.keys())
    assert len(result) == 6


def test_current_pct_computed_from_market_value():
    # 1000 equity out of 2000 total → 50% in listed_risk_assets
    holdings = pd.DataFrame([
        _holding(symbol="A", asset_type="equity", market_value_gbp=1000.0),
        _holding(symbol="B", asset_type="mmf", market_value_gbp=1000.0),
    ])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    equity_row = result[result["bucket_id"] == "listed_risk_assets"].iloc[0]
    assert abs(equity_row["current_pct"] - 50.0) < 0.01


def test_drift_is_current_minus_baseline():
    holdings = pd.DataFrame([_holding(asset_type="equity", market_value_gbp=1000.0)])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    equity_row = result[result["bucket_id"] == "listed_risk_assets"].iloc[0]
    assert abs(equity_row["drift_pct"] - (equity_row["current_pct"] - equity_row["baseline_pct"])) < 0.001


def test_empty_bucket_has_zero_current_pct():
    holdings = pd.DataFrame([_holding(asset_type="equity", market_value_gbp=1000.0)])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    empty_row = result[result["bucket_id"] == "liquidity_reserve"].iloc[0]
    assert empty_row["current_pct"] == 0.0


def test_empty_holdings_gives_all_zero_current():
    result = build_allocation_table(pd.DataFrame(), BASELINE, BUCKET_LABELS)
    assert (result["current_pct"] == 0.0).all()
    assert len(result) == 6


# --- Uncertain flag ---


def test_certain_classification_not_flagged():
    # plain equity → asset_type_fallback → certain
    holdings = pd.DataFrame([_holding(asset_type="equity", market_value_gbp=500.0)])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    equity_row = result[result["bucket_id"] == "listed_risk_assets"].iloc[0]
    assert equity_row["uncertain"] is False or equity_row["uncertain"] == False


def test_keyword_classification_flagged_as_uncertain():
    # equity fund → name_keywords → uncertain
    holdings = pd.DataFrame([
        _holding(asset_type="fund", instrument_name="Vanguard Global Equity Fund", market_value_gbp=500.0)
    ])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    equity_row = result[result["bucket_id"] == "listed_risk_assets"].iloc[0]
    assert equity_row["uncertain"] == True


def test_bucket_labels_mapped_correctly():
    holdings = pd.DataFrame([_holding(asset_type="equity", market_value_gbp=1000.0)])
    result = build_allocation_table(holdings, BASELINE, BUCKET_LABELS)
    equity_row = result[result["bucket_id"] == "listed_risk_assets"].iloc[0]
    assert equity_row["label"] == "Equities"
