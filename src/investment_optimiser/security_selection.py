"""Security-level Mixed Integer Programme for trade selection.

Replaces the proportional-spread + post-hoc friction gate pipeline
(holdings_translator → trade_construction → friction_gate) with a single MIP
that produces a sparse, friction-viable trade list.

Architecture
------------
The MIP sits between the bucket LP and the risk gate::

    Level 1 — bucket LP (unchanged):  target_bucket_weights
    Level 2 — security MIP (this module):  proposed_state_df + gated_trades
    Risk gate (unchanged):  concentration, maturity, liquidity checks

Formulation
-----------
For each *non-MMF* holding i, variables:

    x_plus[i]  ≥ 0          amount bought
    x_minus[i] ≥ 0          amount sold (bounded above by current holding — no short)
    y_buy[i]   ∈ {0, 1}     1 if position i is bought this period
    y_sell[i]  ∈ {0, 1}     1 if position i is sold this period

MMF/liquidity holdings get plain continuous variables (no binary, no fixed cost):

    x_mmf_plus[k]   ≥ 0    buy (receives proceeds from gilt sells)
    x_mmf_minus[k]  ≥ 0    sell (funds gilt or equity buys)

Objective (minimise)::

    Σ_i [ spread_cost · (x_plus + x_minus)
          + 2·commission · y_buy          # round-trip assumption for buys
          + commission   · y_sell          # one-way for sells
          - alignment_tiebreak · (x_plus − x_minus) ]
    + MMF terms (spread only, no commission)

Constraints::

    Cash balance:     Σ(x_plus − x_minus) + Σ_MMF(x_mmf_plus − x_mmf_minus) = 0
    Big-M:            x_plus[i]  ≤ M · y_buy[i]
                      x_minus[i] ≤ M · y_sell[i]
    One direction:    y_buy[i] + y_sell[i] ≤ 1
    Minimum trade:    x_plus[i]  ≥ min_trade · y_buy[i]
                      x_minus[i] ≥ min_trade · y_sell[i]
    No short-sell:    x_minus[i] ≤ current_value[i]   (via upper bounds)
    Bucket targets:   |(new_bucket_value − target_bucket_value)| ≤ epsilon
                      where epsilon = BUCKET_EPSILON_PCT % of total portfolio
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

from investment_optimiser.friction_gate import GatedTrade, derive_friction_class
from investment_optimiser.trade_construction import Trade, round_nominal_conservative

logger = logging.getLogger(__name__)

_LIQUIDITY_BUCKET = "liquidity_reserve"
_MMF_ASSET_TYPES = frozenset({"mmf"})

# ±0.5 % of total portfolio as tolerance for hitting LP bucket targets.
# Wide enough to absorb gilt lot-rounding residuals (typically <£100 per holding);
# narrow enough to enforce LP recommendations of ≥0.5 % weight shifts.
_BUCKET_EPSILON_PCT = 0.5

# Trades smaller than this (in £) after MIP rounding are discarded.
_TRADE_TOL_GBP = 0.01


@dataclass(frozen=True)
class SecuritySelectionResult:
    """Output of :func:`select_trades`."""

    proposed_state_df: pd.DataFrame
    """All holdings with ``proposed_value_gbp`` column (shape matches risk gate input)."""

    gated_trades: list[GatedTrade]
    """Traded positions only; every trade has ``gate_outcome='green'`` by construction."""

    solver_status: str
    """``'optimal'`` | ``'infeasible'`` | ``'error'``"""

    warnings: list[str]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def select_trades(
    current_holdings_df: pd.DataFrame,
    target_bucket_weights: dict[str, float],
    total_portfolio_gbp: float,
    gilt_candidates_df: pd.DataFrame | None,
    policy: dict[str, Any],
    *,
    gilt_price_lookup_df: pd.DataFrame | None = None,
) -> SecuritySelectionResult:
    """Return a friction-viable proposed portfolio state.

    Every trade in ``gated_trades`` has already been evaluated against transaction
    costs inside the MIP objective — no post-hoc gate is needed.

    Parameters
    ----------
    current_holdings_df:
        Enriched holdings with columns:
        ``isin, symbol, asset_type, market_value_gbp, bucket_id, quantity``.
        Column ``quantity`` must be present but is not used here.
    target_bucket_weights:
        LP-level bucket targets as percentage weights (sum ≈ 100).
    total_portfolio_gbp:
        Total portfolio value in GBP.
    gilt_candidates_df:
        Pre-filtered gilt candidates for new-position MIP variables (may be ``None``).
        Required columns: ``isin, asset_type, bucket_id, clean_price_gbp``.
        Rows whose ISIN is already in ``current_holdings_df`` are ignored.
    policy:
        Full policy pack dict.  Cost parameters read from
        ``policy["shared_assumption_schema"]["fields"]``.
    gilt_price_lookup_df:
        Optional DataFrame used *only* for gilt lot-rounding price lookups.
        Pass the full gilt ranking (including held gilts) so that conventional
        gilt resizes are lot-rounded correctly.  Falls back to
        ``gilt_candidates_df`` when not supplied.

    Returns
    -------
    SecuritySelectionResult
    """
    if total_portfolio_gbp <= 0 or current_holdings_df.empty:
        empty_df = current_holdings_df.assign(
            proposed_value_gbp=current_holdings_df.get(
                "market_value_gbp", pd.Series(dtype=float)
            )
        ).reindex(
            columns=["isin", "symbol", "bucket_id", "asset_type", "proposed_value_gbp"]
        )
        return SecuritySelectionResult(
            proposed_state_df=empty_df,
            gated_trades=[],
            solver_status="optimal",
            warnings=["Empty portfolio — no trades possible"],
        )

    fields = {
        f["key"]: f["default"]
        for f in policy["shared_assumption_schema"]["fields"]
    }
    commission_gbp: float = float(fields["interactive_investor_trade_fee_gbp"])
    spread_bps_by_class: dict[str, float] = fields["spread_bps_by_friction_class"]
    min_trade_size: float = float(fields.get("minimum_trade_size_gbp", 500.0))
    max_position_pct: float = float(
        policy.get("default_constraints", {}).get("max_single_position_pct", 100.0)
    )
    max_position_gbp: float = max_position_pct / 100.0 * total_portfolio_gbp

    holdings = current_holdings_df.to_dict("records")

    # Preserve original indices when splitting — avoids O(n) list.index() calls later
    nm_indexed  = [(i, h) for i, h in enumerate(holdings) if not _is_mmf(h)]
    mmf_indexed = [(i, h) for i, h in enumerate(holdings) if _is_mmf(h)]
    nm_holdings  = [h for _, h in nm_indexed]
    mmf_holdings = [h for _, h in mmf_indexed]

    n_nm = len(nm_holdings)
    n_mmf = len(mmf_holdings)

    if n_nm == 0:
        # Portfolio is entirely cash — nothing to optimise
        proposed_df = _build_proposed_df(holdings, {})
        return SecuritySelectionResult(
            proposed_state_df=proposed_df,
            gated_trades=[],
            solver_status="optimal",
            warnings=["Portfolio contains only MMF/cash — no trades generated"],
        )

    # ── Candidate gilts (new-position variables) ─────────────────────────────
    # gilt_candidates_df must supply bucket_id and asset_type columns.
    # Candidates whose ISIN already appears in holdings are excluded upstream
    # (in lp_recommendation._filter_gilt_candidates); here we simply consume
    # whatever arrives.
    candidates: list[dict] = []
    if gilt_candidates_df is not None and not gilt_candidates_df.empty:
        for _, row in gilt_candidates_df.iterrows():
            bucket = row.get("bucket_id")
            asset_type = row.get("asset_type")
            price = row.get("clean_price_gbp")
            if bucket and asset_type and pd.notna(price):
                candidates.append(dict(row))
    n_cand = len(candidates)

    # ── Variable layout ──────────────────────────────────────────────────────
    # [x_plus(n_nm), x_minus(n_nm), y_buy(n_nm), y_sell(n_nm),
    #  x_mmf_plus(n_mmf), x_mmf_minus(n_mmf),
    #  x_new(n_cand), y_new(n_cand)]
    S_XP  = 0                              # x_plus  start
    S_XM  = n_nm                           # x_minus start
    S_YB  = 2 * n_nm                       # y_buy   start
    S_YS  = 3 * n_nm                       # y_sell  start
    S_MP  = 4 * n_nm                       # x_mmf_plus  start
    S_MM  = 4 * n_nm + n_mmf               # x_mmf_minus start
    S_XN  = 4 * n_nm + 2 * n_mmf          # x_new   start (candidate buys)
    S_YN  = 4 * n_nm + 2 * n_mmf + n_cand # y_new   start (candidate binary)
    n_vars = 4 * n_nm + 2 * n_mmf + 2 * n_cand

    M_big = total_portfolio_gbp       # tight big-M

    # ── Bounds ───────────────────────────────────────────────────────────────
    lb = np.zeros(n_vars)
    ub = np.full(n_vars, M_big)

    for i, h in enumerate(nm_holdings):
        current_val = float(h["market_value_gbp"])
        # No short selling
        ub[S_XM + i] = current_val
        # Cap buys at the concentration limit: proposed ≤ max_single_position_pct % of portfolio.
        # This prevents the MIP from generating a trade the risk gate will block.
        headroom = max(0.0, max_position_gbp - current_val)
        ub[S_XP + i] = headroom

    ub[S_YB : S_YB + n_nm] = 1.0
    ub[S_YS : S_YS + n_nm] = 1.0

    for k, h in enumerate(mmf_holdings):
        ub[S_MM + k] = float(h["market_value_gbp"])   # no short selling on MMF either

    # Candidates: buy-only, bounded by concentration cap (current holding = 0, so full headroom)
    ub[S_XN : S_XN + n_cand] = max_position_gbp
    ub[S_YN : S_YN + n_cand] = 1.0

    bounds = Bounds(lb=lb, ub=ub)

    # ── Integrality ──────────────────────────────────────────────────────────
    integrality = np.zeros(n_vars)
    integrality[S_YB : S_YB + n_nm] = 1.0
    integrality[S_YS : S_YS + n_nm] = 1.0
    integrality[S_YN : S_YN + n_cand] = 1.0   # y_new: binary

    # ── Objective ────────────────────────────────────────────────────────────
    c = np.zeros(n_vars)
    bucket_current_vals = _bucket_values(holdings)

    for i, h in enumerate(nm_holdings):
        friction_cls = derive_friction_class(h.get("asset_type"))
        spread_bps = spread_bps_by_class.get(friction_cls, 0.0)
        spread_per_gbp = spread_bps / 10_000.0

        # Proportional transaction cost (spread) on both buy and sell
        c[S_XP + i] = spread_per_gbp
        c[S_XM + i] = spread_per_gbp

        # Fixed commission: round-trip assumption for buys, one-way for sells
        c[S_YB + i] = 2.0 * commission_gbp
        c[S_YS + i] = commission_gbp

        # Tiny alignment tiebreaker — rewards moving bucket toward LP target.
        # Scale: commission / (total * 100) so that a 1 % deviation on a
        # commission-sized trade earns exactly 1 commission unit of alignment.
        # This never overrides the friction signal; it only breaks ties.
        bucket = str(h.get("bucket_id", ""))
        target_w = target_bucket_weights.get(bucket, 0.0) / 100.0
        current_w = bucket_current_vals.get(bucket, 0.0) / total_portfolio_gbp
        deviation = target_w - current_w   # + = bucket below target → prefer buy
        tiebreak = commission_gbp / (total_portfolio_gbp * 100.0)
        c[S_XP + i] -= deviation * tiebreak   # reward aligned buys
        c[S_XM + i] += deviation * tiebreak   # penalise selling into under-weight bucket

    # MMF: no fixed cost, negligible spread (classified as cash_and_mmf → 0 bps)
    for k, h in enumerate(mmf_holdings):
        friction_cls = derive_friction_class(h.get("asset_type"))
        spread_bps = spread_bps_by_class.get(friction_cls, 0.0)
        spread_per_gbp = spread_bps / 10_000.0
        c[S_MP + k] = spread_per_gbp
        c[S_MM + k] = spread_per_gbp

    # Candidates: spread + round-trip commission; alignment tiebreaker for underweight buckets
    for j, cand in enumerate(candidates):
        friction_cls = derive_friction_class(cand.get("asset_type"))
        spread_bps = spread_bps_by_class.get(friction_cls, 0.0)
        spread_per_gbp = spread_bps / 10_000.0
        c[S_XN + j] = spread_per_gbp
        c[S_YN + j] = 2.0 * commission_gbp   # round-trip assumption (same as existing buys)

        bucket = str(cand.get("bucket_id", ""))
        target_w = target_bucket_weights.get(bucket, 0.0) / 100.0
        current_w = bucket_current_vals.get(bucket, 0.0) / total_portfolio_gbp
        deviation = target_w - current_w   # positive → bucket underweight → reward buying
        tiebreak = commission_gbp / (total_portfolio_gbp * 100.0)
        c[S_XN + j] -= deviation * tiebreak

    # ── Constraints ──────────────────────────────────────────────────────────
    constraints: list[LinearConstraint] = []

    # 1. Cash balance: Σ(x_plus − x_minus) + Σ_mmf(x_mmf_plus − x_mmf_minus) + Σ_new(x_new) = 0
    #    Candidate buys (x_new) consume cash — same sign as x_plus for existing holdings.
    A_cash = np.zeros((1, n_vars))
    A_cash[0, S_XP : S_XP + n_nm] = 1.0
    A_cash[0, S_XM : S_XM + n_nm] = -1.0
    A_cash[0, S_MP : S_MP + n_mmf] = 1.0
    A_cash[0, S_MM : S_MM + n_mmf] = -1.0
    A_cash[0, S_XN : S_XN + n_cand] = 1.0   # ← candidate buys consume cash
    constraints.append(LinearConstraint(A_cash, lb=0.0, ub=0.0))

    # 2. Per non-MMF holding: big-M, no-simultaneous, minimum trade
    #    5 rows per holding
    n_holding_rows = 5 * n_nm
    A_h = np.zeros((n_holding_rows, n_vars))
    lb_h = np.full(n_holding_rows, -np.inf)
    ub_h = np.zeros(n_holding_rows)
    r = 0
    for i in range(n_nm):
        # big-M buy:  x_plus[i] − M · y_buy[i] ≤ 0
        A_h[r, S_XP + i] = 1.0
        A_h[r, S_YB + i] = -M_big
        r += 1
        # big-M sell:  x_minus[i] − M · y_sell[i] ≤ 0
        A_h[r, S_XM + i] = 1.0
        A_h[r, S_YS + i] = -M_big
        r += 1
        # no-simultaneous:  y_buy[i] + y_sell[i] ≤ 1
        A_h[r, S_YB + i] = 1.0
        A_h[r, S_YS + i] = 1.0
        ub_h[r] = 1.0
        r += 1
        # min trade buy:  min_trade · y_buy[i] − x_plus[i] ≤ 0
        A_h[r, S_XP + i] = -1.0
        A_h[r, S_YB + i] = min_trade_size
        r += 1
        # min trade sell:  min_trade · y_sell[i] − x_minus[i] ≤ 0
        A_h[r, S_XM + i] = -1.0
        A_h[r, S_YS + i] = min_trade_size
        r += 1

    constraints.append(LinearConstraint(A_h, lb=lb_h, ub=ub_h))

    # 2b. Candidate big-M and minimum-trade constraints (2 rows per candidate)
    if n_cand > 0:
        A_c = np.zeros((2 * n_cand, n_vars))
        lb_c = np.full(2 * n_cand, -np.inf)
        ub_c = np.zeros(2 * n_cand)
        rc = 0
        for j in range(n_cand):
            # big-M upper:  x_new[j] − M · y_new[j] ≤ 0
            A_c[rc, S_XN + j] = 1.0
            A_c[rc, S_YN + j] = -M_big
            rc += 1
            # min-trade lower:  min_trade · y_new[j] − x_new[j] ≤ 0
            A_c[rc, S_XN + j] = -1.0
            A_c[rc, S_YN + j] = min_trade_size
            rc += 1
        constraints.append(LinearConstraint(A_c, lb=lb_c, ub=ub_c))

    # 3. Bucket weight targets (within ±epsilon of LP target)
    epsilon = _BUCKET_EPSILON_PCT / 100.0 * total_portfolio_gbp
    warn_msgs: list[str] = []

    for bucket_id, target_pct in target_bucket_weights.items():
        target_val = target_pct / 100.0 * total_portfolio_gbp
        current_val = bucket_current_vals.get(bucket_id, 0.0)
        required_delta = target_val - current_val

        nm_in_bucket   = [i for i, h in enumerate(nm_holdings)  if h.get("bucket_id") == bucket_id]
        mmf_in_bucket  = [k for k, h in enumerate(mmf_holdings) if h.get("bucket_id") == bucket_id]
        cand_in_bucket = [j for j, c in enumerate(candidates)   if c.get("bucket_id") == bucket_id]

        if not nm_in_bucket and not mmf_in_bucket and not cand_in_bucket:
            # Completely empty bucket with no candidates — warn when LP allocates to it.
            if abs(required_delta) > epsilon:
                warn_msgs.append(
                    f"Bucket '{bucket_id}' has a target of {target_val:.0f} GBP "
                    f"but no current holdings — constraint skipped"
                )
            continue

        if not nm_in_bucket and not cand_in_bucket:
            # MMF-only bucket.  MMF level is determined by the cash-balance identity
            # post-solve (mmf_net_delta = -Σ nm_delta); adding an explicit constraint
            # here would conflict with non-MMF bucket constraints when LP routes money
            # through empty buckets.  Skip and let cash balance handle it.
            continue

        # Constrain the net delta of non-MMF holdings and candidate buys in this bucket.
        # MMF variables are intentionally excluded: they are not in gated_trades and
        # their proposed value is set via the cash-balance identity after the solve.
        A_bkt = np.zeros((1, n_vars))
        for i in nm_in_bucket:
            A_bkt[0, S_XP + i] = 1.0
            A_bkt[0, S_XM + i] = -1.0
        for j in cand_in_bucket:
            A_bkt[0, S_XN + j] = 1.0   # candidate buys increase bucket value

        constraints.append(LinearConstraint(
            A_bkt,
            lb=required_delta - epsilon,
            ub=required_delta + epsilon,
        ))

    # ── Solve ─────────────────────────────────────────────────────────────────
    res = milp(c, constraints=constraints, integrality=integrality, bounds=bounds)

    if not res.success:
        # Retry: known scipy presolve bug can misclassify feasible as infeasible
        res = milp(
            c, constraints=constraints, integrality=integrality, bounds=bounds,
            options={"presolve": False},
        )

    if not res.success:
        status = "infeasible" if res.status == 2 else "error"
        warn_msgs.append(
            f"MIP solver returned status {res.status}: {res.message}. "
            "Proposed state reverted to current holdings."
        )
        logger.warning("security_selection MIP failed: %s", res.message)
        return SecuritySelectionResult(
            proposed_state_df=_build_proposed_df(holdings, {}),
            gated_trades=[],
            solver_status=status,
            warnings=warn_msgs,
        )

    x = res.x

    # ── Parse solution ────────────────────────────────────────────────────────
    proposed_vals: dict[int, float] = {}   # index in `holdings` → proposed_value_gbp
    gated_trades: list[GatedTrade] = []
    total_rounding_residual = 0.0
    nm_delta_total = 0.0  # accumulated non-MMF net delta; used to set MMF value below

    # Use the full gilt ranking for price lookups when available, so that
    # conventional gilt resizes are lot-rounded even when gilt_candidates_df
    # only contains unowned switch candidates.
    gilt_prices = _extract_gilt_prices(
        gilt_price_lookup_df if gilt_price_lookup_df is not None else gilt_candidates_df
    )

    for i, (orig_idx, h) in enumerate(nm_indexed):
        current_val = float(h["market_value_gbp"])
        delta = float(x[S_XP + i]) - float(x[S_XM + i])

        # Gilt lot rounding (conventional gilts only)
        asset_type = h.get("asset_type")
        executable_delta = delta
        if asset_type == "gilt_conventional" and abs(delta) >= _TRADE_TOL_GBP:
            price = gilt_prices.get(str(h.get("isin", "")))
            if price is not None:
                nom_delta = delta / price * 100.0
                rounded_nom = round_nominal_conservative(nom_delta)
                exec_delta = rounded_nom * price / 100.0
                total_rounding_residual += delta - exec_delta
                executable_delta = exec_delta

        nm_delta_total += executable_delta
        proposed_val = max(0.0, current_val + executable_delta)
        proposed_vals[orig_idx] = round(proposed_val, 2)

        if abs(executable_delta) < _TRADE_TOL_GBP:
            continue

        friction_cls = derive_friction_class(asset_type)
        spread_bps = spread_bps_by_class.get(friction_cls, 0.0)
        spread_cost = spread_bps / 10_000.0 * abs(executable_delta)
        is_buy = executable_delta > 0
        commission = 2.0 * commission_gbp if is_buy else commission_gbp

        trade = Trade(
            isin=h.get("isin"),
            symbol=h.get("symbol"),
            bucket_id=str(h.get("bucket_id", "")),
            asset_type=asset_type,
            is_new_position=False,
            current_value_gbp=current_val,
            target_value_gbp=round(proposed_val, 2),
            delta_value_gbp=round(executable_delta, 2),
        )
        gated_trades.append(GatedTrade(
            trade=trade,
            friction_class=friction_cls,
            commission_gbp=round(commission, 4),
            spread_cost_gbp=round(spread_cost, 4),
            stamp_duty_gbp=0.0,
            total_friction_gbp=round(commission + spread_cost, 4),
            yield_improvement_bps=None,
            break_even_months=None,
            gate_outcome="green",
            gate_note="MIP-selected trade — friction-viable by construction",
        ))

    # ── Parse new-position candidate trades ───────────────────────────────────
    new_position_rows: list[dict] = []
    for j, cand in enumerate(candidates):
        raw_delta = float(x[S_XN + j])
        if raw_delta < _TRADE_TOL_GBP:
            continue

        asset_type = cand.get("asset_type")
        executable_delta = raw_delta

        # Gilt lot-rounding for conventional gilts
        if asset_type == "gilt_conventional":
            price = cand.get("clean_price_gbp")
            if price is not None and pd.notna(price) and float(price) > 0:
                nom_delta = raw_delta / float(price) * 100.0
                rounded_nom = round_nominal_conservative(nom_delta)
                exec_delta = rounded_nom * float(price) / 100.0
                total_rounding_residual += raw_delta - exec_delta
                executable_delta = exec_delta

        if executable_delta < _TRADE_TOL_GBP:
            continue

        nm_delta_total += executable_delta
        proposed_val = round(executable_delta, 2)

        friction_cls = derive_friction_class(asset_type)
        spread_bps = spread_bps_by_class.get(friction_cls, 0.0)
        spread_cost = spread_bps / 10_000.0 * executable_delta
        commission = 2.0 * commission_gbp   # round-trip for new positions

        isin_str   = str(cand.get("isin", ""))
        symbol_str = str(cand.get("tidm") or cand.get("symbol", ""))
        bucket_str = str(cand.get("bucket_id", ""))

        trade = Trade(
            isin=isin_str,
            symbol=symbol_str,
            bucket_id=bucket_str,
            asset_type=asset_type,
            is_new_position=True,
            current_value_gbp=0.0,
            target_value_gbp=proposed_val,
            delta_value_gbp=proposed_val,
        )
        gated_trades.append(GatedTrade(
            trade=trade,
            friction_class=friction_cls,
            commission_gbp=round(commission, 4),
            spread_cost_gbp=round(spread_cost, 4),
            stamp_duty_gbp=0.0,
            total_friction_gbp=round(commission + spread_cost, 4),
            yield_improvement_bps=None,
            break_even_months=None,
            gate_outcome="green",
            gate_note="MIP-selected new position — friction-viable by construction",
        ))
        new_position_rows.append({
            "isin": isin_str,
            "symbol": symbol_str,
            "bucket_id": bucket_str,
            "asset_type": asset_type,
            "proposed_value_gbp": proposed_val,
        })

    # MMF receives the net proceeds from all non-MMF trades plus gilt lot-rounding residual
    mmf_net_delta = -nm_delta_total + total_rounding_residual
    if n_mmf > 0:
        mmf_total_current = sum(float(h["market_value_gbp"]) for h in mmf_holdings)
        for orig_idx, h in mmf_indexed:
            current_val = float(h["market_value_gbp"])
            share = (current_val / mmf_total_current) if mmf_total_current > 0 else (1.0 / n_mmf)
            proposed_vals[orig_idx] = round(max(0.0, current_val + mmf_net_delta * share), 2)
    # (if n_mmf == 0, rounding residual becomes a small cash discrepancy — warn)
    elif abs(total_rounding_residual) >= 0.01:
        warn_msgs.append(
            f"Gilt lot-rounding residual of £{total_rounding_residual:.2f} "
            "could not be routed to MMF (no liquidity_reserve holding found)"
        )

    proposed_df = _build_proposed_df(holdings, proposed_vals)
    if new_position_rows:
        proposed_df = pd.concat(
            [proposed_df, pd.DataFrame(new_position_rows)],
            ignore_index=True,
        )
    return SecuritySelectionResult(
        proposed_state_df=proposed_df,
        gated_trades=gated_trades,
        solver_status="optimal",
        warnings=warn_msgs,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _is_mmf(h: dict) -> bool:
    return (
        h.get("asset_type") in _MMF_ASSET_TYPES
        or h.get("bucket_id") == _LIQUIDITY_BUCKET
    )


def _bucket_values(holdings: list[dict]) -> dict[str, float]:
    result: dict[str, float] = {}
    for h in holdings:
        bid = str(h.get("bucket_id", ""))
        result[bid] = result.get(bid, 0.0) + float(h["market_value_gbp"])
    return result


def _extract_gilt_prices(
    gilt_candidates_df: pd.DataFrame | None,
) -> dict[str, float]:
    """Return isin → clean_price_gbp from gilt_candidates_df."""
    if gilt_candidates_df is None or gilt_candidates_df.empty:
        return {}
    result: dict[str, float] = {}
    for _, row in gilt_candidates_df.iterrows():
        isin = row.get("isin")
        price = row.get("clean_price_gbp")
        if isin and pd.notna(price):
            result[str(isin)] = float(price)
    return result


def _build_proposed_df(
    holdings: list[dict],
    proposed_vals: dict[int, float],
) -> pd.DataFrame:
    """Build proposed_state_df from holdings list and index → proposed_value map."""
    rows = []
    for idx, h in enumerate(holdings):
        proposed = proposed_vals.get(idx, float(h["market_value_gbp"]))
        rows.append({
            "isin": h.get("isin"),
            "symbol": h.get("symbol"),
            "bucket_id": h.get("bucket_id"),
            "asset_type": h.get("asset_type"),
            "proposed_value_gbp": round(proposed, 2),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["isin", "symbol", "bucket_id", "asset_type", "proposed_value_gbp"]
    )
