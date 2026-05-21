from __future__ import annotations

import pandas as pd


def _filter_to_scenario(records: list[dict], scenario_name: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    return df[df["scenario_name"] == scenario_name]


def build_scenario_comparison_df(records: list[dict], scenario_name: str) -> pd.DataFrame:
    df = _filter_to_scenario(records, scenario_name)
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot_table(
        index=["holding_name", "asset_type", "bucket_name"],
        columns="portfolio_state",
        values=["current_value_gbp", "scenario_value_gbp", "pnl_gbp"],
        aggfunc="first",
    )
    pivot.columns = [f"{val}_{state}" for val, state in pivot.columns]
    return pivot.fillna(0.0).reset_index()


def compute_scenario_totals(records: list[dict], scenario_name: str) -> dict[str, float]:
    df = _filter_to_scenario(records, scenario_name)
    if df.empty:
        return {}
    return df.groupby("portfolio_state")["pnl_gbp"].sum().to_dict()


def build_coverage_summary(records: list[dict], scenario_name: str) -> pd.DataFrame:
    df = _filter_to_scenario(records, scenario_name)
    if df.empty:
        return pd.DataFrame(columns=["portfolio_state", "model_status", "count"])
    return (
        df.groupby(["portfolio_state", "model_status"])
        .size()
        .reset_index(name="count")
    )
