from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from investment_optimiser.gilt_analytics import clean_price_from_gry, compute_gry
from investment_optimiser.scenario_engine import run_scenarios

_SETTLEMENT = date(2026, 5, 21)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gilt_ref_df(
    *,
    tidm: str = "TR27",
    isin: str = "GB00TEST0001",
    coupon_pct: float = 4.25,
    maturity_date: str = "2027-03-07",
    gry_pct: float = 0.04,
    modified_duration_years: float = 1.5,
) -> pd.DataFrame:
    return pd.DataFrame([{
        "tidm": tidm,
        "isin": isin,
        "coupon_pct": coupon_pct,
        "maturity_date": maturity_date,
        "gry_pct": gry_pct,
        "modified_duration_years": modified_duration_years,
        "clean_price_gbp": 100.0,
    }])


def _holdings_row(
    *,
    symbol: str = "TR27",
    name: str = "4¼% Treasury Gilt 2027",
    asset_type: str = "gilt_conventional",
    qty: float = 3447.63,
    clean_price_gbp: float = 99.64,
    market_value_gbp: float = 3435.22,
    maturity_date: str = "2027-03-07",
    bucket_id: str = "short_duration_nominal_gilts",
) -> dict:
    return dict(
        symbol=symbol,
        name=name,
        asset_type=asset_type,
        qty=qty,
        clean_price_gbp=clean_price_gbp,
        market_value_gbp=market_value_gbp,
        maturity_date=maturity_date,
        bucket_id=bucket_id,
    )


def _minimal_policy(scenarios: list[dict] | None = None) -> dict:
    if scenarios is None:
        scenarios = [
            {
                "id": "rates_up_parallel",
                "label": "Rates up parallel",
                "base_shocks": {
                    "nominal_curve_parallel_bps": 100.0,
                    "nominal_curve_2s10s_steepener_bps": 0.0,
                    "real_yield_parallel_bps": 75.0,
                    "listed_risk_assets_pct": -5.0,
                    "diversifiers_and_manual_pct": -4.0,
                    "cash_mmf_pct": 0.0,
                },
            }
        ]
    return {"named_scenarios": scenarios, "bucket_labels": {}}


# ---------------------------------------------------------------------------
# clean_price_from_gry — roundtrip tests
# ---------------------------------------------------------------------------

class TestCleanPriceFromGry:
    def test_roundtrip_typical_gilt(self):
        # 4.25% coupon, 2027 maturity — compute GRY from price, recover price
        maturity = date(2027, 3, 7)
        original_price = 99.64
        gry, _ = compute_gry(original_price, 4.25, maturity, _SETTLEMENT)
        assert gry is not None
        recovered = clean_price_from_gry(gry, 4.25, maturity, _SETTLEMENT)
        assert recovered is not None
        assert abs(recovered - original_price) < 0.001

    def test_roundtrip_long_dated_gilt(self):
        maturity = date(2035, 3, 7)
        original_price = 95.84
        gry, _ = compute_gry(original_price, 4.5, maturity, _SETTLEMENT)
        assert gry is not None
        recovered = clean_price_from_gry(gry, 4.5, maturity, _SETTLEMENT)
        assert recovered is not None
        assert abs(recovered - original_price) < 0.001

    def test_higher_yield_gives_lower_price(self):
        maturity = date(2034, 1, 31)
        gry_base = 0.045
        gry_shocked = 0.055
        price_base = clean_price_from_gry(gry_base, 4.625, maturity, _SETTLEMENT)
        price_shocked = clean_price_from_gry(gry_shocked, 4.625, maturity, _SETTLEMENT)
        assert price_base is not None and price_shocked is not None
        assert price_shocked < price_base

    def test_maturity_in_past_returns_none(self):
        maturity = date(2020, 1, 31)
        result = clean_price_from_gry(0.04, 2.0, maturity, _SETTLEMENT)
        assert result is None


# ---------------------------------------------------------------------------
# run_scenarios — output shape
# ---------------------------------------------------------------------------

