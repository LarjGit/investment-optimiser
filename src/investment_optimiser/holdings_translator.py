from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


_GILT_BUCKETS = {"short_duration_nominal_gilts", "long_duration_nominal_gilts"}
_SHORT_MATURITY_CUTOFF_YEARS = 5.0


@dataclass(frozen=True)
class HoldingsTranslationResult:
    target_df: pd.DataFrame
    bucket_summary: pd.DataFrame
    warnings: list[str]


def translate_bucket_targets_to_holdings(
    bucket_target_weights: dict[str, float],
    enriched_holdings_df: pd.DataFrame,
    total_portfolio_value_gbp: float,
    gilt_candidates_df: pd.DataFrame | None = None,
    *,
    reference_date: date | None = None,
) -> HoldingsTranslationResult:
    today = reference_date or date.today()
    warnings: list[str] = []
    rows: list[dict] = []

    all_bucket_ids = set(enriched_holdings_df["bucket_id"].unique()) | set(bucket_target_weights.keys())

    for bucket_id in all_bucket_ids:
        target_pct = bucket_target_weights.get(bucket_id)
        bucket_holdings = (
            enriched_holdings_df[enriched_holdings_df["bucket_id"] == bucket_id]
            if not enriched_holdings_df.empty
            else pd.DataFrame()
        )
        has_holdings = not bucket_holdings.empty

        if target_pct is None:
            # Bucket not in targets — pass through unchanged
            for _, h in bucket_holdings.iterrows():
                rows.append(_passthrough_row(h, total_portfolio_value_gbp))
            continue

        target_value = target_pct / 100.0 * total_portfolio_value_gbp

        if has_holdings:
            rows.extend(
                _scale_existing(bucket_holdings, bucket_id, target_value, total_portfolio_value_gbp)
            )
        else:
            new_rows, new_warnings = _deploy_into_empty_bucket(
                bucket_id, target_value, total_portfolio_value_gbp, gilt_candidates_df, today
            )
            rows.extend(new_rows)
            warnings.extend(new_warnings)

    target_df = _build_target_df(rows)
    bucket_summary = _build_bucket_summary(target_df, total_portfolio_value_gbp)
    return HoldingsTranslationResult(target_df=target_df, bucket_summary=bucket_summary, warnings=warnings)


def _scale_existing(
    bucket_holdings: pd.DataFrame,
    bucket_id: str,
    target_value: float,
    total_portfolio_value_gbp: float,
) -> list[dict]:
    bucket_current_total = float(bucket_holdings["market_value_gbp"].sum())
    result_rows = []
    for _, h in bucket_holdings.iterrows():
        current_val = float(h["market_value_gbp"])
        tgt_val = current_val / bucket_current_total * target_value if bucket_current_total > 0 else 0.0
        result_rows.append({
            "symbol": h.get("symbol"),
            "isin": h.get("isin"),
            "bucket_id": bucket_id,
            "asset_type": h.get("asset_type"),
            "is_new_position": False,
            "current_value_gbp": current_val,
            "current_weight_pct": current_val / total_portfolio_value_gbp * 100.0,
            "target_value_gbp": tgt_val,
            "target_weight_pct": tgt_val / total_portfolio_value_gbp * 100.0,
            "delta_value_gbp": tgt_val - current_val,
        })
    return result_rows


def _deploy_into_empty_bucket(
    bucket_id: str,
    target_value: float,
    total_portfolio_value_gbp: float,
    gilt_candidates_df: pd.DataFrame | None,
    today: date,
) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []

    if bucket_id in _GILT_BUCKETS and gilt_candidates_df is not None and not gilt_candidates_df.empty:
        candidate = _pick_gilt_candidate(gilt_candidates_df, bucket_id, today)
        if candidate is not None:
            warnings.append(
                f"New gilt position opened in '{bucket_id}': {candidate['isin']} "
                f"(no existing holdings in this bucket)"
            )
            row = _new_position_row(
                candidate["isin"], candidate.get("instrument_name"),
                bucket_id, target_value, total_portfolio_value_gbp,
            )
            return [row], warnings

    warnings.append(
        f"Bucket '{bucket_id}' has a target of {target_value:.0f} GBP but no current holdings "
        "and no suitable candidate — allocation is unfulfilled"
    )
    return [_sentinel_row(bucket_id, target_value, total_portfolio_value_gbp)], warnings


