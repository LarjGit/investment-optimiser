---
section: persistence-layer
subsection: schema-definitions
phase: level3
status: complete
date: 2026-05-17
---

## Implementation Detail

### Global DDL policy

The persistence schema uses these rules throughout:

- All app-owned tables are `STRICT`
- `PRAGMA foreign_keys = ON`
- Calendar dates are stored as `TEXT` in `YYYY-MM-DD`
- Exact timestamps are stored as UTC ISO-8601 `TEXT`
- Composite-key daily snapshot/cache tables use `WITHOUT ROWID`
- Upserts use `ON CONFLICT DO UPDATE`, not `INSERT OR REPLACE`
- No generic instrument master table is introduced; rows store the real identifiers they actually use (`symbol`, optional `isin`, `ticker`)

### Table 1: `portfolio_snapshots`

One row per portfolio holding per snapshot date.

```sql
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_date    TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    isin             TEXT,
    instrument_name  TEXT NOT NULL,
    asset_type       TEXT NOT NULL CHECK (
        asset_type IN (
            'gilt_conventional',
            'gilt_index_linked',
            'mmf',
            'equity',
            'etf',
            'investment_trust',
            'reit',
            'fund',
            'other'
        )
    ),
    quantity         REAL NOT NULL,
    clean_price_gbp  REAL,
    market_value_gbp REAL NOT NULL,
    book_cost_gbp    REAL,
    weight_pct       REAL NOT NULL,
    PRIMARY KEY (snapshot_date, symbol)
) STRICT, WITHOUT ROWID;
```

Notes:

- `symbol` is the practical primary identifier for portfolio rows
- `isin` is nullable and retained when known, but not required for non-gilts
- No foreign key to `gilt_reference`; historical snapshots must survive reference-table refreshes and matured instruments

### Table 2: `signal_readings`

One row per day, signal, and metric. Same-day reruns update the existing row rather than appending duplicates.

```sql
CREATE TABLE IF NOT EXISTS signal_readings (
    reading_date TEXT NOT NULL,
    signal_name  TEXT NOT NULL,
    metric_name  TEXT NOT NULL,
    value        REAL NOT NULL,
    unit         TEXT NOT NULL,
    PRIMARY KEY (reading_date, signal_name, metric_name)
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_signal_readings_metric_history
ON signal_readings(signal_name, metric_name, reading_date DESC);
```

Examples:

- `yield_curve_shape` / `spread_2s10s_bps`
- `duration_limit` / `portfolio_duration_years`
- `liquidity_concentration` / `pct_over_10y`
- `equity_macro` / `equity_earnings_yield_pct`

### Table 3: `signal_events`

One row per real alert episode, from first fire until clear.

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    id           INTEGER PRIMARY KEY,
    alert_type   TEXT NOT NULL,
    scope_key    TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    started_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    cleared_at   TEXT,
    message      TEXT NOT NULL,
    details_json TEXT NOT NULL CHECK (json_valid(details_json))
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_events_active
ON signal_events(alert_type, scope_key)
WHERE cleared_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_signal_events_active_lookup
ON signal_events(alert_type, scope_key, started_at)
WHERE cleared_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_signal_events_history
ON signal_events(started_at DESC);
```

Notes:

- `scope_key` is `portfolio` in v1, but the column is kept for future scope expansion
- `message` and `details_json` are the opening snapshot, not a rolling latest-state payload

### Table 4: `decision_log`

Append-only user decision history.

```sql
CREATE TABLE IF NOT EXISTS decision_log (
    id                   INTEGER PRIMARY KEY,
    decision_date        TEXT NOT NULL,
    signal_event_id      INTEGER REFERENCES signal_events(id) ON DELETE SET NULL,
    action               TEXT NOT NULL CHECK (action IN ('acted', 'passed', 'deferred')),
    instruments_affected TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(instruments_affected)),
    notes                TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS ix_decision_log_created_at
