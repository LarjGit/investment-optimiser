---
section: signal-layer
phase: level2
status: complete
date: 2026-05-16
---

## What We Established

### GRY Ranking Signal
The signal reuses the same shared gilt yield engine as the allocation section, so there is only one GRY calculation path in the system. The default headline ranking is the live conventional-gilt universe, not just held positions. Prices come from the daily LSE gilt market snapshot already used by the allocator; DMO reference data provides coupon and maturity metadata.

A ranked conventional-gilt table is always shown on the dashboard as an informational view. The switch banner fires only when the best available comparable conventional gilt beats a currently held comparable conventional gilt by more than a user-configurable threshold. If the portfolio holds no comparable conventional gilts, the ranking remains visible but the switch banner is suppressed.

Index-linked gilts are not mixed into the headline ranking by default. They become comparable only when the user supplies an expected RPI assumption that converts real yield into nominal-equivalent yield.

### Equity Macro Signal
Relative value only: earnings yield of the FTSE 100, derived from the dated BlackRock `ISF` public P/E field, versus the best available comparable conventional-gilt GRY from the ranking. The banner fires when the equity earnings yield falls below the best conventional-gilt GRY. The P/E snapshot is cached and freshness-checked by the field's own `as of` date.

### Yield Curve Shape Signal
Uses the BoE six-maturity curve already fetched daily (`1y`, `2y`, `5y`, `10y`, `20y`, `30y`). Classifies each day as one of four shapes:

- **Normal**: 10y - 2y spread > +10bps
- **Inverted**: 10y - 2y spread < -10bps
- **Flat**: `|10y - 2y| <= 10bps`
- **Humped**: 5y yield > both 2y and 10y yields by >10bps

The shape signal fires only after the classification has been sustained for at least five consecutive business days.

### Duration / Liquidity Signal (Two Separate Alerts)
Two independent alerts, both user-configurable:

- **Duration alert** - fires when portfolio weighted-average modified duration exceeds a ceiling (default 8 years) or falls below a floor (default 1 year).
- **Liquidity concentration alert** - fires when more than X% of portfolio value sits in the 10y+ maturity band (default 40%).

Both thresholds are sidebar knobs. Bond duration comes from the same shared SciPy-based cash-flow engine used for GRY; there is no separate QuantLib dependency in the live design.

### Signal Lifecycle
Signals are managed as an episode log in SQLite:

- On each daily refresh, each signal's condition is evaluated
- If newly true: insert a new `signal_events` row for `(alert_type, scope_key)`
- If still true: update only `last_seen_at`
- If condition clears: set `cleared_at`
- Dashboard reads only rows where `cleared_at IS NULL`; cleared signals disappear immediately with no "resolved" banner
- Full episode history is preserved for the decision log

### Signal Evaluation Timing
Two evaluation modes remain:

1. **Daily refresh** (`refresh.py`) - authoritative evaluation, writes to SQLite signal history
2. **On-demand in-memory** (dashboard) - re-evaluates with current day's cached data when the user adjusts threshold knobs; does not write to signal history

## Decisions Made

- One shared GRY calculator across signalling and allocation; no separate signal-layer maths
- Default GRY ranking is conventional-gilt only; index-linked gilts join only when an RPI assumption is supplied
- GRY signal fires when the best comparable conventional gilt beats a held comparable conventional gilt by the configured threshold
- Ranked gilt table always shows; the switch banner is suppressed when there is no comparable held conventional gilt
- Equity signal = dated FTSE 100 earnings yield versus best conventional-gilt GRY
- Yield curve: four-shape classification from the BoE curve; signal requires 5+ consecutive business days
- Duration and liquidity remain separate alerts, both driven by shared persisted analytics rather than a separate QuantLib path
- Signal lifecycle uses `signal_events` episodes keyed by `(alert_type, scope_key)` with `cleared_at IS NULL` as the active-state rule
- Daily refresh is authoritative and persists history; on-demand dashboard evaluation is in-memory only

## Sub-section Map

- [x] gry-computation - shared GRY engine, common market snapshot, ex-dividend handling, T+1 settlement, SciPy cash-flow approach
- [x] equity-signal-pe-source - reliable PE/earnings yield source for FTSE 100
- [x] signal-state-machine - SQLite episode schema for `signal_events`, active-row rule, module structure for signal evaluation

## Remaining Open Questions

None at decision level
