## Problem

The security-level MIP in `src/investment_optimiser/security_selection.py` can only recommend changes to holdings **already in the portfolio**. It cannot buy a gilt you don't currently own. This means:

1. The **Signals tab** can identify a superior gilt in the same bracket (e.g. "Switch from T26 to T28 — yield gap 18 bps, break-even 7 months") but the **Scenarios tab recommendation never actions it**, because the target gilt is not in the variable set.
2. Trade count is capped by what you hold — typically 3 trades because there are only 3 mutable non-MMF buckets with existing positions.
3. An **empty gilt bucket** (target > 0 in baseline, no current holdings) causes the bucket constraint to be silently skipped, so the optimiser never moves money into that bucket.

---

## Evidence in the code

### `security_selection.py` — all variables are over existing holdings only

```python
# security_selection.py:158
holdings = current_holdings_df.to_dict("records")
```

The MIP variable arrays `x_plus[i]`, `x_minus[i]`, `y_buy[i]`, `y_sell[i]` are created with `i` ranging over `current_holdings_df` only. No path adds variables for candidate gilts not yet held.

Every generated trade has this hardcoded (line 408):
```python
is_new_position=False,
```

### `gilt_candidates_df` is passed in but ignored for selection

`build_lp_recommendation` passes `gilt_ranking_df` into `select_trades` as `gilt_candidates_df` (lp_recommendation.py:94), but inside `select_trades` it is only used for one thing — gilt lot-rounding price lookup:

```python
# security_selection.py:372
gilt_prices = _extract_gilt_prices(gilt_candidates_df)
```

The candidate universe has GRY, maturity, ISIN, coupon, clean price — everything needed to add new positions — but none of it is fed into the MIP.

### Empty bucket constraint is silently skipped

```python
# security_selection.py:310-317
if not nm_in_bucket and not mmf_in_bucket:
    if abs(required_delta) > epsilon:
        warn_msgs.append(f"Bucket '{bucket_id}' has a target ...")
    continue
```

If you have no holdings in a bucket the LP says should be funded, the MIP skips the constraint and makes no trades toward it.

### Signals tab switch table (app.py ~1115)

The switch table correctly identifies the best available gilt in the same **bracket** (ultra-short / short / medium / long) that is not held:

```python
candidates = df[
    (df["_bracket"] == bracket) & (~df["held"]) & df["gry_pct"].notna()
]
best_row = candidates.loc[candidates["gry_pct"].idxmax()]
gap_bps = (float(best_row["gry_pct"]) - held_gry) * 10_000
```

It computes yield gap and break-even months using `break_even_estimate()` from `friction_gate.py`. This is exactly the information the MIP needs to decide whether a switch is worth executing — but the two subsystems are not connected.

---

## Desired behaviour

When the MIP runs, it should be able to:

1. **Switch gilts within a bucket**: sell a held gilt and buy a better-yielding unowned gilt in the same bucket — not just resize the existing holding.
2. **Open a new gilt position in a bucket where you hold nothing**: if the LP says a bucket should be 20% of portfolio and you hold zero there, recommend buying the top-ranked gilt for that bucket.
3. **Surface new-position trades distinctly** in the recommendation table (e.g. labelled "New position" rather than "Increase").

---

## Architecture

### How bucket_id is derived for candidate gilts

`bucket_assignment.py` (confirmed by `tests/test_bucket_assignment.py`) derives `bucket_id` from `asset_type` and `maturity_years`:

| Condition | bucket_id |
|---|---|
| `gilt_conventional`, maturity < 5y | `short_duration_nominal_gilts` |
| `gilt_conventional`, maturity >= 5y | `long_duration_nominal_gilts` |
| `gilt_index_linked` | `index_linked_gilts` |

The `gilt_candidates_df` already has `maturity_date` and `instrument_type` ("Conventional" / "Index-linked"), so `bucket_id` can be derived at the point candidates are prepared, before entering `select_trades`.

### Data pipeline is already in place

```
build_lp_recommendation(gilt_ranking_df=...)
  └─ select_trades(gilt_candidates_df=gilt_ranking_df)   <- data is here already
```

`gilt_ranking_df` / `gilt_candidates_df` contains: `isin`, `tidm`, `instrument_name`, `instrument_type`, `maturity_date`, `coupon_pct`, `clean_price_gbp`, `gry_pct`, `modified_duration_years`.

---

## Proposed implementation

### Step 1 — Enrich candidates with `bucket_id` before `select_trades`

In `build_lp_recommendation` (or in `build_gilt_candidate_universe`), call `assign_bucket` / `bucket_assignment.py` to add a `bucket_id` column to the candidate DataFrame. Filter out candidates with no price or no GRY. Filter out candidates whose ISIN is already in `current_holdings_df` (they are existing holdings, not new positions).

### Step 2 — Add new-position variables to the MIP

In `select_trades`, introduce a new group of variables for each unowned candidate gilt:

```
x_new[j]   >= 0      amount to buy of candidate j
y_new[j]   in {0,1}  1 if candidate j is bought
```

Bounds:
- `x_new[j]` lower bound: 0
- `x_new[j]` upper bound: `max_position_gbp` (current value is 0, so full headroom)
- `y_new[j]`: binary {0, 1}

Big-M constraints (same pattern as existing holdings):
- `x_new[j] <= M * y_new[j]`
- `x_new[j] >= min_trade_size * y_new[j]`

Objective contribution per candidate:
```
spread_cost * x_new[j] + 2 * commission * y_new[j]   (round-trip assumption, same as existing buys)
- alignment_tiebreak * x_new[j]                       (if bucket is underweight)
```

### Step 3 — Include new positions in bucket and cash-balance constraints

**Cash balance**: add `x_new[j]` with coefficient +1 (buying consumes cash, offset by MMF sell or existing gilt sell).

**Bucket constraint**: for bucket `b`, add `x_new[j]` for all candidates where `candidate_bucket_id == b` to the net-delta constraint.

### Step 4 — Parse new-position solution variables

After solve, for each candidate `j` where `x_new[j] > _TRADE_TOL_GBP`:

```python
trade = Trade(
    isin=candidate["isin"],
    symbol=candidate["tidm"],
    bucket_id=candidate_bucket_id,
    asset_type="gilt_conventional",   # or gilt_index_linked
    is_new_position=True,             # distinguishes from resize
    current_value_gbp=0.0,
    target_value_gbp=round(x_new[j], 2),
    delta_value_gbp=round(x_new[j], 2),
)
```

Apply gilt lot-rounding using `clean_price_gbp` from the candidate row (same logic as existing holdings at security_selection.py:381-388).

### Step 5 — Candidate filtering (keep MIP tractable)

Do not add the entire gilt universe (~50 gilts) as free variables — this bloats the MIP unnecessarily. Restrict to a small, high-quality candidate set per bucket.

**Preferred approach (signal-aligned)**: only add candidates where `gry_pct > best_held_gry_in_bucket + switch_threshold_pct`, i.e. only gilts the Signals tab would already flag as switch opportunities. This directly connects the two subsystems and avoids the MIP being nudged toward marginally better gilts that don't pass the friction gate anyway.

The switch threshold is in policy: look for `gry_switch_threshold_pct` or equivalent in `policy["shared_assumption_schema"]["fields"]`.

**Fallback**: if a bucket has no held gilts at all (empty bucket case), include the top-N gilts by GRY for that bucket (N=3 is sufficient).

---

## Files to change

| File | Change |
|---|---|
| `src/investment_optimiser/security_selection.py` | Main MIP: add new-position variable group, extend cash-balance + bucket constraints, parse solution, lot-round new positions |
| `src/investment_optimiser/gilt_signals.py` or `src/investment_optimiser/bucket_assignment.py` | Add `bucket_id` derivation to `build_gilt_candidate_universe` output (or do it in lp_recommendation.py) |
| `src/investment_optimiser/lp_recommendation.py` | Pre-filter candidates before passing to `select_trades`; enrich with `bucket_id` |
| `src/investment_optimiser/trade_construction.py` | Verify `is_new_position=True` is handled downstream (risk gate, display) |
| `app.py` | Ensure recommendation table renders new-position trades with a distinct label |
| `tests/test_security_selection.py` | New tests: new position opened when bucket empty; switch candidate chosen over held gilt; MIP ignores sub-threshold candidates |

---

## Guardrails / constraints to preserve

- **No short-selling**: `x_new[j] >= 0` only (lower-bound = 0).
- **Concentration limit**: `x_new[j] <= max_position_gbp` (same cap already applied to existing buys at security_selection.py:202).
- **Cash balance**: net zero — new gilt buys must be funded by MMF drawdown or existing gilt sell (the cash-balance constraint already enforces this; adding `x_new[j]` to it maintains the invariant).
- **Bucket epsilon**: the `+/-_BUCKET_EPSILON_PCT` tolerance on bucket constraints remains unchanged.
- **Friction viability**: the MIP objective already prices in commission + spread for new positions. The risk gate runs afterward and can still veto on concentration / maturity / liquidity grounds.
- **MMF is not a candidate**: only gilt-type assets from `gilt_candidates_df` should be added as new-position variables. MMF rebalancing continues to flow through the cash-balance identity.

---

## Related

- Signals tab switch table: `app.py:_render_gilt_switch_table`, `app.py:_build_switch_rows`
- Break-even calculation: `src/investment_optimiser/friction_gate.py:break_even_estimate`
- Candidate universe: `src/investment_optimiser/gilt_signals.py:build_gilt_candidate_universe`
- Bucket assignment: `src/investment_optimiser/bucket_assignment.py:assign_bucket`
- Empty-bucket handling in old pipeline: `src/investment_optimiser/holdings_translator.py:_deploy_into_empty_bucket` (pre-MIP code; may be useful as reference)
- System design: `docs/system-design.md`
