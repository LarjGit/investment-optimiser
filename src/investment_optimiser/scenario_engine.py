from __future__ import annotations

from datetime import date

import pandas as pd

from investment_optimiser.gilt_analytics import (
    clean_price_from_gry,
    settlement_date_for,
)

_ASSET_TYPES_LISTED_RISK = {"equity", "etf"}
_ASSET_TYPES_DIVERSIFIERS = {"investment_trust", "reit", "fund"}


def run_scenarios(
    enriched_holdings_df: pd.DataFrame,
    executable_df: pd.DataFrame,
    policy: dict,
    gilt_ref_df: pd.DataFrame,
    *,
    scenario_magnitude: float = 1.0,
    reference_date: date | None = None,
) -> list[dict]:
    """Reprice both portfolio states under every named scenario.

    Returns a flat list of canonical long-form records — one per
    holding × scenario × portfolio state.
    """
    if enriched_holdings_df.empty:
        return []

    today = reference_date or date.today()
    settlement = settlement_date_for(today)
    gilt_lookup = _build_gilt_lookup(gilt_ref_df)
    bucket_labels: dict[str, str] = policy.get("bucket_labels", {})

    states: list[tuple[str, pd.DataFrame]] = [("current", enriched_holdings_df)]
    if not executable_df.empty:
        states.append(("executable_recommended", executable_df))

    records: list[dict] = []
    for scenario in policy.get("named_scenarios", []):
        shocks = {k: v * scenario_magnitude for k, v in scenario["base_shocks"].items()}
        for portfolio_state, holdings_df in states:
            for row in holdings_df.to_dict("records"):
                rec = _reprice_holding(
                    row, scenario["id"], portfolio_state, shocks,
                    gilt_lookup, bucket_labels, settlement,
                )
                records.append(rec)

    return records


def _build_gilt_lookup(gilt_ref_df: pd.DataFrame) -> dict[str, dict]:
    """Return {tidm: {coupon_pct, gry_pct, maturity_date, instrument_type, real_gry_pct}}."""
    if gilt_ref_df.empty or "tidm" not in gilt_ref_df.columns:
        return {}
    lookup: dict[str, dict] = {}
    for row in gilt_ref_df.to_dict("records"):
        tidm = row.get("tidm")
        if tidm and pd.notna(tidm):
            real_gry_raw = row.get("real_gry_pct")
            lookup[str(tidm)] = {
                "coupon_pct": row.get("coupon_pct"),
                "gry_pct": row.get("gry_pct"),
                "maturity_date": row.get("maturity_date"),
                "instrument_type": row.get("instrument_type", "Conventional"),
                "real_gry_pct": None if pd.isna(real_gry_raw) else float(real_gry_raw),
            }
    return lookup


def _reprice_holding(
    row: dict,
    scenario_name: str,
    portfolio_state: str,
    shocks: dict,
    gilt_lookup: dict[str, dict],
    bucket_labels: dict[str, str],
    settlement: date,
) -> dict:
    symbol = str(row.get("symbol", ""))
    asset_type = str(row.get("asset_type") or "")
    # executable_df uses proposed_value_gbp; enriched_holdings_df uses market_value_gbp
    current_value = float(
        row.get("market_value_gbp") or row.get("proposed_value_gbp") or 0.0
    )
    bucket_id = str(row.get("bucket_id") or "")

    scenario_value, model_status, notes = _compute_scenario_value(
        row, asset_type, current_value, shocks, gilt_lookup, settlement,
    )

    pnl = scenario_value - current_value

    return {
        "portfolio_state": portfolio_state,
        "scenario_name": scenario_name,
        "holding_id": symbol,
        "holding_name": str(row.get("name") or symbol),
        "asset_type": asset_type,
        "bucket_name": bucket_labels.get(bucket_id, bucket_id),
        "current_value_gbp": current_value,
        "scenario_value_gbp": scenario_value,
        "pnl_gbp": pnl,
        "model_status": model_status,
        "notes": notes,
    }


def _compute_scenario_value(
    row: dict,
    asset_type: str,
    current_value: float,
    shocks: dict,
    gilt_lookup: dict[str, dict],
    settlement: date,
) -> tuple[float, str, str]:
    """Return (scenario_value_gbp, model_status, notes)."""

    if asset_type == "gilt_conventional":
        return _reprice_conventional_gilt(row, current_value, shocks, gilt_lookup, settlement)

    if asset_type == "gilt_index_linked":
        return _reprice_il_gilt(row, current_value, shocks, gilt_lookup, settlement)

    if asset_type == "mmf":
        return current_value, "held_flat", "MMF capital value flat; income changes only."

    if asset_type in _ASSET_TYPES_LISTED_RISK:
        shock_pct = shocks.get("listed_risk_assets_pct", 0.0)
        return current_value * (1.0 + shock_pct / 100.0), "exact", f"Listed risk asset: {shock_pct:+.1f}% shock."

    if asset_type in _ASSET_TYPES_DIVERSIFIERS:
        shock_pct = shocks.get("diversifiers_and_manual_pct", 0.0)
        return current_value * (1.0 + shock_pct / 100.0), "exact", f"Diversifier: {shock_pct:+.1f}% shock."

    return current_value, "unmodelled_held_flat", f"No scenario model for asset_type '{asset_type}'."


