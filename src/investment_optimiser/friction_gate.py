from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from investment_optimiser.trade_construction import Trade


_LIQUIDITY_BUCKET = "liquidity_reserve"
_STAMP_DUTY_FRICTION_CLASS = "equities_and_investment_trusts"
_STAMP_DUTY_RATE = 0.005

_ASSET_TYPE_TO_FRICTION_CLASS: dict[str | None, str] = {
    "gilt_conventional": "conventional_gilts",
    "gilt_index_linked": "index_linked_gilts",
    "mmf": "cash_and_mmf",
    "equity": "equities_and_investment_trusts",
    "investment_trust": "equities_and_investment_trusts",
    "reit": "equities_and_investment_trusts",
    "fund": "equities_and_investment_trusts",
    "etf": "equities_and_investment_trusts",
    "other": "equities_and_investment_trusts",
}

_FALLBACK_FRICTION_CLASS = "equities_and_investment_trusts"


def derive_friction_class(asset_type: str | None) -> str:
    return _ASSET_TYPE_TO_FRICTION_CLASS.get(asset_type, _FALLBACK_FRICTION_CLASS)


@dataclass(frozen=True)
class GatedTrade:
    trade: Trade
    friction_class: str
    commission_gbp: float
    spread_cost_gbp: float
    stamp_duty_gbp: float
    total_friction_gbp: float
    yield_improvement_bps: float | None
    break_even_months: float | None
    gate_outcome: str
    gate_note: str


def _friction_costs(
    trade: Trade,
    commission_gbp: float,
    spread_bps_by_class: dict[str, float],
) -> tuple[str, float, float, float, float]:
    friction_class = derive_friction_class(trade.asset_type)
    position_size = abs(trade.delta_value_gbp)
    commission = 2.0 * commission_gbp
    spread_bps = spread_bps_by_class.get(friction_class, 0.0)
    spread = spread_bps / 10_000.0 * position_size
    stamp_duty = _STAMP_DUTY_RATE * position_size if friction_class == _STAMP_DUTY_FRICTION_CLASS else 0.0
    total = commission + spread + stamp_duty
    return friction_class, commission, spread, stamp_duty, total


def _break_even_months(
    total_friction_gbp: float,
    yield_improvement_bps: float | None,
    position_size_gbp: float,
) -> float | None:
    if yield_improvement_bps is None or yield_improvement_bps <= 0.0:
        return None
    annual_gain = (yield_improvement_bps / 10_000.0) * position_size_gbp
    if annual_gain < 1e-6:
        return None
    return (total_friction_gbp / annual_gain) * 12.0


def _classify(
    break_even_months: float | None,
    expected_hold_period_years: float,
) -> tuple[str, str]:
    hold_months = expected_hold_period_years * 12.0
    green_threshold = hold_months * 0.5
    amber_threshold = hold_months
    if break_even_months is None:
        return "red", "No yield improvement — trade not recommended"
    if break_even_months < green_threshold:
        return "green", f"Break-even {break_even_months:.1f} months — recommended"
    if break_even_months <= amber_threshold:
        return "amber", f"Break-even {break_even_months:.1f} months — marginal"
    return "red", f"Break-even {break_even_months:.1f} months — not recommended"


def break_even_estimate(
    position_size_gbp: float,
    yield_gap_pct: float,
    commission_gbp: float,
    spread_bps: float,
    hold_period_years: float,
) -> tuple[float | None, str]:
    """Return (break_even_months, outcome) for a prospective gilt switch signal.

    Intended for the signal-layer banner, not the full trade pipeline.
    Uses the same underlying helpers as gate_trades so thresholds stay consistent.
    """
    total_friction = 2.0 * commission_gbp + (spread_bps / 10_000.0) * position_size_gbp
    yield_improvement_bps = yield_gap_pct * 10_000.0
    months = _break_even_months(total_friction, yield_improvement_bps, position_size_gbp)
    outcome, _ = _classify(months, hold_period_years)
    return months, outcome


def gate_trades(
    trades: list[Trade],
    yield_improvement_bps_by_isin: dict[str, float | None],
    policy: dict[str, Any],
) -> list[GatedTrade]:
    fields = {f["key"]: f["default"] for f in policy["shared_assumption_schema"]["fields"]}
    commission_gbp: float = fields["interactive_investor_trade_fee_gbp"]
    hold_period_years: float = fields["expected_hold_period_years"]
    spread_bps_by_class: dict[str, float] = fields["spread_bps_by_friction_class"]

    result: list[GatedTrade] = []
    for trade in trades:
        if trade.delta_value_gbp <= 0.0:
            result.append(GatedTrade(
                trade=trade,
                friction_class=derive_friction_class(trade.asset_type),
                commission_gbp=0.0,
                spread_cost_gbp=0.0,
                stamp_duty_gbp=0.0,
                total_friction_gbp=0.0,
                yield_improvement_bps=None,
                break_even_months=None,
                gate_outcome="not_gated",
                gate_note="Sell trade — not independently gated",
            ))
            continue

        friction_class, commission, spread, stamp_duty, total = _friction_costs(
            trade, commission_gbp, spread_bps_by_class
        )
        improvement = yield_improvement_bps_by_isin.get(trade.isin)
        be_months = _break_even_months(total, improvement, abs(trade.delta_value_gbp))
        outcome, note = _classify(be_months, hold_period_years)

        result.append(GatedTrade(
            trade=trade,
            friction_class=friction_class,
            commission_gbp=commission,
            spread_cost_gbp=spread,
            stamp_duty_gbp=stamp_duty,
            total_friction_gbp=total,
            yield_improvement_bps=improvement,
            break_even_months=be_months,
            gate_outcome=outcome,
            gate_note=note,
        ))

    return result


def apply_gate_to_proposed_state(
    gated_trades: list[GatedTrade],
    proposed_state_df: pd.DataFrame,
) -> pd.DataFrame:
    df = proposed_state_df.copy()
    freed_cash = 0.0

    for gt in gated_trades:
        if gt.gate_outcome != "red":
            continue
        trade = gt.trade
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
