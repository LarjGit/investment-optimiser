# Implementation Status

Companion to `docs/system-design.md`. Updated 2026-05-23 by code inspection, not by GitHub issue status (issues may lag).

**Scope:** This document tracks the v1 design only. It is a closed snapshot once the gaps listed below are resolved or explicitly deferred. New capabilities beyond the v1 design belong in `docs/system-design.md` first, then in a GitHub issue — not here.

---

## Data Ingestion — Fully implemented

All elements from the design are present in code:

- II CSV normalisation: BOM stripping, totals-row filtering, `II_COLUMN_MAP`, `II_REQUIRED_COLUMNS`, `IngestionError` on missing columns
- `parse_price()`: GBP-prefix strip, pence `/100` conversion, per-row warnings without aborting import
- Asset classification cascade: all 6 steps implemented (symbol overrides → MMF name detection → DMO gilt bridge → non-gilt reference map → name heuristics → `other` fallback)
- Fixed `asset_type` taxonomy persisted; friction-only distinctions derived at runtime
- DMO XML feeds (`D1A` conventional, `D1D` index-linked) with coupon parsing supporting all fraction and decimal formats
- TIDM→ISIN bridge: seeded CSV bootstrap plus monthly LSE refresh, logged separately from DMO reference refresh
- `gilt_reference` schema and full field set
- LSE gilt price refresh
- Yahoo Finance equity/ETF/fund batch (`period="2d"`, `shared._ERRORS` inspection)
- `trailingPE` single-ticker call → `equity_valuation_cache`, default benchmark `SWRD.L`, configurable in policy pack
- BoE 6-point yield curve (1y/2y/5y/10y/20y/30y) + base rate
- Refresh coordinator with process lock, per-source logging, startup auto-refresh and manual dashboard trigger
- Staleness thresholds: >2 trading days = warning, >5 = error