def _reprice_il_gilt(
    row: dict,
    current_value: float,
    shocks: dict,
    gilt_lookup: dict[str, dict],
    settlement: date,
) -> tuple[float, str, str]:
    """Reprice an IL gilt by shocking its real yield.

    Uses the ``real_gry_pct`` computed by the analytics handler (which resolves the
    shared observed-inflation contract) as the baseline, then applies the scenario's
    ``real_yield_parallel_bps`` shock.  Proportional repricing avoids the need for
    ``index_ratio``, which cancels in the baseline/scenario price ratio.
    """
    symbol = str(row.get("symbol", ""))
    ref = gilt_lookup.get(symbol)
    if ref is None:
        return current_value, "unmodelled_held_flat", "IL gilt not found in reference data; held at spot."

    real_gry_pct = ref.get("real_gry_pct")
    if real_gry_pct is None:
        return current_value, "unmodelled_held_flat", "IL gilt real GRY unavailable; held at spot."

    coupon_pct = ref.get("coupon_pct")
    maturity_date_str = ref.get("maturity_date")
    if coupon_pct is None or maturity_date_str is None:
        return current_value, "unmodelled_held_flat", "Missing IL gilt reference data; held at spot."

    try:
        maturity = date.fromisoformat(str(maturity_date_str))
    except (ValueError, TypeError):
        return current_value, "unmodelled_held_flat", "Invalid IL gilt maturity date; held at spot."

    real_shock_bps = shocks.get("real_yield_parallel_bps", 0.0)
    # IL real yields are small (typically −0.5% to +2.5%), so bps must be converted
    # correctly (÷10000) to avoid pushing shocked yields into non-physical territory.
    shocked_real_gry = real_gry_pct + real_shock_bps / 10000.0

    baseline_price = clean_price_from_gry(real_gry_pct, float(coupon_pct), maturity, settlement)
    scenario_price = clean_price_from_gry(shocked_real_gry, float(coupon_pct), maturity, settlement)

    if baseline_price is None or baseline_price <= 0 or scenario_price is None:
        return current_value, "unmodelled_held_flat", "IL gilt price solve failed; held at spot."

    scenario_value = current_value * (scenario_price / baseline_price)
    notes = f"Real GRY shock {real_shock_bps:+.1f}bps (real yield parallel)."
    return scenario_value, "exact", notes


def _reprice_conventional_gilt(
    row: dict,
    current_value: float,
    shocks: dict,
    gilt_lookup: dict[str, dict],
    settlement: date,
) -> tuple[float, str, str]:
    symbol = str(row.get("symbol", ""))
    ref = gilt_lookup.get(symbol)
    if ref is None:
        return current_value, "unmodelled_held_flat", "Gilt not found in reference data; held at spot."

    baseline_gry = ref.get("gry_pct")
    coupon_pct = ref.get("coupon_pct")
    maturity_date_str = ref.get("maturity_date")

    if baseline_gry is None or coupon_pct is None or maturity_date_str is None:
        return current_value, "unmodelled_held_flat", "Missing gilt reference data; held at spot."

    try:
        maturity = date.fromisoformat(str(maturity_date_str))
    except (ValueError, TypeError):
        return current_value, "unmodelled_held_flat", "Invalid maturity date; held at spot."

    years_to_maturity = (maturity - settlement).days / 365.25
    parallel_bps = shocks.get("nominal_curve_parallel_bps", 0.0)
    steepener_bps = shocks.get("nominal_curve_2s10s_steepener_bps", 0.0)
    steepener_fraction = max(0.0, min(1.0, (years_to_maturity - 2.0) / 8.0))
    total_shock_bps = parallel_bps + steepener_bps * steepener_fraction

    scenario_gry = float(baseline_gry) + total_shock_bps / 10000.0

    # Proportional repricing: ratio of scenario price to baseline price, applied to
    # current market value.  This mirrors the IL gilt approach and avoids any
    # dependency on the qty / face-value column (which varies by caller).
    baseline_price = clean_price_from_gry(float(baseline_gry), float(coupon_pct), maturity, settlement)
    scenario_price = clean_price_from_gry(scenario_gry, float(coupon_pct), maturity, settlement)

    if baseline_price is None or baseline_price <= 0 or scenario_price is None:
        return current_value, "unmodelled_held_flat", "Price solve failed; held at spot."

    scenario_value = current_value * (scenario_price / baseline_price)
    notes = (
        f"GRY shock {total_shock_bps:+.1f}bps "
        f"({parallel_bps:+.1f} parallel, {steepener_bps * steepener_fraction:+.1f} steepener)."
    )
    return scenario_value, "exact", notes