ON decision_log(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_decision_log_signal_event
ON decision_log(signal_event_id);
```

Notes:

- `instruments_affected` is JSON text, not comma-separated free text
- Example payloads:
  - `["TR27","ISF"]`
  - `[{"symbol":"TR27","side":"sell"},{"symbol":"TG29","side":"buy"}]`

### Table 5: `yield_curve_cache`

Daily BoE rates cache for both named curve points and base rate.

```sql
CREATE TABLE IF NOT EXISTS yield_curve_cache (
    cache_date      TEXT NOT NULL,
    curve_key       TEXT NOT NULL,
    maturity_years  REAL,
    rate_pct        REAL NOT NULL,
    series_code     TEXT,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (cache_date, curve_key)
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_yield_curve_cache_history
ON yield_curve_cache(curve_key, cache_date DESC);
```

Expected `curve_key` values:

- `base_rate`
- `1y`
- `2y`
- `5y`
- `10y`
- `20y`
- `30y`

Notes:

- `maturity_years` is nullable so `base_rate` does not need a fake maturity like `0`

### Table 6: `gilt_price_cache`

Daily gilt market snapshot plus derived fixed-income analytics.

```sql
CREATE TABLE IF NOT EXISTS gilt_price_cache (
    cache_date               TEXT NOT NULL,
    isin                     TEXT NOT NULL,
    clean_price_gbp          REAL NOT NULL,
    gry_pct                  REAL NOT NULL,
    modified_duration_years  REAL NOT NULL,
    coupon_pct               REAL NOT NULL,
    maturity_date            TEXT NOT NULL,
    fetched_at               TEXT NOT NULL,
    PRIMARY KEY (cache_date, isin)
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_gilt_price_cache_history
ON gilt_price_cache(isin, cache_date DESC);
```

Notes:

- No foreign key to `gilt_reference`; the cache must remain queryable even after monthly reference replacement or after a gilt matures out of the live reference set

### Table 7: `equity_price_cache`

Daily cached prices for non-gilt exchange-traded holdings fetched from Yahoo Finance.

```sql
CREATE TABLE IF NOT EXISTS equity_price_cache (
    cache_date      TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    close_price_gbp REAL NOT NULL,
    volume          INTEGER,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (cache_date, ticker)
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_equity_price_cache_history
ON equity_price_cache(ticker, cache_date DESC);
```

### Table 8: `equity_valuation_cache`

Dated equity-valuation inputs used by the equity macro signal.

```sql
CREATE TABLE IF NOT EXISTS equity_valuation_cache (
    cache_date   TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    pe_ratio     REAL NOT NULL,
    pe_as_of     TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (cache_date, source_name)
) STRICT, WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS ix_equity_valuation_cache_history
ON equity_valuation_cache(source_name, cache_date DESC);
```

Notes:

- v1 stores one source row per day with `source_name='blackrock_isf_html'`
- `pe_as_of` is preserved separately from `cache_date` because the valuation field's own date drives signal freshness

### Table 9: `refresh_log`

Append-only operational log. Multiple runs on the same day are expected and retained.

```sql
CREATE TABLE IF NOT EXISTS refresh_log (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL CHECK (
        source IN (
            'boe',
            'dmo_reference',
            'blackrock_ftse_pe',
            'lse_gilt_prices',
            'lse_tidm_bridge',
            'yfinance_equities'
        )
    ),
    run_started_at TEXT NOT NULL,
    finished_at    TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    error_msg      TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS ix_refresh_log_source_finished
ON refresh_log(source, finished_at DESC);

CREATE INDEX IF NOT EXISTS ix_refresh_log_source_success
ON refresh_log(source, finished_at DESC)
WHERE status = 'completed';
```

Notes:

- The dashboard determines freshness from the latest successful row per source
- Same-day reruns append new rows rather than overwriting earlier attempts

### Table 10: `gilt_reference`

Monthly-refreshed gilt reference table loaded from DMO XML plus LSE TIDM bridge data.

```sql
CREATE TABLE IF NOT EXISTS gilt_reference (
    isin             TEXT PRIMARY KEY,
    tidm             TEXT UNIQUE,
    instrument_name  TEXT NOT NULL,
    coupon_pct       REAL NOT NULL,
    maturity_date    TEXT NOT NULL,
    dividend_months  TEXT NOT NULL,
    dividend_day     INTEGER NOT NULL,
    ex_div_date      TEXT,
    instrument_type  TEXT NOT NULL CHECK (instrument_type IN ('Conventional', 'Index-linked')),
    maturity_bracket TEXT,
    last_updated     TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS ix_gilt_reference_tidm
ON gilt_reference(tidm);

CREATE INDEX IF NOT EXISTS ix_gilt_reference_maturity
ON gilt_reference(maturity_date);
```

Notes:

- `tidm` is nullable because the bridge is external and may fail for some rows
- `tidm` is still indexed for fast portfolio-symbol matching

### Table 11: `allocation_runs`

Replayable audit trail for each allocator solve.

```sql
CREATE TABLE IF NOT EXISTS allocation_runs (
    id                    INTEGER PRIMARY KEY,
    created_at            TEXT NOT NULL,
    policy_version        TEXT NOT NULL,
    baseline_version      TEXT NOT NULL,
    current_snapshot_date TEXT NOT NULL,
    regime_state          TEXT NOT NULL,
    scenario_set_name     TEXT NOT NULL,
    solver_status         TEXT NOT NULL,
    fallback_path         TEXT,
    snapshot_json         TEXT NOT NULL CHECK (json_valid(snapshot_json))
) STRICT;

CREATE INDEX IF NOT EXISTS ix_allocation_runs_created_at
ON allocation_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_allocation_runs_policy_version
ON allocation_runs(policy_version, created_at DESC);
```

Notes:

- `snapshot_json` is the full replay payload, including baseline allocation, current holdings, sleeve confidence values, cash-flow inputs, active constraints, score coefficients, scenario floors/results, solver diagnostics, fallback path, and sleeve explanation payloads
- indexed scalar columns support quick lookup without duplicating the whole payload across many narrow tables

### Upsert patterns

Daily cache/snapshot tables should be written with `ON CONFLICT DO UPDATE`, for example:

```sql
INSERT INTO signal_readings (reading_date, signal_name, metric_name, value, unit)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(reading_date, signal_name, metric_name)
DO UPDATE SET
    value = excluded.value,
    unit  = excluded.unit;
```

This is important for same-day reruns: the current day is updated, not duplicated.

### Foreign-key boundaries

Only one foreign key is required in v1:

- `decision_log.signal_event_id -> signal_events.id ON DELETE SET NULL`

Do **not** add foreign keys from historical cache/snapshot tables into `gilt_reference`. That would create unnecessary coupling to the monthly reference refresh process and would make old rows harder to retain cleanly.

## Decisions Made

- All app-owned tables are `STRICT`
- All dates/times are stored as `TEXT`; day-level fields use `YYYY-MM-DD`, event timestamps use UTC ISO-8601
- Composite-key daily tables use `WITHOUT ROWID`
- `portfolio_snapshots` stores `symbol` plus nullable `isin`; no generic instrument master table
- `signal_readings` is generic and keyed by `(reading_date, signal_name, metric_name)` so same-day reruns upsert
- `signal_events` uses the episode model from the signal-state-machine drill-down, including a partial unique index for active alerts
- `decision_log.instruments_affected` is JSON text, not free-form delimited text
- `yield_curve_cache` stores both named curve points and `base_rate` in one table using `curve_key`
- `equity_valuation_cache` stores dated equity-valuation inputs separately from trade-price caches because the signal depends on both `pe_ratio` and `pe_as_of`
- `refresh_log` is append-only with one row per attempt, so multiple runs per day are preserved
- `gilt_reference` remains separate from historical caches
- `allocation_runs` stores replayable optimizer output as one JSON-backed audit record per solve
- Upserts use `ON CONFLICT DO UPDATE`, not `INSERT OR REPLACE`

## Remaining Open Questions

None
