---
section: allocation-engine
subsection: scenario-engine
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

The scenario engine evaluates two portfolio states under each named deterministic scenario:

- the **current portfolio**
- the **post-friction executable portfolio** derived from the optimizer target after trade construction, blocked-trade handling, friction gating, rounding, and residual-cash handling

The executable portfolio is the main comparison state. The raw optimizer target may be retained as a diagnostic, but it is not the headline scenario portfolio because it may not be reachable in practice on the day.

### Repricing rules by asset type

**Conventional gilts**
- Reprice exactly in every scenario
- Shift the gilt GRY by the scenario delta
- Re-solve clean price from the shocked yield using the existing cash-flow engine
- Do not use duration/convexity approximation in the core path

**Index-linked gilts**
- Reprice exactly on the real-yield path using the same pattern
- If the scenario framework has a credible inflation assumption, include it in the scenario valuation/income view
- If not, keep the holding in totals as `unmodelled_held_flat`

**MMF / cash**
- Capital value stays flat
- Scenario effect is on running yield only

**Other holdings without a credible scenario model**
- Stay in totals at unchanged spot value
- Are labelled `unmodelled_held_flat`
- Are never silently excluded from portfolio totals

This keeps totals complete while making modelling limits explicit.

### Canonical output shape

The engine emits **long-form scenario records** first. It does not calculate directly into the final dashboard table shape.

Minimum record shape:

```text
portfolio_state      # current | executable_recommended
scenario_name        # e.g. Base, -100bps, +50bps, +100bps
holding_id
holding_name
asset_type
bucket_name
current_value_gbp
scenario_value_gbp
pnl_gbp
model_status         # exact | held_flat | unmodelled_held_flat
notes
```

Optional fields may include:

```text
current_yield_pct
scenario_yield_pct
duration_years
trade_block_reason
```

This long-form structure is the authoritative engine output because it is easier to test, audit, and debug.

### Dashboard reshaping

The dashboard reshapes long-form records only at render time:

- aggregate to holding or bucket level as needed
- use `pivot()` when index/column pairs are unique
- use `pivot_table()` if aggregation is needed
- highlight the active scenario column in the UI styling layer, not in engine logic

This keeps calculation and presentation cleanly separated.

### Scenario loop

For each scenario:

1. Select the portfolio state to evaluate (`current` and `executable_recommended`)
2. Iterate holdings
3. Apply the asset-type-specific scenario valuation rule
4. Emit one long-form record per holding
5. Aggregate to bucket and total-portfolio summaries

This supports:

- per-holding P&L
- per-bucket P&L
- total portfolio P&L
- side-by-side current vs executable-recommended comparison

### Output semantics

The main scenario view answers:

> "If this rate scenario happened, how would my portfolio look now, and how would it look if I executed today's realistic recommendation?"

It does not answer:

> "What would happen to a frictionless paper target that I probably cannot fully implement today?"

That distinction is mandatory.

### Disclosure requirements

Every scenario summary must surface modelling coverage:

- portfolio value modelled exactly
- portfolio value held flat
- portfolio value marked `unmodelled_held_flat`

If any unmodelled weight exists, show a visible caveat that part of the portfolio was carried unchanged rather than stress-modelled.

## Decisions Made

- Scenario engine evaluates `current` and `post-friction executable` portfolio states; executable is the headline recommended comparison
- Conventional gilts are repriced exactly under each scenario by shocking yield and re-solving clean price from cash flows
- Index-linked gilts use the same exact repricing pattern on the real-yield path; without credible inflation assumptions they fall back to `unmodelled_held_flat`
- MMF/cash keep capital value flat; only running yield changes by scenario
- Holdings without a credible scenario model stay in totals at unchanged spot value and are labelled `unmodelled_held_flat`
- Canonical engine output is long-form scenario records, not final dashboard table shape
- Dashboard tables are derived later via pandas pivoting/styling
- Scenario output is about realistic implementable post-trade portfolios, not frictionless paper targets
- Scenario summaries must disclose exact-modelled, held-flat, and unmodelled-held-flat coverage

## Remaining Open Questions

None
