---
phase: reconcile
status: complete
date: 2026-05-17
based_on_audit: consistency-audit.md
---

## Summary
This reconciliation resolved the remaining contract drift left by the latest audit without introducing a new design fork. The main changes were promoting missing persistence ownership into the source docs, aligning the refresh workflow with the actual signal and CSV-import write path, and giving the allocator plus BlackRock valuation input explicit persisted homes. The gilt analytics drill-down was also narrowed so it now matches the schema-owned storage contract and no longer depends on an unstored `issue_date`. Authority was clear from the existing persistence and Level 2 decisions, so no user tie-break was required.

## Decisions Applied
- Equity valuation source ownership -> the BlackRock `ISF` P/E snapshot is now promoted into the ingestion and persistence contracts -> updated `.grill-session/level1.md`, `.grill-session/level2-data-ingestion.md`, `.grill-session/level2-persistence-layer.md`, `.grill-session/level3-signal-layer-equity-signal-pe-source.md`, `.grill-session/level3-persistence-layer-schema-definitions.md`, `.grill-session/level3-persistence-layer-refresh-job-structure.md`, `.grill-session/level3-persistence-layer-dashboard-db-access.md`
- Allocator replay storage -> the optimizer's replayable audit payload now has an authoritative home in `allocation_runs` -> updated `.grill-session/level2-allocation-engine.md`, `.grill-session/level2-persistence-layer.md`, `.grill-session/level3-allocation-engine-optimizer-algorithm.md`, `.grill-session/level3-persistence-layer-schema-definitions.md`
- Refresh and write ownership -> one local refresh coordinator owns CSV import, remote-source refresh, and authoritative signal persistence; the dashboard remains read-mostly except append-only notes -> updated `.grill-session/level2-data-ingestion.md`, `.grill-session/level2-persistence-layer.md`, `.grill-session/level3-persistence-layer-refresh-job-structure.md`
- Signal persistence sequencing -> `signal_readings` and `signal_events` are now explicitly written after the latest stored inputs land -> updated `.grill-session/level2-data-ingestion.md`, `.grill-session/level2-persistence-layer.md`, `.grill-session/level3-persistence-layer-refresh-job-structure.md`
- Gilt analytics storage contract -> the persistence schema wins on column names, nullability, and terminal-only `refresh_log` semantics -> updated `.grill-session/level3-allocation-engine-gry-calculation.md`
- First-period gilt handling -> the reference-data contract stays unchanged; the stray `issue_date` dependency was removed from the GRY drill-down -> updated `.grill-session/level3-allocation-engine-gry-calculation.md`
- Stale parent/child allocation drift -> the optimizer drill-down no longer claims its Level 2 parent is outdated -> updated `.grill-session/level3-allocation-engine-optimizer-algorithm.md`

## Files Updated
- `.grill-session/level1.md` - promoted BlackRock as a high-level owned data source
- `.grill-session/level2-data-ingestion.md` - added BlackRock source ownership and clarified that the coordinator imports `data/portfolio_latest.csv` into `portfolio_snapshots` before remote refresh and signal writes
- `.grill-session/level2-allocation-engine.md` - promoted the requirement that every solve is persisted as a replayable audit record
- `.grill-session/level2-persistence-layer.md` - rewrote process/write ownership and added `equity_valuation_cache` plus `allocation_runs`
- `.grill-session/level3-allocation-engine-gry-calculation.md` - aligned gilt cache column names, nullability, warning behaviour, and removed the unsupported `issue_date` dependency
- `.grill-session/level3-allocation-engine-optimizer-algorithm.md` - removed stale parent drift language and pointed replay storage at `allocation_runs`
- `.grill-session/level3-signal-layer-equity-signal-pe-source.md` - added the persisted cache and `refresh_log` contract for the BlackRock valuation source
- `.grill-session/level3-persistence-layer-schema-definitions.md` - added DDL for `equity_valuation_cache` and `allocation_runs`, and extended `refresh_log.source` with `blackrock_ftse_pe`
- `.grill-session/level3-persistence-layer-refresh-job-structure.md` - defined the three-phase coordinator flow: local portfolio import, remote sources, then authoritative signal persistence
- `.grill-session/level3-persistence-layer-dashboard-db-access.md` - added the new valuation source and allocator audit table to the dashboard read/freshness contract

## Deferred Issues
None

## Ready For Re-Audit
Yes
