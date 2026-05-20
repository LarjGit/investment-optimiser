from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


GILT_NOMINAL_INCREMENT = 100
_ROUNDABLE_ASSET_TYPES = {"gilt_conventional"}
_LIQUIDITY_BUCKET = "liquidity_reserve"


@dataclass(frozen=True)
class Trade:
    isin: str | None
    symbol: str | None
    bucket_id: str
    asset_type: str | None
    is_new_position: bool
    current_value_gbp: float
    target_value_gbp: float
    delta_value_gbp: float
    clean_price_gbp: float | None = None
    nominal_delta: float | None = None
    rounded_nominal_delta: int | None = None
    executable_delta_gbp: float | None = None
    residual_cash_gbp: float | None = None


@dataclass(frozen=True)
class TradeConstructionResult:
    trades: list[Trade]
    total_residual_cash_gbp: float
    proposed_state_df: pd.DataFrame
    warnings: list[str]


def round_nominal_conservative(delta: float, increment: int = GILT_NOMINAL_INCREMENT) -> int:
    return math.trunc(delta / increment) * increment


def construct_trades(
    target_df: pd.DataFrame,
    gilt_prices: dict[str, float],
) -> TradeConstructionResult:
    trades: list[Trade] = []
    warnings: list[str] = []
    total_residual = 0.0
    proposed_rows: list[dict] = []

    for _, row in target_df.iterrows():
        isin = row.get("isin")
        symbol = row.get("symbol")
        bucket_id = str(row["bucket_id"])
        asset_type = row.get("asset_type")
        is_new_position = bool(row.get("is_new_position", False))
        current_val = float(row["current_value_gbp"])
        target_val = float(row["target_value_gbp"])
        delta = float(row["delta_value_gbp"])

        if isin is None:
            warnings.append(
                f"Sentinel row in bucket '{bucket_id}' (isin=None) excluded from trades — "
                "allocation is unfulfilled"
            )
            proposed_rows.append({
                "isin": isin,
                "symbol": symbol,
                "bucket_id": bucket_id,
                "asset_type": asset_type,
                "proposed_value_gbp": current_val,
            })
            continue

        is_gilt = asset_type in _ROUNDABLE_ASSET_TYPES
        if is_gilt and isin not in gilt_prices:
            warnings.append(
                f"No price available for gilt {isin} — rounding skipped, treated as non-gilt"
            )
            is_gilt = False

        if is_gilt:
            price = gilt_prices[isin]
            nominal_delta = delta / price * 100.0
            rounded = round_nominal_conservative(nominal_delta)
            executable = rounded * price / 100.0
            residual = delta - executable
            total_residual += residual
            trade = Trade(
                isin=isin,
                symbol=symbol,
                bucket_id=bucket_id,
                asset_type=asset_type,
                is_new_position=is_new_position,
                current_value_gbp=current_val,
                target_value_gbp=target_val,
                delta_value_gbp=delta,
                clean_price_gbp=price,
                nominal_delta=nominal_delta,
                rounded_nominal_delta=rounded,
                executable_delta_gbp=executable,
                residual_cash_gbp=residual,
            )
        else:
            executable = delta
            trade = Trade(
                isin=isin,
                symbol=symbol,
                bucket_id=bucket_id,
                asset_type=asset_type,
                is_new_position=is_new_position,
                current_value_gbp=current_val,
                target_value_gbp=target_val,
                delta_value_gbp=delta,
            )

        trades.append(trade)
        proposed_rows.append({
            "isin": isin,
            "symbol": symbol,
            "bucket_id": bucket_id,
            "asset_type": asset_type,
            "proposed_value_gbp": current_val + executable,
        })

    proposed_df = _apply_residual_to_liquidity(proposed_rows, total_residual)

    return TradeConstructionResult(
        trades=trades,
        total_residual_cash_gbp=round(total_residual, 2),
        proposed_state_df=proposed_df,
        warnings=warnings,
    )


def _apply_residual_to_liquidity(
    proposed_rows: list[dict],
    total_residual: float,
) -> pd.DataFrame:
    if abs(total_residual) >= 1e-9:
        idx = next(
            (i for i, r in enumerate(proposed_rows) if r["bucket_id"] == _LIQUIDITY_BUCKET),
            None,
        )
        if idx is not None:
            row = proposed_rows[idx]
            proposed_rows[idx] = {**row, "proposed_value_gbp": row["proposed_value_gbp"] + total_residual}
        else:
            proposed_rows.append({
                "isin": None,
                "symbol": None,
                "bucket_id": _LIQUIDITY_BUCKET,
                "asset_type": "mmf",
                "proposed_value_gbp": round(total_residual, 2),
            })

    return pd.DataFrame(proposed_rows) if proposed_rows else _empty_proposed_df()


def _empty_proposed_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["isin", "symbol", "bucket_id", "asset_type", "proposed_value_gbp"])
