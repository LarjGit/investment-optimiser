---
section: allocation-engine
phase: level2
status: complete
date: 2026-05-15
---

## What We Established

### Whole-Portfolio Hierarchical Model

The authoritative architecture is a whole-portfolio, hierarchical allocator rather than a user-set equity sleeve plus a separate bond optimizer. A top layer works across active sleeves or asset buckets relative to a versioned strategic baseline, while sleeve modules implement the allocated budget with sleeve-specific logic. Current holdings matter for turnover, friction, and migration pacing, but they are not the policy anchor.

This keeps the system honest across asset classes. Strongly modelled sleeves, especially fixed income, can take analytically defensible tilts. Weakly modelled sleeves stay bounded and confidence-limited rather than being forced through a fake common expected-return model.

### Objective and Evidence Model

The top layer does not pretend to know precise cross-asset expected returns. It allocates using deterministic attractiveness scores, confidence-adjusted tilt bands around the strategic baseline, and explicit regime-aware turnover limits. Confidence acts primarily through tighter or wider allowable tilts and only secondarily through score scaling.

Within that whole-portfolio framework, the fixed-income sleeve remains the most analytically precise module:

- conventional gilt GRY is computed exactly from the shared cash-flow engine
- index-linked gilts can participate only when the user supplies an expected RPI assumption
- MMF yield is proxied by the BoE base rate

### Candidate Universe

The fixed-income sleeve searches the full live gilt universe rather than only current holdings. Conventional gilts are always in scope; index-linked gilts are brought into ranking and optimisation only when their real yield can be converted using a user-supplied RPI assumption. The daily candidate snapshot comes from the LSE price-explorer API, while coupon and maturity metadata come from the DMO reference layer.

Other sleeves may exist in the top-layer model before they are fully optimisable. A sleeve without a credible instrument-level optimiser can still be carried with baseline bounds, confidence limits, and explicit degraded-mode labelling.

### Constraints

The allocator uses two levels of constraints:

- **Top-layer policy constraints** - full investment, long-only v1, baseline tilt bands, regime-aware turnover budgets, and scenario acceptability floors.
- **Sleeve-local implementation constraints** - for the fixed-income sleeve these include max maturity, max instrument concentration, minimum MMF or cash floor, and minimum short-duration liquidity floor.

When a sleeve cannot satisfy its local constraints cleanly, it must return a visible fallback such as holding current positions or parking residual capital in MMF or cash. It cannot silently relax top-layer policy constraints.

### Output to Trade Recommendations

The allocator first produces continuous target weights, then sleeve-level target holdings, then an executable trade list against the current portfolio. Post-solve rounding, residual cash handling, and the friction gate happen after optimisation. The user sees the executable recommendation, not a frictionless paper target.

### Audit and Replay

Every solver run persists a replayable audit record in the persistence layer's `allocation_runs` table. That stored snapshot is the authoritative record of which baseline, constraints, scores, scenario floors, solver status, and fallback path produced a given recommendation.

### Scenario Analysis

Scenario analysis applies to the full portfolio and compares two states:

- the current portfolio
- the executable recommended portfolio after rounding, blocked-trade handling, and friction gating

Conventional gilts are repriced exactly from the shared cash-flow engine under named deterministic rate shifts. Index-linked gilts use the same path when the inflation assumptions are credible; otherwise they remain visible but explicitly marked as not fully modelled. MMF and cash hold capital value flat while income changes. Other holdings stay in totals with explicit `unmodelled_held_flat` disclosure unless a sleeve has a stronger scenario model.

## Decisions Made

- Whole-portfolio hierarchical allocator anchored to a user-authored strategic baseline; the older two-stage equity-plus-bonds framing is superseded
- Top layer uses deterministic attractiveness scores, confidence-adjusted tilt bands, turnover limits, and scenario floors rather than fake precise cross-asset return forecasts
- Fixed-income sleeve remains analytically strongest: conventional gilt GRY, optional index-linked participation with RPI assumption, and MMF yield from BoE base rate
- Live gilt candidate prices come from the LSE price-explorer API and DMO reference data; candidate scope is not limited to current holdings
- Constraints split into top-layer policy rules and sleeve-local implementation rules
- Output path is target weights to sleeve implementation to executable trade list to friction-gated recommendations
- Every solve persists a replayable audit snapshot in `allocation_runs`
- Scenario analysis compares current versus executable recommended portfolios and discloses where positions are exact-modelled versus held flat
- Named deterministic scenarios remain the v1 scenario framework

## Sub-section Map

- [x] gry-calculation - dirty price, accrued interest, semi-annual coupons, settlement convention, scipy.brentq implementation
- [x] optimizer-algorithm - top-layer LP design, objective construction, constraint formulation, candidate universe fetch, edge cases
- [x] scenario-engine - yield curve shift loop, full reprice per gilt, output table format, side-by-side current vs recommended

## Remaining Open Questions

None
