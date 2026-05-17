---
section: allocation-engine
subsection: optimizer-algorithm
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

### Scope

This sub-section implements the same authoritative **whole-portfolio, hierarchical, asset-agnostic allocator** established at Level 2:

- A **top layer** allocates capital across active sleeves or asset buckets relative to a strategic baseline policy
- Each **sleeve module** then implements its allocated budget using sleeve-specific logic
- Asset classes may exist in the portfolio model before they are actively optimizable
- A sleeve that lacks a credible model can still be tracked, bounded, and carried, but must not pretend to produce high-confidence optimized weights

This keeps the system honest: the engine can reason about the whole portfolio without forcing all asset classes into one fake common return model.

### Solver family

Use a **continuous linear-programming core** for v1:

- `scipy.optimize.linprog`
- `method='highs'`
- Keep `presolve=True`
- On any `status=3` unbounded result where infeasibility is plausible, re-run once with `presolve=False` to disambiguate, following SciPy guidance

Do **not** use SLSQP for the core allocator. Do **not** use MILP in v1. Integer lot sizes and fixed dealing fees stay outside the main optimizer.

This choice fits the desired shape of the problem:

- linear score objective
- linear budget constraints
- linear concentration and tilt bounds
- linear turnover budgets
- linear scenario floor constraints

It also preserves good diagnostics: slacks, marginals, and infeasible/unbounded status codes are all directly available from HiGHS.

### Top-layer decision variables

The top layer works in **portfolio weights**, not pounds. Let:

- `w_base` = versioned strategic baseline weight vector
- `w_cur` = current live portfolio weights
- `w` = target post-trade portfolio weights chosen by the top layer

The active decision vector is `w`, subject to:

- full investment: `sum(w) = 1`
- long-only for v1: `w_i >= 0`
- per-sleeve or per-bucket upper/lower bounds
- confidence-adjusted tilt bounds around `w_base`
- regime-adjusted turnover budget versus `w_cur`

The top layer allocates only across **active sleeves / asset buckets**. Lower-level sleeves expand those allocations into actual instruments.

### Baseline-anchored policy model

The top layer is anchored to a **user-authored, versioned strategic baseline allocation**, not to current holdings.

Current holdings matter for:

- measuring drift
- turnover control
- friction estimation
- staging migration over time

But current holdings are **implementation state**, not policy truth.

The top layer therefore does not search freely over the entire simplex. It applies **bounded tilts around baseline**. This is the main defense against overreaction to noisy signals.

### Objective construction

The top-layer objective is not a fake precise expected-return forecast. It is a **normalized attractiveness / conviction score** for each active sleeve.

Let:

- `s_base` = base attractiveness score vector from deterministic scoring policy
- `c_i in [0,1]` = sleeve confidence
- `s_eff_i` = confidence-adjusted score used in the LP

Confidence affects the objective **secondarily**:

- `s_eff_i = c_i * s_base_i`

So low confidence weakens a sleeve's score, but does not by itself eliminate the sleeve.

Primary control happens through bounds, not score scaling.

The LP is solved as a maximization of total weighted attractiveness, implemented in SciPy as minimizing `-s_eff^T w`.

### Confidence control law

Low confidence must not just appear as a label. It changes allocation freedom.

For each sleeve `i`, define a baseline tilt band:

- `w_base_i - down_i <= w_i <= w_base_i + up_i`

Then apply confidence tightening:

- lower confidence -> narrower allowable tilt band
- higher confidence -> wider allowable tilt band

This is the **primary** confidence mechanism.

The full rule is:

1. Tighten the sleeve's allowable tilt band around baseline according to confidence
2. Also scale down the sleeve's attractiveness score according to confidence

This is asymmetric by design:

- bounds prevent oversized bets when confidence is weak
- score scaling still lets a mildly attractive low-confidence sleeve participate

### Regime-aware turnover budgeting

The allocator must support staged convergence, not assume one-shot reshaping.

Impose an explicit turnover or active-change budget versus current holdings:

- conservative in `constructive` and `normal`
- wider in `cautious`
- wider again in `defensive`
- near-unbounded only in `capital-preservation`

This budget is a **hard top-layer constraint**, not merely a preference.

The trade path should be:

1. use cash flows first
2. then low-friction reshuffles
3. then discretionary sells if still needed

Cash flows include:

- new contributions
- withdrawals
- coupons
- dividends
- maturities
- existing cash / MMF balances

New cash is allocated at the **top layer first**, then passed down into sleeves.

### Robust scenario policy

The top layer must not optimize only for one base case.

Use a small named scenario set, such as:

- Base
- Bullish rates / risk-on variant
- Mild adverse
- Severe adverse

The robustness design is **hybrid**:

1. The main objective is a weighted multi-scenario attractiveness objective
2. A small set of adverse scenarios also impose **hard acceptability floors**

This keeps the model linear and auditable while preventing the optimizer from buying a high-score portfolio that fails obvious downside tests.

Scenario floors are explicit linear constraints of the form:

- `scenario_return_k(w) >= floor_k`

