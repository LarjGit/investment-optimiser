---
phase: drift-audit
status: complete
date: 2026-05-17
---

## Scope

This is not a consistency audit. It asks whether the current `.grill-session` source files still reflect the original design intent as far as that intent can still be reconstructed.

## Evidence Base

Available anchors, in descending reliability:

1. `README.md` in git (`Initial commit`)
2. `.grill-session/level1.md`
3. early-written Level 2 / Level 3 files that were not part of the latest reconciliation wave
4. `.grill-session/reconciliation-log.md`

Important limitation:

- `.grill-session/` is untracked in git, so there is no durable file-by-file history for earlier versions of the design docs
- `level1.md` and several Level 2/3 files were edited during reconciliation on 2026-05-17
- because prior overwritten contents are not preserved, this report can assess drift risk but cannot prove absence of drift

## High-Confidence Preserved Intent

These themes appear stable across the surviving evidence and do not look like accidental drift:

- **Local decision-support tool for a UK SIPP** remains intact.
  `README.md` describes a holistic optimiser for a UK SIPP, and `level1.md` still frames it as a local decision-support tool rather than an execution system.
- **Portfolio-wide framing is preserved.**
  The current design is still whole-portfolio, hierarchical, and baseline-anchored rather than a narrow single-signal toy.
- **Fixed income remains the analytically strongest sleeve.**
  Gilt GRY, DMO/LSE reference data, and exact bond analytics still sit at the centre of the design.
- **Macro/equity signalling remains a secondary overlay, not a separate product.**
  The FTSE 100 earnings-yield comparison remains a supporting signal inside the same portfolio tool.
- **Scenario modelling, friction awareness, and dashboard delivery are still first-class.**
  The current files still describe executable recommendations, scenario views, and transaction-friction gating rather than pure paper optimisation.
- **No evidence was found that reconciliation changed the fundamental non-negotiables.**
  Decision-support only, no paid feeds, Streamlit + SQLite + local Python, and named deterministic scenarios all remain aligned with the current Level 1 constraints.

## Changes That Look Like Clarification, Not Intent Drift

These edits changed specification detail or ownership, but they do not appear to change the product definition:

- Promotion of the BlackRock `ISF` P/E snapshot into Level 1 / ingestion / persistence ownership
- Explicit persisted home for allocator replay data in `allocation_runs`
- Explicit refresh-coordinator ownership for CSV import, remote refresh, and authoritative signal writes
- Removal of the unsupported `issue_date` dependency from gilt analytics
- Alignment of schema names, nullability, and `refresh_log` semantics

These are contract-clarity changes, not new strategy.

## Real Drift Risks

### 1. Decision Log semantics may have shifted

This is the clearest candidate for actual semantic drift.

- `level1.md` still frames persistence as including a `decision log with free-text notes`
- `level2-dashboard-ux.md` defines the UI as an `Add note` form with text input only
- `level2-persistence-layer.md` and `level3-persistence-layer-schema-definitions.md` now require structured `action` values (`acted`, `passed`, `deferred`) for each `decision_log` row

This is not just a wording mismatch. It changes what the feature is:

- original reading: lightweight note-taking tied to decisions/signals
- current schema reading: structured decision capture with mandatory action classification

That may be a good design, but it is a product behaviour change, not merely reconciliation.

### 2. Asset-class handling may be more implementation-driven than the original open-scope intent

Level 1 still says any SIPP-eligible asset class is in scope, and the allocation section still preserves that as a policy stance. However:

- friction modelling now assumes spread defaults for `Gilt ETFs` and `Corporate bonds`
- persistence and ingestion persist a narrower taxonomy that does not explicitly encode those friction classes

This does **not** prove intent drift, but it does show the implementation contracts are starting to drive category meaning. Left unchecked, that can silently narrow the originally open asset-scope promise.

## No Strong Evidence Of Strategic Drift

I did **not** find surviving evidence that reconciliation changed these core design choices:

- whole-portfolio hierarchical allocation
- current holdings are implementation state, not policy truth
- exact gilt analytics with shared GRY engine
- alert-driven dashboard with persisted history
- executable recommendation focus rather than frictionless paper targets

If drift happened, it was not obvious at the strategy layer from the current surviving files.

## Confidence Assessment

- **High confidence** that the core investment thesis is still broadly intact
- **Medium confidence** that the current Level 1 still reflects the original grill-session intent, because `level1.md` itself was later edited
- **Low confidence** in any claim that there was zero semantic drift, because earlier file states were overwritten and are not recoverable from git

## Practical Conclusion

The current problem is not “the whole design has obviously wandered off.”

The current problem is:

1. the workflow destroyed historical evidence
2. reconciliation mixed contract repair with occasional feature-shape changes
3. at least one area (`decision_log`) now looks like a real semantic shift rather than a pure consistency repair

## Recommended Next Step

Before any further reconcile loop:

1. Freeze the current `level1.md` as the best available high-level authority
2. Decide explicitly whether `decision_log` is meant to be:
   - free-text notes
   - structured action records
   - or two separate concepts
3. Treat any future change that alters user-facing behaviour as a **design change**, not a reconciliation
4. Fix the `grill-me-web` skill so audit/reconcile outputs are append-only or timestamped rather than overwritten
