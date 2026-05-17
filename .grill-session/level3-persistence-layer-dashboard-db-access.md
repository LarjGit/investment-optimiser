---
section: persistence-layer
subsection: dashboard-db-access
phase: level3
status: complete
date: 2026-05-17
---

## Implementation Detail

The dashboard uses a single named Streamlit SQL connection for all database access:

```python
conn = st.connection("db", type="sql")
```

The connection is configured in the project-local `.streamlit/secrets.toml`, not hard-coded in Python:

```toml
[connections.db]
url = "sqlite:///data/investment_optimiser.db"
```

Project-local secrets are the correct home for this because the app is local, the DB path may vary by machine, and Streamlit already resolves named connections from `.streamlit/secrets.toml`.

### Read path

All dashboard reads use short `conn.query(...)` calls with explicit TTLs. Do not omit `ttl`, because Streamlit otherwise caches query results indefinitely and would hide freshness changes.

Use two TTL bands:

- `ttl=60` seconds for freshness-sensitive reads
- `ttl=300` seconds for heavier historical tables and charts

Recommended query split:

- `refresh_log` latest-success rows per source: `ttl=60`
- active `signal_events`: `ttl=60`
- latest `portfolio_snapshots` date and current holdings table: `ttl=60`
- current-day `yield_curve_cache`, `gilt_price_cache`, `equity_price_cache`: `ttl=60`
- current-day `equity_valuation_cache`: `ttl=60`
- `decision_log` table: `ttl=60`
- longer history views and charts over `signal_readings` / snapshot history: `ttl=300`
- `allocation_runs` history or replay drill-downs: `ttl=300`

The dashboard stays read-mostly. Queries should be plain SELECT statements that finish quickly and do not hold long transactions open.

### Write path

The dashboard writes only for the append-only note form in the Decision Log tab. That write uses the same named connection via a short SQLAlchemy session:

```python
with conn.session as s:
    s.execute(...)
    s.commit()
```

No other dashboard feature writes refresh state, cache state, or signal history. Those remain owned by the refresh coordinator.

### Post-write and post-refresh cache invalidation

After a successful note save or manual refresh:

1. call `st.cache_data.clear()`
2. call `st.rerun()`

This is mandatory. The user should see the new note, new freshness timestamps, and any updated tables immediately rather than waiting for the 60-300 second TTLs to expire.

### Freshness detection

The dashboard computes source freshness from `refresh_log` by reading the latest **successful** row per source, not merely the latest row overall.

Status rules stay per source:

- fresh: latest successful run within the normal window
- warning: source stale beyond 2 trading days
- error: source stale beyond 5 trading days

The relevant sources are:

- `boe`
- `dmo_reference`
- `blackrock_ftse_pe`
- `lse_tidm_bridge`
- `lse_gilt_prices`
- `yfinance_equities`

If a source has no successful row at all, treat it as error-level unavailable.

### UI status pattern

The dashboard does not use one giant generic stale-data banner. It uses two layers:

1. **Top summary block** - a compact status summary listing each source and whether it is fresh, warning-stale, error-stale, or unavailable
2. **Local section warnings** - `st.warning(...)` or `st.error(...)` only in the tabs/cards affected by that source

Examples:

- stale `boe` data warns in the signals/scenarios areas that depend on the curve
- stale `blackrock_ftse_pe` warns in the equity macro signal card
- stale `lse_gilt_prices` warns in gilt ranking, optimizer output, and bond scenario views
- stale `yfinance_equities` warns in portfolio rows and any equity-related signal card

The rest of the app must still render. Partial data degradation is surfaced explicitly, not escalated into a full-page failure.

## Decisions Made

- One dashboard connection only: `st.connection("db", type="sql")`
- DB URL stored in project-local `.streamlit/secrets.toml`, not hard-coded in Python
- All reads use `conn.query(...)` with explicit TTLs; never rely on indefinite caching
- Freshness-sensitive reads use `ttl=60`; heavier history reads use `ttl=300`
- Decision-log note writes use `conn.session` with a short commit-scoped transaction
- After successful note save or manual refresh, clear cached data and rerun immediately
- Freshness is computed from the latest successful `refresh_log` row per source
- Dashboard freshness UX uses a compact top summary plus local per-section warnings/errors
- Partial source failures never block the whole page from rendering

## Remaining Open Questions

None