class TestRunScenariosShape:
    def test_returns_list_of_dicts(self):
        holdings = pd.DataFrame([_holdings_row()])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_canonical_fields_present(self):
        holdings = pd.DataFrame([_holdings_row()])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        required = {
            "portfolio_state", "scenario_name", "holding_id", "holding_name",
            "asset_type", "bucket_name", "current_value_gbp", "scenario_value_gbp",
            "pnl_gbp", "model_status", "notes",
        }
        for rec in results:
            assert required.issubset(rec.keys()), f"Missing fields: {required - rec.keys()}"

    def test_pnl_equals_scenario_minus_current(self):
        holdings = pd.DataFrame([_holdings_row()])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        for rec in results:
            assert abs(rec["pnl_gbp"] - (rec["scenario_value_gbp"] - rec["current_value_gbp"])) < 1e-6

    def test_two_portfolio_states_when_executable_provided(self):
        holdings = pd.DataFrame([_holdings_row()])
        executable = pd.DataFrame([_holdings_row(market_value_gbp=3500.0)])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, executable, policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        states = {r["portfolio_state"] for r in results}
        assert "current" in states
        assert "executable_recommended" in states

    def test_only_current_state_when_executable_empty(self):
        holdings = pd.DataFrame([_holdings_row()])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        states = {r["portfolio_state"] for r in results}
        assert states == {"current"}

    def test_one_record_per_holding_per_scenario_per_state(self):
        holdings = pd.DataFrame([
            _holdings_row(symbol="TR27", maturity_date="2027-03-07"),
            _holdings_row(symbol="ADM", name="Admiral", asset_type="equity",
                          maturity_date=None, bucket_id="equities"),
        ])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        # 2 holdings × 1 scenario × 1 state = 2 records
        assert len(results) == 2


# ---------------------------------------------------------------------------
# run_scenarios — repricing correctness
# ---------------------------------------------------------------------------

class TestGiltRepricing:
    def test_rates_up_reduces_gilt_value(self):
        holdings = pd.DataFrame([_holdings_row(
            qty=3447.63, clean_price_gbp=99.64, market_value_gbp=3435.22,
            maturity_date="2027-03-07",
        )])
        gilt_ref = _gilt_ref_df(gry_pct=0.04, maturity_date="2027-03-07")
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "exact"
        assert rec["scenario_value_gbp"] < rec["current_value_gbp"]
        assert rec["pnl_gbp"] < 0

    def test_rates_down_increases_gilt_value(self):
        holdings = pd.DataFrame([_holdings_row(maturity_date="2034-01-31")])
        gilt_ref = _gilt_ref_df(gry_pct=0.045, maturity_date="2034-01-31")
        policy = _minimal_policy(scenarios=[{
            "id": "rates_down_parallel",
            "label": "Rates down parallel",
            "base_shocks": {
                "nominal_curve_parallel_bps": -100.0,
                "nominal_curve_2s10s_steepener_bps": 0.0,
                "real_yield_parallel_bps": -75.0,
                "listed_risk_assets_pct": 5.0,
                "diversifiers_and_manual_pct": 3.0,
                "cash_mmf_pct": 0.0,
            },
        }])
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["scenario_value_gbp"] > rec["current_value_gbp"]
        assert rec["pnl_gbp"] > 0

    def test_gilt_not_in_ref_becomes_unmodelled(self):
        holdings = pd.DataFrame([_holdings_row(symbol="UNKNOWN", maturity_date="2028-01-01")])
        gilt_ref = _gilt_ref_df(tidm="TR27", maturity_date="2027-03-07")
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "unmodelled_held_flat"
        assert rec["scenario_value_gbp"] == rec["current_value_gbp"]

    def test_magnitude_scales_shock(self):
        holdings = pd.DataFrame([_holdings_row(maturity_date="2034-01-31")])
        gilt_ref = _gilt_ref_df(gry_pct=0.04, maturity_date="2034-01-31")
        policy = _minimal_policy()
        results_1x = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                   scenario_magnitude=1.0, reference_date=_SETTLEMENT)
        results_2x = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                   scenario_magnitude=2.0, reference_date=_SETTLEMENT)
        pnl_1x = results_1x[0]["pnl_gbp"]
        pnl_2x = results_2x[0]["pnl_gbp"]
        # 2× magnitude should produce roughly 2× P&L (not exact due to convexity)
        assert pnl_2x < pnl_1x  # both negative; 2x is more negative
        assert abs(pnl_2x) > abs(pnl_1x)