**Note on non-gilt classification (issue #41):** The `non_gilt_reference` refresh is wired into `REFRESH_SOURCE_ORDER` and calls Yahoo Finance per-symbol to classify holdings by type (equity, ETF, investment trust, etc.). Issue #41 questions whether this should be redesigned to enrich from Yahoo in a single portfolio-scoped pass rather than individual calls. The feature works; the method is under review.

---

## Allocation Engine — Core implemented, three design elements absent

### Implemented

- `w_base` / `w_cur` / `w` weight-space formulation
- `scipy.linprog(method='highs')` with `presolve=False` fallback on unbounded result
- `policy_pack_v1.json`: bucket taxonomy, named scenarios, default constraints, shared assumption keys
- Regime-aware turnover limits via `turnover_limit_pct_by_regime[regime_state]`
- Tilt bands: single fixed `baseline_tilt_band_pct` per solve
- Scenario floor hard constraints (`scenario_floor_pct_of_current_value`) encoded as LP inequality rows
- Binding constraints and marginals returned from solver
- Full gilt candidate universe (all LSE-priced gilts, not just holdings)
- IL real GRY: `compute_real_gry()` with Fisher equation, RPI sidebar input, IL gilts join ranking and LP candidate universe when RPI is set
- T+1 settlement via UK business day calendar, ICMA actual/actual accrued interest
- Newton primary / brentq fallback GRY solver; failed solves omitted from cache with warnings
- Holdings-to-trades translation, gilt nominal rounding to GBP100
- Friction gate: commission × 2 + spread by asset class + stamp duty, break-even months, green/amber/red thresholds derived from hold period
- Risk gate: post-trade concentration cap, maturity cap, liquidity floor — each with a plain-English reason
- Executable recommendation rebuilt after gating
- Scenario engine: exact gilt repricing, held-flat equities/other, coverage disclosure
- `allocation_runs` replayable audit payload (JSON blob + indexed scalar columns)
- Narrative explanation, constraint-binding explanations, blocked-trade explanations
- Recommendation change summary (run-to-run allocation delta)
- Cash deployment of existing MMF/liquidity surplus (pro-rata across under-weight buckets)

### Not yet implemented

| Missing element | Where it appears in the design |
|---|---|
| **Confidence tightening tilt bands** | "Confidence acts primarily by tightening tilt bands around baseline." The LP receives a single fixed tilt band; no confidence parameter feeds the solver. |
| **Weighted multi-scenario attractiveness objective** | "Scenario robustness is hybrid: a weighted multi-scenario attractiveness objective + explicit hard floors." The LP has scenario floor *constraints* (hard floors) but no weighted scenario component in the objective function itself. |
| **Cash flows as explicit solver inputs** | "Contributions, withdrawals, coupons, dividends, maturities… deployed first before discretionary sells." The cash allocator handles only the existing MMF/liquidity surplus already in the portfolio. Upcoming coupon receipts, maturities, or new contributions are not tracked or pre-deployed. |

### Risk gate partial gap

The design lists "scenario-loss ceilings" as a typical risk gate check. `risk_gate.py` checks concentration, maturity, and liquidity only. Scenario-loss protection exists but sits in the LP as hard floor constraints earlier in the pipeline — it is not a named explicit veto in the risk gate itself. Functionally the protection is present; architecturally it is not the separate auditable veto layer the design describes.

---

## Signal Layer — Fully implemented, plus one addition beyond design

| Signal area | Status |
|---|---|
| GRY ranking: full gilt universe, same LSE snapshot as allocator, held gilts marked | Implemented |
| Switch banner: fires only when held conventional comparator exists; suppressed with plain-English note otherwise | Implemented |
| IL gilts excluded from ranking when no RPI set; join when RPI is set | Implemented |
| Graceful degradation on missing prices or failed GRY solves | Implemented |
| ERP signal: `1/PE − best_gilt_GRY`, configurable threshold, 5-trading-day stale fallback | Implemented |
| ERP card always visible whether signal is firing, quiet, or stale | Implemented |
| Yield curve: 6-point BoE, 4-state classification (normal/inverted/flat/humped), 5-business-day persistence before firing | Implemented |
| Duration alert: weighted-average modified duration vs configurable floor/ceiling | Implemented |
| Liquidity concentration alert: 10y+ maturity band vs configurable threshold | Implemented |
| Signal episode persistence: `signal_events` open/close lifecycle, partial unique index per `(alert_type, scope_key)` | Implemented |
| `signal_readings` timeseries | Implemented |
| Authoritative writes in refresh job only; dashboard what-if is read-only with respect to persisted history | Implemented |
| **Equity opportunity composite signal** (ERP percentile + valuation percentile + drawdown percentile, EMA trend dampener) | Implemented — **beyond the 4 signal areas in the v1 design** |

**Minor ERP deviation:** The design says the equity macro banner is "suppressed" when data is stale beyond 5 days; the code fires a `"stale"`-state banner instead, with the stale explanation in the card body. The intent (don't false-positive an ERP warning on stale data) is preserved; the UX is a stale warning rather than silence.

**ERP change attribution gap:** The design says the card should surface "which factor moved: gilt GRY rising, equity PE expanding or compressing, or both" when signal state changes. The card shows current values but does not compare to the previous session.

---

## Friction Model — Fully implemented

All cost components, routing by derived friction class, break-even formula, hold-period-derived green/amber/red thresholds, and blocked-cash → MMF/cash behaviour are present.

**Minor gap:** The design says "the dashboard adds a plain-English note when a holding matures within twelve months." No such note is rendered in the holdings table.

---

## Dashboard UX — Mostly implemented, two layout gaps

| Element | Status |
|---|---|
| 4 tabs: Portfolio, Signals, Scenarios, Decision Log | Implemented |
| Firing signal banners above all tabs | Implemented |
| Full sidebar assumption set (all named controls) | Implemented |
| Portfolio tab: KPIs, current vs recommended bar charts, holdings dataframe | Implemented |
| Scenarios tab: summary metrics, comparison table, coverage disclosure | Implemented |
| Decision Log: newest-first, append-only, structured `action` field | Implemented |
| Explanation and change reporting: what changed, constraints, blocked trades | Implemented |
| Freshness UX: per-source from latest successful `refresh_log` row, two-layer warnings | Implemented |
| **Signals tab 2×2 grid** | Not implemented — 5 cards in a linear stacked layout (the equity opportunity signal added a 5th card beyond the 4 in the design) |
| **Near-maturity 12-month note in holdings table** | Not implemented |
| **ERP card change attribution** ("which factor moved") | Not implemented — card shows current values only |

---

## Persistence Layer — Fully implemented

All schema policy rules are present (STRICT tables, WAL, UTC ISO-8601 timestamps, YYYY-MM-DD dates, WITHOUT ROWID on cache tables, upserts, no generic instrument master). The 11 core tables from the design are present plus 3 additions introduced during build:

- `non_gilt_reference` — non-gilt asset type and source reference
- `strategic_baseline` — user-authored baseline allocations
- `equity_benchmark_prices` — benchmark price history for equity opportunity signal

Foreign key `decision_log → signal_events ON DELETE SET NULL` is implemented. No `running` status in `refresh_log`. Source-level atomic commit/rollback. Dashboard access via `st.connection` with explicit TTLs and `st.cache_data.clear()` on write.

---

## LLM Analysis Layer — Absent from v1 design, candidate for v2

The current explanation layer is mechanical: it reads stored numbers and formats them into structured summaries. There is no LLM anywhere in the system.

The design's "Explanation and Research Layer" section describes generating "readable memos, short recommendation summaries, decision-support notes, and question-answering for the local user" — but specifies these come from structured persisted state, not from an AI model.

Given the data that is now persisted (signal episodes with opening snapshots, allocation run audit payloads, scenario results, decision log, GRY timeseries, yield curve history), a natural v2 addition would be an LLM overlay that produces:

- Plain-English narrative explaining *why* the current recommendation differs from last week in economic terms
- Economic context for current signal states (yield curve shape, ERP regime, gilt market conditions)
- Answers to questions like "should I act on this switch given where we are in the cycle?"
- Draft decision log entries

This would sit on top of existing persisted state as a read-only overlay, consistent with the current explanation layer design principle. It does not require any new write paths.

---

## Summary of Known Gaps

| Gap | Section | Nature |
|---|---|---|
| Confidence does not tighten tilt bands | Allocation Engine | Design feature not built |
| Weighted multi-scenario LP objective absent | Allocation Engine | Design feature not built |
| Cash flows (contributions, coupons, maturities) not tracked as solver inputs | Allocation Engine | Design feature not built |
| Scenario-loss ceilings not in risk gate (covered by LP constraints instead) | Risk Gate | Architectural deviation — protection exists, not as an explicit veto |
| ERP card does not attribute change to specific factor | Dashboard UX | Minor |
| Near-maturity 12-month note absent from holdings table | Dashboard UX / Friction | Minor |
| Signals tab not a 2×2 grid (5 linear cards; equity opportunity is an addition) | Dashboard UX | Structural |
| ERP banner shows as stale rather than suppressed | Dashboard UX | Minor behavioural deviation |
| LLM analysis/interpretation layer | Entire system | Not in v1 design; v2 candidate |
