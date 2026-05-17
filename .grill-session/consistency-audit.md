---
phase: audit
status: complete
date: 2026-05-17
---

## Verdict
Needs reconciliation before stitch

## Critical Contradictions
- `.grill-session/level2-data-ingestion.md` and `.grill-session/level3-data-ingestion-csv-normalisation.md` disagree on the raw ii quantity column name. The Level 2 source says the CSV uses `Qty`, while the Level 3 adapter contract hard-requires `Quantity` in `II_REQUIRED_COLUMNS` and says import should fail if it is missing. One exact header contract must win or the importer specification is not self-consistent.
- `.grill-session/level2-dashboard-ux.md` defines the Decision Log input as an `Add note` form with only `st.text_area` plus `Save note`, while `.grill-session/level2-persistence-layer.md` and `.grill-session/level3-persistence-layer-schema-definitions.md` require every `decision_log` row to carry an `action` in `('acted','passed','deferred')`. The current UX contract does not establish how that required field is supplied.

## Gaps And Missing Promotions
- `.grill-session/level2-friction-model.md` defines separate spread defaults for `Gilt ETFs` and `Corporate bonds`, but `.grill-session/level2-data-ingestion.md`, `.grill-session/level3-data-ingestion-csv-normalisation.md`, and `.grill-session/level3-persistence-layer-schema-definitions.md` only persist the asset types `gilt_conventional`, `gilt_index_linked`, `mmf`, `equity`, `etf`, `investment_trust`, `reit`, `fund`, and `other`. No owning file explains how a gilt ETF or corporate bond is distinguished from generic `etf` / `fund` / `other` for class-specific friction.
- `.grill-session/level2-persistence-layer.md` still says its `schema-definitions` child covers “all 9 tables” even though the same file now declares `11 total` tables and `.grill-session/level3-persistence-layer-schema-definitions.md` defines 11 tables. The subsection descriptor is stale and should be reconciled upward before stitch.

## Open Questions Still Unresolved
- What is the authoritative ii quantity header for the first adapter contract: `Qty` or `Quantity`?
- Should friction-class routing expand the persisted taxonomy, or should a separate derived friction classification layer own distinctions such as `gilt ETF` and `corporate bond`?
- Does the Decision Log tab need an explicit `action` control, or should pure free-text notes become a first-class schema case separate from `decision_log` entries with structured actions?

## Section Map Integrity
- All Level 1 checked sections have matching Level 2 files.
- All checked Level 2 sub-sections have matching Level 3 files.
- No orphaned Level 2 or Level 3 source files were found.
- Existing `consistency-audit.md` and `reconciliation-log.md` files are auxiliary audit artifacts and do not break the Level 1/2/3 map.

## Required Source Updates Before Stitch
- Reconcile `.grill-session/level2-data-ingestion.md` and `.grill-session/level3-data-ingestion-csv-normalisation.md` so the ii adapter has one exact raw-header contract for the quantity column.
- Reconcile the Decision Log contract across `.grill-session/level2-dashboard-ux.md`, `.grill-session/level2-persistence-layer.md`, and `.grill-session/level3-persistence-layer-schema-definitions.md` so the UI and schema agree on whether `action` is required and how it is captured.
- Add an authoritative friction-class ownership rule across `.grill-session/level2-friction-model.md`, `.grill-session/level2-data-ingestion.md`, `.grill-session/level3-data-ingestion-csv-normalisation.md`, and `.grill-session/level3-persistence-layer-schema-definitions.md` for instruments that need spread handling beyond the persisted `asset_type` set.
- Update `.grill-session/level2-persistence-layer.md` so its `schema-definitions` sub-section description matches the current 11-table schema.
