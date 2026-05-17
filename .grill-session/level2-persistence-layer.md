---
section: persistence-layer
phase: level2
status: complete
date: 2026-05-16
---

## What We Established

The persistence layer is a single SQLite file owned by one local Streamlit app process. Within that process, a single refresh coordinator owns the portfolio-import step plus all market-data, signal, and reference-data writes; the dashboard is read-mostly and performs only append-only decision-note inserts outside the refresh path. WAL mode is still enabled so short reads and writes can coexist cleanly. The dashboard connects via `st.connection` with SQLAlchemy; refresh and import paths use raw `sqlite3`. Schema evolution is handled by `PRAGMA user_version` with numbered migration functions run on startup - no Alembic. Nothing is ever pruned; the data volume is trivially small for a decade of use.

**Tables confirmed (11 total):**

1. `portfolio_snapshots` - one row per (date x symbol), position-level granularity. Columns: snapshot_date, symbol, isin (nullable), instrument_name, asset_type, quantity, clean_price_gbp, market_value_gbp, book_cost_gbp, weight_pct.
2. `signal_readings` - one row per (date x signal x metric), daily computed values for charts and diagnostics. Columns: reading_date, signal_name, metric_name, value, unit.
3. `signal_events` - one row per alert episode from first fire until clear. Columns: id, alert_type, scope_key, severity, started_at, last_seen_at, cleared_at, message, details_json.
4. `decision_log` - one row per user decision entry. Columns: decision_date, signal_event_id (nullable FK -> signal_events), action ('acted'|'passed'|'deferred'), instruments_affected (JSON TEXT), notes, created_at.
5. `yield_curve_cache` - one row per (date x curve_key). Columns: cache_date, curve_key, maturity_years (nullable), rate_pct, series_code, fetched_at.
6. `gilt_price_cache` - one row per (date x ISIN). Columns: cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years, coupon_pct, maturity_date, fetched_at.
7. `equity_price_cache` - one row per (date x ticker). Columns: cache_date, ticker, close_price_gbp, volume, fetched_at.
8. `equity_valuation_cache` - one row per (date x source) for dated equity-valuation inputs. Columns: cache_date, source_name, pe_ratio, pe_as_of, fetched_at.
9. `refresh_log` - append-only one row per remote refresh attempt. Columns: id, source, run_started_at, finished_at, status, error_msg.
10. `gilt_reference` - one row per gilt in the monthly DMO/LSE reference set. Columns: isin, tidm, instrument_name, coupon_pct, maturity_date, dividend_months, dividend_day, ex_div_date, instrument_type, maturity_bracket, last_updated.
11. `allocation_runs` - one row per allocator solve. Columns: id, created_at, policy_version, baseline_version, current_snapshot_date, regime_state, scenario_set_name, solver_status, fallback_path, snapshot_json.

## Decisions Made

- **Table granularity**: position-level for portfolio snapshots (date x symbol), not portfolio-level summary rows; no generic instrument master table
- **Signal persistence**: two tables - `signal_readings` for generic daily metrics keyed by `(date, signal, metric)` and `signal_events` for alert episodes from first fire until clear
- **Decision log**: nullable FK to `signal_events` (unprompted decisions have no signal); `action` as a structured TEXT column; `instruments_affected` stored as JSON TEXT; free-text `notes` field
- **Market data cache**: four separate typed cache tables (`yield_curve_cache`, `gilt_price_cache`, `equity_price_cache`, `equity_valuation_cache`) plus `gilt_reference` as the monthly reference table - not a unified EAV table
- **Upsert strategy**: `ON CONFLICT DO UPDATE` on daily snapshot/cache/readings tables - idempotent same-day reruns without `REPLACE`
- **Refresh ownership**: the refresh coordinator owns local CSV import into `portfolio_snapshots`, all remote cache/reference refreshes, and the authoritative daily write of `signal_readings` / `signal_events`
- **Refresh state tracking**: `refresh_log` is append-only with one row per remote attempt; dashboard freshness uses the latest successful row per source
- **Allocator audit trail**: every solve persists its replayable payload in `allocation_runs`
- **Retention**: no pruning - keep all data indefinitely; entire DB stays under 50MB for a decade
- **Connection pattern**: `st.connection('db', type='sql')` with SQLAlchemy for dashboard reads; `conn.query(..., ttl=60)` for result-level caching; WAL mode set at DB creation
- **Schema migration**: `PRAGMA user_version` with a list of numbered Python migration functions run on startup; version increments atomically inside each migration's transaction

## Sub-section Map

- [x] schema-definitions - Exact DDL (column names, types, constraints, composite PKs, indexes) for all 9 tables
- [x] refresh-job-structure - Daily refresh job structure: WAL setup, per-source fetch/upsert flow, refresh_log writes, error handling, re-run safety
- [x] dashboard-db-access - st.connection configuration, secrets.toml setup, query patterns with TTL, staleness detection banner

## Remaining Open Questions

None.