def _pick_gilt_candidate(
    gilt_candidates_df: pd.DataFrame,
    bucket_id: str,
    today: date,
) -> dict | None:
    df = gilt_candidates_df.copy()
    df["_maturity_years"] = (
        (pd.to_datetime(df["maturity_date"]) - pd.Timestamp(today)).dt.days / 365.25
    )
    if bucket_id == "short_duration_nominal_gilts":
        df = df[df["_maturity_years"] <= _SHORT_MATURITY_CUTOFF_YEARS]
    else:
        df = df[df["_maturity_years"] > _SHORT_MATURITY_CUTOFF_YEARS]

    df = df.dropna(subset=["gry_pct"])
    if df.empty:
        return None
    return df.sort_values("gry_pct", ascending=False).iloc[0].to_dict()


def _passthrough_row(h: pd.Series, total_portfolio_value_gbp: float) -> dict:
    current_val = float(h["market_value_gbp"])
    weight_pct = current_val / total_portfolio_value_gbp * 100.0
    return {
        "symbol": h.get("symbol"),
        "isin": h.get("isin"),
        "bucket_id": h.get("bucket_id"),
        "asset_type": h.get("asset_type"),
        "is_new_position": False,
        "current_value_gbp": current_val,
        "current_weight_pct": weight_pct,
        "target_value_gbp": current_val,
        "target_weight_pct": weight_pct,
        "delta_value_gbp": 0.0,
    }


def _new_position_row(
    isin: str,
    instrument_name: str | None,
    bucket_id: str,
    target_value: float,
    total_portfolio_value_gbp: float,
) -> dict:
    return {
        "symbol": instrument_name,
        "isin": isin,
        "bucket_id": bucket_id,
        "asset_type": "gilt_conventional",
        "is_new_position": True,
        "current_value_gbp": 0.0,
        "current_weight_pct": 0.0,
        "target_value_gbp": target_value,
        "target_weight_pct": target_value / total_portfolio_value_gbp * 100.0,
        "delta_value_gbp": target_value,
    }


def _sentinel_row(bucket_id: str, target_value: float, total_portfolio_value_gbp: float) -> dict:
    return {
        "symbol": None,
        "isin": None,
        "bucket_id": bucket_id,
        "asset_type": None,
        "is_new_position": False,
        "current_value_gbp": 0.0,
        "current_weight_pct": 0.0,
        "target_value_gbp": target_value,
        "target_weight_pct": target_value / total_portfolio_value_gbp * 100.0,
        "delta_value_gbp": target_value,
    }


def _build_target_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[
            "symbol", "isin", "bucket_id", "asset_type", "is_new_position",
            "current_value_gbp", "current_weight_pct",
            "target_value_gbp", "target_weight_pct", "delta_value_gbp",
        ])
    return pd.DataFrame(rows)


def _build_bucket_summary(
    target_df: pd.DataFrame,
    total_portfolio_value_gbp: float,
) -> pd.DataFrame:
    if target_df.empty:
        return pd.DataFrame(columns=["bucket_id", "current_pct", "target_pct", "delta_pct"])
    summary = (
        target_df.groupby("bucket_id", as_index=False)
        .agg(
            current_pct=("current_value_gbp", lambda s: s.sum() / total_portfolio_value_gbp * 100.0),
            target_pct=("target_value_gbp", lambda s: s.sum() / total_portfolio_value_gbp * 100.0),
        )
    )
    summary["delta_pct"] = summary["target_pct"] - summary["current_pct"]
    return summary
