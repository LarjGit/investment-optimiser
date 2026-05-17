---
section: persistence-layer
subsection: refresh-job-structure
phase: level3
status: complete
date: 2026-05-17
---

## Implementation Detail

The refresh job is a single-process coordinator that runs on app startup when today's data is missing and also on explicit manual refresh. In v1 it owns the only refresh path for portfolio imports, market data, reference data, and authoritative signal writes. The dashboard may still append a short `decision_log` note transaction, but the system must never rely on overlapping refresh writers as a normal operating mode.

### Concurrency model

V1 uses one process-global mutex created through Streamlit's shared resource layer, for example a cached `threading.Lock`. This lock is shared across reruns and browser sessions within the same Streamlit server process.

If a refresh trigger fires while another refresh is already in progress:

- do not queue a second writer
- do not block indefinitely waiting for the lock
- return early with a plain-English `refresh already running` status

This is an application-level coordination rule, not something delegated to SQLite lock contention handling.

The design assumption is explicit:

- exactly one refresh-writer process exists in v1
- if a future scheduled task or second process is introduced, the mutex must be upgraded to a cross-process lock or lease

### Connection setup

Every writer connection applies the same initialization block on open:

- `PRAGMA foreign_keys = ON`
- `PRAGMA journal_mode = WAL`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA busy_timeout = <small fixed timeout>`
- leave `wal_autocheckpoint` at the normal SQLite default behavior

Do not run `PRAGMA wal_checkpoint(...)` in the normal refresh path. WAL checkpoint management is not part of the v1 coordinator logic.

Use Python `sqlite3` with explicit transaction control rather than relying on ambiguous defaults. The practical pattern is:

- open connection
- apply PRAGMAs
- keep network fetches outside write transactions
- start short explicit write transactions only around SQLite upserts and terminal log writes

### Refresh flow

The coordinator runs three phases in order:

1. local portfolio import
2. remote source refreshes
3. derived signal persistence

### Phase 1: local portfolio import

If `data/portfolio_latest.csv` exists and today's portfolio snapshot is missing or a new upload has just been saved, the coordinator normalises that file and upserts today's `portfolio_snapshots` rows before any downstream signal or allocation query reads from SQLite.

This local import step:

- is part of the refresh coordinator rather than a direct dashboard read path
- uses its own short write transaction
- does not create a `refresh_log` row, because `refresh_log` tracks remote-source attempts only

### Phase 2: remote source refreshes

The coordinator processes remote sources independently in a fixed order:

1. `boe`
2. `dmo_reference`
3. `lse_tidm_bridge` if needed by the reference refresh
4. `lse_gilt_prices`
5. `yfinance_equities`
6. `blackrock_ftse_pe`

For each source:

1. Record `run_started_at` in memory
2. Fetch and parse remote data outside any write transaction
3. Open a short write transaction only when data is ready to persist
4. Upsert that source's cache/reference rows
5. Insert one terminal `refresh_log` row with `status='completed'`
6. Commit once

If the source fails after fetch starts but before commit:

1. Roll back the source transaction
2. Open a new short transaction
3. Insert one terminal `refresh_log` row with `status='failed'` and `error_msg`
4. Commit the failure row
5. Continue to the next source

This means a source attempt always produces exactly one terminal log row and never leaves an in-progress row behind.

### Phase 3: derived signal persistence

After the local portfolio snapshot and the remote cache/reference writes are complete, the coordinator evaluates the signal layer against the latest persisted inputs and writes the authoritative daily signal state:

1. compute and upsert today's `signal_readings`
2. reconcile active `signal_events` episodes (`started_at`, `last_seen_at`, `cleared_at`) from those evaluations
3. commit the signal write in its own short transaction

This phase is owned by the refresh coordinator, not by the dashboard. It is not modelled as a separate `refresh_log.source` because it derives from already-persisted local inputs rather than a remote fetch.

### Transaction boundary rules

The coordinator uses one transaction per write unit, not one transaction for the whole refresh run.

That boundary is deliberate:

- successful sources commit even if later sources fail
- reruns only need to re-upsert failed or stale sources
- write locks stay short because HTTP fetch time is outside the transaction
- cache writes and the successful terminal log row are atomically tied together
- local portfolio import and signal persistence can rerun without replaying every remote source

Recommended write pattern:

- local CSV import in one short explicit transaction
- explicit `BEGIN IMMEDIATE` when starting a source write transaction
- batched `executemany(...)` or grouped parameterized statements for upserts
- `ON CONFLICT DO UPDATE` for all daily cache tables and other rerun-safe writes
- a separate short explicit transaction for `signal_readings` plus `signal_events`

`busy_timeout` remains a defensive fallback only. The coordinator should normally avoid contention by design rather than by retrying through it.

### Failure isolation

One source failure does not abort the entire refresh run.

Examples:

- `yfinance_equities` may fail while `boe` and `lse_gilt_prices` still commit successfully
- `dmo_reference` may fail without preventing same-day `boe` cache freshness

This matches the dashboard's graceful degradation model. The app should prefer mixed freshness with explicit warnings over all-or-nothing refresh failure.

### Re-run safety

The refresh job must be idempotent for same-day reruns:

- daily cache tables overwrite the current day's row via `ON CONFLICT DO UPDATE`
- same source can log multiple attempts in `refresh_log` on the same day
- freshness checks read the latest successful row per source, not merely the latest row
- a partially successful prior run does not need cleanup before a second run

Because `refresh_log` is append-only, same-day retries preserve operational history instead of masking earlier failures.

### Suggested module split

- `db.py` or equivalent: connection factory, PRAGMA initialization, migration entrypoint
- `portfolio_import.py`: CSV normalisation and `portfolio_snapshots` upsert
- `refresh.py`: top-level coordinator and mutex handling
- `refresh_sources/boe.py`
- `refresh_sources/dmo.py`
- `refresh_sources/blackrock.py`
- `refresh_sources/lse.py`
- `refresh_sources/yfinance.py`
- `refresh_store.py`: source-specific upsert functions and `refresh_log` insert helpers
- `signals.py`: signal evaluation and `signal_readings` / `signal_events` persistence helpers

The dashboard reads from the persisted tables only for portfolio, market, signal, and scenario data. It does not write refresh state, cache state, or signal history, and it does not participate in source transaction management.

## Decisions Made

- V1 refresh uses one application-level writer coordinator, not overlapping SQLite writers
- The refresh guard is a process-global shared Python lock, not `st.session_state`
- Writer connections explicitly set `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=NORMAL`, and `busy_timeout`
- Remote fetches happen outside SQLite write transactions
- Each source gets its own short write transaction
- Successful source writes and `refresh_log(status='completed')` commit atomically together
- Failed source writes roll back first, then persist one standalone `refresh_log(status='failed')` row
- `refresh_log` remains terminal-only; there is no `running` status in v1
- Source failures are isolated; the coordinator continues through remaining sources
- Re-run safety relies on `ON CONFLICT DO UPDATE` plus append-only attempt logging
- No routine manual WAL checkpointing in the normal refresh path

## Remaining Open Questions

None