or any equivalent linearized acceptability metric used by the top layer.

If these floors conflict with policy bounds or turnover limits, the optimizer should fail visibly rather than silently relaxing them.

### Layer responsibilities for robustness

Robustness exists at two levels:

1. **Top layer**
   - enforces portfolio-wide scenario floors
   - enforces regime-aware pacing
   - arbitrates capital across sleeves

2. **Sleeve layer**
   - enforces sleeve-local stress checks only when that sleeve has a credible local model

For this project:

- the fixed-income sleeve **should** enforce sleeve-level robustness because gilts and MMF can be stress-tested analytically
- a weakly modelled sleeve must **not** invent precise local robustness
- instead, a weak sleeve returns lower confidence and tighter bounds upstream

### Sleeve contract

Each sleeve must expose a standard deterministic interface.

**Inputs**

- allocated budget from top layer
- active local constraints
- current sleeve holdings
- scenario set relevant to that sleeve
- any sleeve-specific assumptions or knobs

**Outputs**

- target sleeve weights and/or explicit trades
- implementation metrics
- explanation payload

The explanation payload is mandatory. Each sleeve must return at least:

- local confidence
- scenario pass/fail summary
- binding constraints
- degraded-mode flags
- turnover used
- cash left unallocated
- short explanation string

Without this payload, the top layer cannot tell the difference between:

- a genuinely strong local result
- a merely feasible but degraded solve

### Conflict resolution between layers

The **top layer is authoritative**.

A sleeve is not allowed to silently force upstream relaxation of:

- portfolio-wide scenario floors
- top-level pacing limits
- top-level budget limits
- top-level tilt bands

If a sleeve cannot produce a satisfactory locally robust result inside the envelope it was given, it must return:

- a degraded status
- diagnostics
- small named fallback options where possible

Named fallbacks should be limited to simple, auditable choices such as:

- `feasible-conservative`
- `hold-current`
- `cash-remainder`

The top layer may then:

- accept the degraded sleeve result
- reallocate away from that sleeve
- explicitly rerun under a user-visible relaxation policy

No hidden constraint relaxation is permitted.

### Post-solve trade construction

Lot-size rounding is **not** part of the LP.

Workflow:

1. solve continuous LP in weights
2. convert target sleeve allocations into instrument-level continuous targets
3. construct trade list against current holdings
4. round gilt trades to nearest `GBP 100` nominal
5. leave residual cash in MMF/cash
6. apply friction gate after trade construction

Do not enforce minimum trade size or fixed dealing fee inside the LP. Those belong in the post-solve implementation layer.

### Failure handling

Failure behavior must be explicit and user-visible.

- True infeasibility fails loudly
- Show which constraints were active and the smallest obvious relaxation candidates
- If a sleeve universe becomes empty under local filters, return the sleeve fallback rather than crashing the entire portfolio engine
- If a sleeve is temporarily non-optimizable, freeze current sleeve holdings for that cycle and route new deployable cash elsewhere where valid
- One sleeve failure must not crash the entire engine

If no eligible instrument remains inside a sleeve after filters, the preferred fallback is conservative cash / MMF parking with a visible warning.

### Audit and replay

Every solve must persist a full decision snapshot sufficient for replay.

The authoritative persisted home for that replay payload is `allocation_runs` in the persistence layer: indexed metadata columns capture the solve identity, while `snapshot_json` stores the full structured replay record.

Minimum payload:

- policy version
- baseline allocation
- current holdings
- sleeve confidence values
- regime state
- cash-flow inputs
- active constraints and bounds
- confidence-adjusted score coefficients
- scenario floors and scenario results
- solver status and message
- binding constraints / marginals where available
- chosen fallback path, if any
- explanation payload passed through from sleeves

Auditability is a first-class requirement, not an optional reporting layer.

## Decisions Made

- `optimizer-algorithm` uses the authoritative hierarchical, whole-portfolio, asset-agnostic design established for the allocation engine
- LP core: `scipy.optimize.linprog(method='highs')`; not SLSQP, not MILP for v1
- Baseline policy is versioned and user-authored; current holdings are implementation state, not policy truth
- Top-layer objective uses normalized deterministic sleeve scores, not fake precise cross-asset expected returns
- Low confidence acts primarily by tightening tilt bounds and secondarily by scaling down sleeve scores
- Regime-aware turnover budgets are hard constraints and widen as conditions become more defensive
- Robustness is hybrid: weighted multi-scenario objective plus explicit hard adverse-scenario floors
- Top layer enforces portfolio-wide robustness; sleeves enforce local robustness only where they have credible local models
- Fixed-income sleeve gets local stress checks; weakly modelled sleeves report low confidence instead of fake precision
- Sleeve contract requires diagnostics payload, not just target weights/trades
- Top layer is authoritative in conflicts; sleeves return degraded-status fallbacks rather than silently relaxing upstream constraints
- Lot rounding and friction gating happen after the LP solve in trade construction
- Every solve writes a replayable audit snapshot to `allocation_runs`

## Remaining Open Questions

None
