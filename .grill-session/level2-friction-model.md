---
section: friction-model
phase: level2
status: complete
date: 2026-05-16
---

## What We Established

The friction model is a separate layer from the signal layer. Signals fire purely on market conditions; friction is applied as a filter when evaluating whether to act on a signal. Signals are never silently suppressed by friction — both the opportunity and the friction cost are always surfaced together on the dashboard.

### Friction Cost Components

A round-trip switch (sell existing, buy replacement) incurs three components:

1. **Commission** — £3.99 per leg = £7.98 total (Core/Plus ii plan). £2.99 on Premium = £5.98 total.
2. **Bid-offer spread** — modelled as a configurable estimate per asset class (see table below), applied to the full position size.
3. **Stamp duty** — 0.5% on the buy leg for equities and investment trusts. Zero for gilts (conventional and index-linked), gilt ETFs, and corporate bonds.

Formula:
```
total_friction = (2 × commission) + (spread_bps / 10000 × position_size) + stamp_duty
```

### Bid-Offer Spread Defaults (Knobs Panel)

| Asset class | Default spread |
|---|---|
| Conventional gilts | 5 bps |
| Index-linked gilts | 8 bps |
| Gilt ETFs | 3 bps |
| Corporate bonds | 15 bps |
| Equities / investment trusts | 10 bps |
| Cash / money market | 0 bps |

These are parameterised in the knobs panel and editable by the user. Live spread data is not fetched — free public APIs do not expose retail spread data reliably.

### Friction-class routing

The friction layer does not widen the persisted `asset_type` enum. It derives a separate routing class at evaluation time from the stored `asset_type` plus maintained symbol metadata and overrides.

Routing rules:

- `gilt_conventional` -> Conventional gilts bucket
- `gilt_index_linked` -> Index-linked gilts bucket
- persisted `etf` with explicit gilt-ETF metadata/override -> Gilt ETFs bucket
- any persisted holding with explicit corporate-bond metadata/override -> Corporate bonds bucket
- `mmf` -> Cash / money market bucket
- plain `equity`, `investment_trust`, `reit`, `fund`, unresolved `other`, and persisted `etf` without a more specific override -> Equities / investment trusts bucket

This keeps storage stable while still allowing class-specific friction for instruments such as gilt ETFs and corporate bonds.

### Break-Even Threshold

The tool calculates how many months it takes for the yield improvement to recover the total friction cost:

```
break_even_years = total_friction / (yield_improvement_decimal × position_size)
break_even_months = break_even_years × 12
```

A configurable **expected hold period** (default: 2 years / 24 months) is set in the knobs panel. This represents how long the user expects to hold the replacement instrument. Two years is conservative relative to the 5-year drawdown window.

### Trade Gate Output

The gate does not produce a binary yes/no at the signal-display layer. It produces the break-even period in months with colour coding:

- **Green** — break-even < 12 months (clearly worth it)
- **Amber** — break-even 12–24 months (marginal; within but close to the expected hold horizon)
- **Red** — break-even > 24 months (not recommended)

Thresholds are derived from the expected hold parameter: green = < 50% of hold, amber = 50–100%, red = > 100%.

For system-generated portfolio recommendations, the gate is authoritative when building the executable result:

- **Green** - include the trade in the executable recommendation
- **Amber** - include the trade, but mark it as marginal in the recommendation and dashboard
- **Red** - exclude the trade from the executable recommendation and surface the blocked reason explicitly

When a red trade is excluded, the system keeps the current position unchanged if the blocked action was a switch out of an existing holding. If the blocked action was deployment of free cash, the blocked amount remains in MMF or cash rather than being forced into the target instrument.

Dashboard display example:
> "T26 yields 40bps more than TG28 — switch recovers costs in **4 months** ✓"
> "T26 yields 8bps more than TG28 — switch recovers costs in **22 months** ⚠️ (marginal)"
> "T26 yields 3bps more than TG28 — switch recovers costs in **31 months** ✗"

### Near-Maturity Edge Case

No special friction logic is needed for holdings close to maturity. The break-even formula handles it correctly: a gilt with 6 months remaining can only deliver yield improvement for 6 months, so the break-even period will exceed the expected hold threshold and the gate will correctly flag it as not recommended.

An additional plain-English note is shown in the dashboard whenever a holding is within 12 months of maturity: *"Matures in N months — redemption proceeds available for reinvestment."* This surfaces the upcoming cash event without altering the friction logic.

## Decisions Made

- Friction = commission (both legs) + spread (by asset class, parameterised) + stamp duty (equities only)
- Spread modelled as configurable defaults per asset class; not fetched live
- Friction routing is derived from stored `asset_type` plus maintained metadata/overrides; v1 does not expand the persisted enum just to support spread buckets
- Expected hold default: 2 years, editable in knobs panel
- Trade gate output: break-even in months with green/amber/red colouring; for executable recommendations green flows through, amber stays with a warning, red is blocked
- Signal and friction layers are strictly separated; signals always surface, friction annotates them
- Near-maturity holdings handled by break-even maths; dashboard adds a plain-English maturity note at < 12 months

## Remaining Open Questions

None