class TestNonGiltRepricing:
    def test_equity_drawdown_applies_price_shock(self):
        holdings = pd.DataFrame([_holdings_row(
            symbol="ADM", name="Admiral", asset_type="equity",
            qty=110, clean_price_gbp=32.72, market_value_gbp=3599.20,
            maturity_date=None, bucket_id="equities",
        )])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy(scenarios=[{
            "id": "equity_drawdown",
            "label": "Equity drawdown",
            "base_shocks": {
                "nominal_curve_parallel_bps": -50.0,
                "nominal_curve_2s10s_steepener_bps": 0.0,
                "real_yield_parallel_bps": -25.0,
                "listed_risk_assets_pct": -20.0,
                "diversifiers_and_manual_pct": -12.0,
                "cash_mmf_pct": 0.0,
            },
        }])
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "exact"
        expected = 3599.20 * (1 - 0.20)
        assert abs(rec["scenario_value_gbp"] - expected) < 0.01

    def test_etf_uses_listed_risk_shock(self):
        holdings = pd.DataFrame([_holdings_row(
            symbol="VWRL", name="Vanguard FTSE All-World", asset_type="etf",
            qty=50, clean_price_gbp=100.0, market_value_gbp=5000.0,
            maturity_date=None, bucket_id="equities",
        )])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy(scenarios=[{
            "id": "equity_drawdown",
            "label": "Equity drawdown",
            "base_shocks": {
                "nominal_curve_parallel_bps": -50.0,
                "nominal_curve_2s10s_steepener_bps": 0.0,
                "real_yield_parallel_bps": -25.0,
                "listed_risk_assets_pct": -20.0,
                "diversifiers_and_manual_pct": -12.0,
                "cash_mmf_pct": 0.0,
            },
        }])
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "exact"
        assert abs(rec["scenario_value_gbp"] - 4000.0) < 0.01

    def test_mmf_is_capital_flat(self):
        holdings = pd.DataFrame([_holdings_row(
            symbol="B8XYYQ8", name="Royal London MMF", asset_type="mmf",
            qty=32710.57, clean_price_gbp=1.20905, market_value_gbp=39548.71,
            maturity_date=None, bucket_id="liquidity_reserve",
        )])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "held_flat"
        assert rec["scenario_value_gbp"] == rec["current_value_gbp"]
        assert rec["pnl_gbp"] == 0.0

    def test_il_gilt_is_unmodelled_held_flat(self):
        holdings = pd.DataFrame([_holdings_row(
            symbol="TG33", name="0.875% Index-linked 2033",
            asset_type="gilt_index_linked",
            maturity_date="2033-07-31",
        )])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        rec = results[0]
        assert rec["model_status"] == "unmodelled_held_flat"
        assert rec["scenario_value_gbp"] == rec["current_value_gbp"]


# ---------------------------------------------------------------------------
# run_scenarios — coverage disclosure
# ---------------------------------------------------------------------------

class TestCoverageDisclosure:
    def test_model_status_field_present_on_every_record(self):
        holdings = pd.DataFrame([
            _holdings_row(symbol="TR27", maturity_date="2027-03-07"),
            _holdings_row(symbol="ADM", asset_type="equity", maturity_date=None,
                          bucket_id="equities"),
            _holdings_row(symbol="B8XYYQ8", asset_type="mmf", maturity_date=None,
                          bucket_id="liquidity_reserve"),
            _holdings_row(symbol="TG33", asset_type="gilt_index_linked",
                          maturity_date="2033-07-31"),
        ])
        gilt_ref = _gilt_ref_df()
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        valid_statuses = {"exact", "held_flat", "unmodelled_held_flat"}
        for rec in results:
            assert rec["model_status"] in valid_statuses

    def test_all_four_asset_types_produce_correct_status(self):
        holdings = pd.DataFrame([
            _holdings_row(symbol="TR27", asset_type="gilt_conventional",
                          maturity_date="2027-03-07"),
            _holdings_row(symbol="ADM", asset_type="equity", maturity_date=None,
                          bucket_id="equities"),
            _holdings_row(symbol="B8XYYQ8", asset_type="mmf", maturity_date=None,
                          bucket_id="liquidity_reserve"),
            _holdings_row(symbol="TG33", asset_type="gilt_index_linked",
                          maturity_date="2033-07-31"),
        ])
        gilt_ref = _gilt_ref_df(tidm="TR27", maturity_date="2027-03-07")
        policy = _minimal_policy()
        results = run_scenarios(holdings, pd.DataFrame(), policy, gilt_ref,
                                reference_date=_SETTLEMENT)
        status_by_symbol = {r["holding_id"]: r["model_status"] for r in results}
        assert status_by_symbol["TR27"] == "exact"
        assert status_by_symbol["ADM"] == "exact"
        assert status_by_symbol["B8XYYQ8"] == "held_flat"
        assert status_by_symbol["TG33"] == "unmodelled_held_flat"

    def test_empty_holdings_returns_empty_list(self):
        results = run_scenarios(
            pd.DataFrame(), pd.DataFrame(), _minimal_policy(), _gilt_ref_df(),
            reference_date=_SETTLEMENT,
        )
        assert results == []
