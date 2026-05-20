from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from investment_optimiser.holdings_translator import (
    HoldingsTranslationResult,
    translate_bucket_targets_to_holdings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _holding(symbol: str, bucket_id: str, market_value_gbp: float, isin: str | None = None) -> dict:
    return {
        "symbol": symbol,
        "instrument_name": f"{symbol} name",
        "asset_type": "equity",
        "market_value_gbp": market_value_gbp,
        "bucket_id": bucket_id,
        "isin": isin,
    }


def _gilt_holding(symbol: str, bucket_id: str, market_value_gbp: float, isin: str) -> dict:
    return {
        "symbol": symbol,
        "instrument_name": f"{symbol} name",
        "asset_type": "gilt_conventional",
        "market_value_gbp": market_value_gbp,
        "bucket_id": bucket_id,
        "isin": isin,
    }


def _candidate(isin: str, maturity_date: str, gry_pct: float) -> dict:
    return {
        "isin": isin,
        "instrument_name": f"Gilt {isin}",
        "maturity_date": maturity_date,
        "coupon_pct": 1.5,
        "clean_price_gbp": 95.0,
        "gry_pct": gry_pct,
        "modified_duration_years": 3.0,
    }


REFERENCE_DATE = date(2026, 5, 20)


# ---------------------------------------------------------------------------
# Tracer bullet — proportional scaling within a bucket
# ---------------------------------------------------------------------------

def test_proportional_scaling_preserves_relative_weights():
    # Two equities in the same bucket. Portfolio = £100k, current bucket = 40%,
    # target = 50%. Both holdings should scale up proportionally.
    holdings = pd.DataFrame([
        _holding("VUAG", "listed_risk_assets", 25_000.0),
        _holding("VWRP", "listed_risk_assets", 15_000.0),
    ])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"listed_risk_assets": 50.0},
        enriched_holdings_df=holdings,
        total_portfolio_value_gbp=100_000.0,
        reference_date=REFERENCE_DATE,
    )

    df = result.target_df
    vuag = df[df["symbol"] == "VUAG"].iloc[0]
    vwrp = df[df["symbol"] == "VWRP"].iloc[0]

    # VUAG was 25k/40k of the bucket → should be 25/40 * 50k = 31 250
    assert abs(vuag["target_value_gbp"] - 31_250.0) < 0.01
    assert abs(vwrp["target_value_gbp"] - 18_750.0) < 0.01


def test_full_exit_when_target_zero():
    holdings = pd.DataFrame([
        _holding("VUAG", "listed_risk_assets", 20_000.0),
        _holding("SMT", "listed_risk_assets", 10_000.0),
    ])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"listed_risk_assets": 0.0},
        enriched_holdings_df=holdings,
        total_portfolio_value_gbp=100_000.0,
        reference_date=REFERENCE_DATE,
    )
    df = result.target_df
    assert (df["target_value_gbp"] == 0.0).all()
    assert (df["delta_value_gbp"] < 0).all()


def test_empty_short_gilt_bucket_picks_candidate_within_five_years():
    # Reference date 2026-05-20. Short = maturity ≤ 5y → before 2031-05-20.
    # Two candidates: one short (2028), one long (2040). Should pick the short one.
    candidates = pd.DataFrame([
        _candidate("GB00BM8Z2V91", "2028-03-07", gry_pct=4.2),  # short
        _candidate("GB00BNNGP775", "2040-10-22", gry_pct=4.8),  # long
    ])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"short_duration_nominal_gilts": 15.0},
        enriched_holdings_df=pd.DataFrame(columns=["symbol", "instrument_name", "asset_type", "market_value_gbp", "bucket_id", "isin"]),
        total_portfolio_value_gbp=100_000.0,
        gilt_candidates_df=candidates,
        reference_date=REFERENCE_DATE,
    )
    df = result.target_df
    assert len(df) == 1
    assert df.iloc[0]["isin"] == "GB00BM8Z2V91"
    assert df.iloc[0]["is_new_position"] == True
    assert abs(df.iloc[0]["target_value_gbp"] - 15_000.0) < 0.01
    assert len(result.warnings) == 1


def test_empty_long_gilt_bucket_picks_highest_gry_candidate():
    # Two long candidates; highest GRY should be selected.
    candidates = pd.DataFrame([
        _candidate("GB00BNNGP775", "2040-10-22", gry_pct=4.5),
        _candidate("GB00BFX0ZL58", "2052-07-31", gry_pct=4.9),  # higher GRY
    ])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"long_duration_nominal_gilts": 20.0},
        enriched_holdings_df=pd.DataFrame(columns=["symbol", "instrument_name", "asset_type", "market_value_gbp", "bucket_id", "isin"]),
        total_portfolio_value_gbp=100_000.0,
        gilt_candidates_df=candidates,
        reference_date=REFERENCE_DATE,
    )
    df = result.target_df
    assert df.iloc[0]["isin"] == "GB00BFX0ZL58"


def test_empty_non_gilt_bucket_emits_warning_and_sentinel():
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"listed_risk_assets": 30.0},
        enriched_holdings_df=pd.DataFrame(columns=["symbol", "instrument_name", "asset_type", "market_value_gbp", "bucket_id", "isin"]),
        total_portfolio_value_gbp=100_000.0,
        reference_date=REFERENCE_DATE,
    )
    df = result.target_df
    assert len(df) == 1
    assert df.iloc[0]["symbol"] is None
    assert df.iloc[0]["isin"] is None
    assert abs(df.iloc[0]["target_value_gbp"] - 30_000.0) < 0.01
    assert len(result.warnings) == 1
    assert "unfulfilled" in result.warnings[0]


def test_bucket_absent_from_targets_passes_through_unchanged():
    # "diversifiers_and_manual" has no entry in bucket_target_weights → target = current
    holdings = pd.DataFrame([
        _holding("LAND", "diversifiers_and_manual", 5_000.0),
    ])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"listed_risk_assets": 40.0},
        enriched_holdings_df=holdings,
        total_portfolio_value_gbp=100_000.0,
        reference_date=REFERENCE_DATE,
    )
    df = result.target_df
    land = df[df["symbol"] == "LAND"].iloc[0]
    assert abs(land["target_value_gbp"] - 5_000.0) < 0.01
    assert abs(land["delta_value_gbp"]) < 0.01


def test_output_dataframe_has_required_columns():
    holdings = pd.DataFrame([_holding("VUAG", "listed_risk_assets", 10_000.0)])
    result = translate_bucket_targets_to_holdings(
        bucket_target_weights={"listed_risk_assets": 10.0},
        enriched_holdings_df=holdings,
        total_portfolio_value_gbp=100_000.0,
        reference_date=REFERENCE_DATE,
    )
    required = {
        "symbol", "isin", "bucket_id", "is_new_position",
        "current_value_gbp", "current_weight_pct",
        "target_value_gbp", "target_weight_pct", "delta_value_gbp",
    }
    assert required.issubset(set(result.target_df.columns))
    assert set(result.bucket_summary.columns) == {"bucket_id", "current_pct", "target_pct", "delta_pct"}
