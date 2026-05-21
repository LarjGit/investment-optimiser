from __future__ import annotations

import pandas as pd
import pytest

from investment_optimiser.scenario_comparison import (
    build_coverage_summary,
    build_scenario_comparison_df,
    compute_scenario_totals,
)

_RECORDS = [
    {
        "portfolio_state": "current",
        "scenario_name": "rates_up_parallel",
        "holding_id": "TR27",
        "holding_name": "4% Treasury 2027",
        "asset_type": "gilt_conventional",
        "bucket_name": "Short duration",
        "current_value_gbp": 10000.0,
        "scenario_value_gbp": 9800.0,
        "pnl_gbp": -200.0,
        "model_status": "exact",
        "notes": "",
    },
    {
        "portfolio_state": "executable_recommended",
        "scenario_name": "rates_up_parallel",
        "holding_id": "TR27",
        "holding_name": "4% Treasury 2027",
        "asset_type": "gilt_conventional",
        "bucket_name": "Short duration",
        "current_value_gbp": 12000.0,
        "scenario_value_gbp": 11700.0,
        "pnl_gbp": -300.0,
        "model_status": "exact",
        "notes": "",
    },
    {
        "portfolio_state": "current",
        "scenario_name": "rates_up_parallel",
        "holding_id": "ADM",
        "holding_name": "Admiral",
        "asset_type": "equity",
        "bucket_name": "Equities",
        "current_value_gbp": 5000.0,
        "scenario_value_gbp": 4750.0,
        "pnl_gbp": -250.0,
        "model_status": "exact",
        "notes": "",
    },
    {
        "portfolio_state": "current",
        "scenario_name": "equity_drawdown",
        "holding_id": "ADM",
        "holding_name": "Admiral",
        "asset_type": "equity",
        "bucket_name": "Equities",
        "current_value_gbp": 5000.0,
        "scenario_value_gbp": 4000.0,
        "pnl_gbp": -1000.0,
        "model_status": "exact",
        "notes": "",
    },
    {
        "portfolio_state": "current",
        "scenario_name": "rates_up_parallel",
        "holding_id": "B8X",
        "holding_name": "Royal London MMF",
        "asset_type": "mmf",
        "bucket_name": "Liquidity",
        "current_value_gbp": 2000.0,
        "scenario_value_gbp": 2000.0,
        "pnl_gbp": 0.0,
        "model_status": "held_flat",
        "notes": "",
    },
]


# ---------------------------------------------------------------------------
# build_scenario_comparison_df
# ---------------------------------------------------------------------------


class TestBuildScenarioComparisonDf:
    def test_returns_dataframe(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        assert isinstance(result, pd.DataFrame)

    def test_filters_to_named_scenario(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        # equity_drawdown record should not appear
        names = result["holding_name"].tolist()
        # Admiral appears in rates_up_parallel; its equity_drawdown record is excluded
        assert len(result) == 3  # TR27, Admiral, Royal London MMF

    def test_has_flattened_columns_for_both_states(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        assert "pnl_gbp_current" in result.columns
        assert "pnl_gbp_executable_recommended" in result.columns

    def test_current_pnl_correct(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        tr27 = result[result["holding_name"] == "4% Treasury 2027"].iloc[0]
        assert abs(tr27["pnl_gbp_current"] - (-200.0)) < 1e-6

    def test_executable_pnl_correct(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        tr27 = result[result["holding_name"] == "4% Treasury 2027"].iloc[0]
        assert abs(tr27["pnl_gbp_executable_recommended"] - (-300.0)) < 1e-6

    def test_missing_executable_state_fills_zero(self):
        # Admiral and MMF only appear in "current" state
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        admiral = result[result["holding_name"] == "Admiral"].iloc[0]
        assert admiral["pnl_gbp_executable_recommended"] == 0.0

    def test_no_scenario_name_column_in_output(self):
        result = build_scenario_comparison_df(_RECORDS, "rates_up_parallel")
        assert "scenario_name" not in result.columns

    def test_empty_records_returns_empty_dataframe(self):
        result = build_scenario_comparison_df([], "rates_up_parallel")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_unknown_scenario_returns_empty_dataframe(self):
        result = build_scenario_comparison_df(_RECORDS, "bear_steepener")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# compute_scenario_totals
# ---------------------------------------------------------------------------


class TestComputeScenarioTotals:
    def test_returns_dict(self):
        result = compute_scenario_totals(_RECORDS, "rates_up_parallel")
        assert isinstance(result, dict)

    def test_current_total_is_sum_of_pnl(self):
        result = compute_scenario_totals(_RECORDS, "rates_up_parallel")
        # current: -200 + -250 + 0 = -450
        assert abs(result["current"] - (-450.0)) < 1e-6

    def test_executable_total_present_when_data_exists(self):
        result = compute_scenario_totals(_RECORDS, "rates_up_parallel")
        assert "executable_recommended" in result
        assert abs(result["executable_recommended"] - (-300.0)) < 1e-6

    def test_filters_to_named_scenario(self):
        result = compute_scenario_totals(_RECORDS, "equity_drawdown")
        assert abs(result["current"] - (-1000.0)) < 1e-6
        assert "executable_recommended" not in result

    def test_empty_records_returns_empty_dict(self):
        result = compute_scenario_totals([], "rates_up_parallel")
        assert result == {}

    def test_unknown_scenario_returns_empty_dict(self):
        result = compute_scenario_totals(_RECORDS, "bear_steepener")
        assert result == {}


# ---------------------------------------------------------------------------
# build_coverage_summary
# ---------------------------------------------------------------------------


class TestBuildCoverageSummary:
    def test_returns_dataframe(self):
        result = build_coverage_summary(_RECORDS, "rates_up_parallel")
        assert isinstance(result, pd.DataFrame)

    def test_columns_present(self):
        result = build_coverage_summary(_RECORDS, "rates_up_parallel")
        assert set(result.columns) == {"portfolio_state", "model_status", "count"}

    def test_filters_to_named_scenario(self):
        result = build_coverage_summary(_RECORDS, "rates_up_parallel")
        # equity_drawdown should not appear
        assert "equity_drawdown" not in result["portfolio_state"].tolist()

    def test_counts_are_correct(self):
        result = build_coverage_summary(_RECORDS, "rates_up_parallel")
        current_exact = result[
            (result["portfolio_state"] == "current") & (result["model_status"] == "exact")
        ]["count"].iloc[0]
        # TR27 and Admiral are exact for current
        assert current_exact == 2

    def test_held_flat_counted(self):
        result = build_coverage_summary(_RECORDS, "rates_up_parallel")
        current_flat = result[
            (result["portfolio_state"] == "current") & (result["model_status"] == "held_flat")
        ]["count"].iloc[0]
        assert current_flat == 1

    def test_empty_records_returns_empty_dataframe(self):
        result = build_coverage_summary([], "rates_up_parallel")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0
