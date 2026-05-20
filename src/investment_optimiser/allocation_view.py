from typing import TYPE_CHECKING

import pandas as pd

from investment_optimiser.bucket_assignment import assign_bucket

if TYPE_CHECKING:
    import pandas.io.formats.style as _style


def enrich_with_buckets(holdings_df: pd.DataFrame) -> pd.DataFrame:
    if holdings_df.empty:
        return holdings_df.assign(bucket_id=pd.Series(dtype=str), resolution_method=pd.Series(dtype=str))
    rows = holdings_df.to_dict("records")
    resolutions = [assign_bucket(r) for r in rows]
    return holdings_df.assign(
        bucket_id=[r.bucket_id for r in resolutions],
        resolution_method=[r.method for r in resolutions],
    )


def build_allocation_table(
    holdings_df: pd.DataFrame,
    baseline_weights: dict[str, float],
    bucket_labels: dict[str, str],
) -> pd.DataFrame:
    baseline_df = pd.DataFrame(
        [{"bucket_id": bid, "baseline_pct": w} for bid, w in baseline_weights.items()]
    )

    if holdings_df.empty:
        baseline_df["current_pct"] = 0.0
        baseline_df["drift_pct"] = -baseline_df["baseline_pct"]
        baseline_df["uncertain"] = False
        baseline_df["label"] = baseline_df["bucket_id"].map(bucket_labels)
        return baseline_df[["bucket_id", "label", "current_pct", "baseline_pct", "drift_pct", "uncertain"]]

    enriched = enrich_with_buckets(holdings_df)
    total_value = enriched["market_value_gbp"].sum()

    bucket_totals = (
        enriched.groupby("bucket_id", as_index=False)
        .agg(
            market_value_gbp=("market_value_gbp", "sum"),
            uncertain=("resolution_method", lambda s: s.isin({"name_keywords", "catch_all"}).any()),
        )
    )
    bucket_totals["current_pct"] = (
        bucket_totals["market_value_gbp"] / total_value * 100 if total_value > 0 else 0.0
    )

    alloc = baseline_df.merge(bucket_totals[["bucket_id", "current_pct", "uncertain"]], on="bucket_id", how="left")
    alloc["current_pct"] = alloc["current_pct"].fillna(0.0)
    alloc["uncertain"] = alloc["uncertain"].fillna(False)
    alloc["drift_pct"] = alloc["current_pct"] - alloc["baseline_pct"]
    alloc["label"] = alloc["bucket_id"].map(bucket_labels)

    return alloc[["bucket_id", "label", "current_pct", "baseline_pct", "drift_pct", "uncertain"]]


def style_allocation_table(df: pd.DataFrame) -> "pandas.io.formats.style.Styler":
    def _colour_drift(val: float) -> str:
        if val > 0:
            return "color: green"
        if val < 0:
            return "color: red"
        return ""

    return df.style.map(_colour_drift, subset=["Drift %"])
