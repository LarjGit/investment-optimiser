from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from investment_optimiser.friction_gate import GatedTrade


_LIQUIDITY_BUCKET = "liquidity_reserve"


@dataclass(frozen=True)
class RiskGatedTrade:
    gated_trade: GatedTrade
    risk_gate_outcome: str  # "pass" | "blocked_concentration" | "blocked_maturity" | "blocked_liquidity" | "not_gated"
    risk_gate_note: str


def risk_gate_trades(
    gated_trades: list[GatedTrade],
    proposed_state_df: pd.DataFrame,
    policy: dict[str, Any],
    maturity_by_isin: dict[str, float | None],
) -> list[RiskGatedTrade]:
    constraints = policy["default_constraints"]
    max_concentration_pct: float = constraints["max_single_position_pct"]
    max_maturity_years: float = constraints["max_maturity_years"]
    min_liquidity_pct: float = constraints["minimum_cash_mmf_pct"]

    total_portfolio = float(proposed_state_df["proposed_value_gbp"].sum())
    liquidity_value = float(
        proposed_state_df.loc[
            proposed_state_df["bucket_id"] == _LIQUIDITY_BUCKET, "proposed_value_gbp"
        ].sum()
    )
    liquidity_pct = (liquidity_value / total_portfolio * 100.0) if total_portfolio > 0 else 0.0
    liquidity_breached = liquidity_pct < min_liquidity_pct

    result: list[RiskGatedTrade] = []
    for gt in gated_trades:
        trade = gt.trade

        if gt.gate_outcome == "red" or trade.delta_value_gbp <= 0.0:
            label = (
                "Already blocked by friction gate"
                if gt.gate_outcome == "red"
                else "Sell trade — not independently gated"
            )
            result.append(RiskGatedTrade(gated_trade=gt, risk_gate_outcome="not_gated", risk_gate_note=label))
            continue

        isin = trade.isin
        mask = proposed_state_df["isin"] == isin
        if mask.any() and total_portfolio > 0:
            proposed_value = float(proposed_state_df.loc[mask, "proposed_value_gbp"].iloc[0])
            position_pct = proposed_value / total_portfolio * 100.0
            if position_pct > max_concentration_pct:
                result.append(RiskGatedTrade(
                    gated_trade=gt,
                    risk_gate_outcome="blocked_concentration",
                    risk_gate_note=(
                        f"Position would be {position_pct:.1f}% of portfolio — "
                        f"concentration limit is {max_concentration_pct:.1f}%"
                    ),
                ))
                continue

        maturity = maturity_by_isin.get(isin) if isin else None
        if maturity is not None and maturity > max_maturity_years:
            result.append(RiskGatedTrade(
                gated_trade=gt,
                risk_gate_outcome="blocked_maturity",
                risk_gate_note=(
                    f"Gilt matures in {maturity:.1f} years — "
                    f"policy ceiling is {max_maturity_years:.0f} years"
                ),
            ))
            continue

        if liquidity_breached:
            result.append(RiskGatedTrade(
                gated_trade=gt,
                risk_gate_outcome="blocked_liquidity",
                risk_gate_note=(
                    f"Post-trade liquidity would be {liquidity_pct:.1f}% — "
                    f"floor is {min_liquidity_pct:.0f}%"
                ),
            ))
            continue

        result.append(RiskGatedTrade(
            gated_trade=gt,
            risk_gate_outcome="pass",
            risk_gate_note="All risk gate checks passed",
        ))

    return result


def apply_risk_gate_to_proposed_state(
    risk_gated_trades: list[RiskGatedTrade],
    proposed_state_df: pd.DataFrame,
) -> pd.DataFrame:
    df = proposed_state_df.copy()
    freed_cash = 0.0

    for rgt in risk_gated_trades:
        if rgt.risk_gate_outcome in ("pass", "not_gated"):
            continue
        trade = rgt.gated_trade.trade
        mask = df["isin"] == trade.isin
        if not mask.any():
            continue
        original_proposed = float(df.loc[mask, "proposed_value_gbp"].iloc[0])
        df.loc[mask, "proposed_value_gbp"] = trade.current_value_gbp
        freed_cash += original_proposed - trade.current_value_gbp

    if abs(freed_cash) < 1e-9:
        return df

    liq_mask = df["bucket_id"] == _LIQUIDITY_BUCKET
    if liq_mask.any():
        df.loc[liq_mask, "proposed_value_gbp"] += freed_cash
    else:
        df = pd.concat([df, pd.DataFrame([{
            "isin": None,
            "symbol": None,
            "bucket_id": _LIQUIDITY_BUCKET,
            "asset_type": "mmf",
            "proposed_value_gbp": round(freed_cash, 2),
        }])], ignore_index=True)

    return df
