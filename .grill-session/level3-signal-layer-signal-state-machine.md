---
section: signal-layer
subsection: signal-state-machine
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

The signal state machine is a small, explicit event-log system. Alert types are fixed in Python code, while SQLite stores each real alert episode that occurred.

### Alert catalogue lives in code

V1 uses a fixed alert catalogue in Python, not a database-driven configuration table. Each alert definition supplies:

- `alert_type` — stable machine name such as `gry_switch`
- `severity` — default display level such as `warning` or `error`
- evaluator function — returns whether the alert is currently firing
- message builder — renders the plain-English opening message
- details builder — creates the opening snapshot payload

The market data determines whether each alert is currently on or off. It does not create new alert types dynamically.

### `signal_events` table shape

One row represents one alert episode: from first fire until clear.

Recommended schema:

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    id           INTEGER PRIMARY KEY,
    alert_type   TEXT NOT NULL,
    scope_key    TEXT NOT NULL,   -- v1: always 'portfolio'
    severity     TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    started_at   TEXT NOT NULL,   -- ISO8601 UTC timestamp
    last_seen_at TEXT NOT NULL,   -- ISO8601 UTC timestamp
    cleared_at   TEXT,            -- ISO8601 UTC timestamp, NULL while active
    message      TEXT NOT NULL,   -- opening plain-English message
    details_json TEXT NOT NULL    -- opening snapshot payload
) STRICT;
```

`cleared_at IS NULL` means the row is still active. No separate `status` column is needed.

### Uniqueness and active-row rule

V1 does **not** use SHA256 fingerprints. The logical identity is carried directly by normal columns:

- `alert_type`
- `scope_key`

The database enforces "at most one active row per logical alert" with a unique partial index:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_events_active
ON signal_events(alert_type, scope_key)
WHERE cleared_at IS NULL;
```

Useful read indexes:

```sql
CREATE INDEX IF NOT EXISTS ix_signal_events_active_lookup
ON signal_events(alert_type, scope_key, started_at)
WHERE cleared_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_signal_events_history
ON signal_events(started_at DESC);
```

Dashboard query for live alerts:

```sql
SELECT *
FROM signal_events
WHERE cleared_at IS NULL
ORDER BY started_at DESC;
```

### State transition flow

The authoritative evaluator runs during the daily refresh job inside one SQLite transaction.

For each alert definition:

1. Evaluate whether the alert is firing now
2. Look up any active row for `(alert_type, scope_key)`
3. Apply one of four transitions:

- **Now firing, no active row:** insert a new row with opening message and opening snapshot
- **Now firing, active row exists:** update `last_seen_at` only
- **Not firing, active row exists:** set `cleared_at` and update `last_seen_at`
- **Not firing, no active row:** do nothing

This produces one clean row per alert episode and avoids duplicate rows while an alert stays active.

### Opening snapshot policy

`message` and `details_json` are the **opening** record, not a rolling latest-state record.

When the alert first fires:

- render the message once
- build the details snapshot once
- save both into the row

While the alert stays active:

- update only `last_seen_at`

When it clears:

- set `cleared_at`
- set `last_seen_at` to the same run timestamp

This preserves the answer to: "Why did this alert first fire?"

### Timestamp and payload format

- Store timestamps as ISO8601 UTC `TEXT`
- Serialize alert-specific payloads with `json.dumps()`
- Keep JSON keys simple, stable, and string-based

Typical `details_json` examples:

- `gry_switch`: best gilt, held gilt, spread bps, threshold bps
- `yield_curve_shape`: shape, 2y yield, 10y yield, 2s10s spread
- `duration_limit`: portfolio duration, floor, ceiling
- `liquidity_concentration`: long-duration pct, threshold pct

### Module structure

Recommended split:

- `signals/catalogue.py`
  - fixed alert definitions
- `signals/types.py`
  - dataclasses for evaluation results, e.g. `AlertDefinition`, `AlertEvaluation`
- `signals/evaluator.py`
  - loops over the catalogue and computes current alert states from fresh market data
- `signals/store.py`
  - SQLite read/write functions for `signal_events`
- `refresh.py`
  - calls the evaluator during the daily authoritative refresh
- `app.py` or dashboard module
  - reads active rows only; never writes signal history in what-if mode

### Dashboard vs refresh responsibilities

There are still two evaluation modes:

- **Daily refresh job:** authoritative, writes to `signal_events`
- **Dashboard what-if mode:** in-memory only, does not write to `signal_events`

The dashboard may recompute "would this fire under my current knob settings?" but that should not create or clear persisted history rows.

## Decisions Made

- One row per alert episode from first fire to clear
- Fixed alert catalogue in Python code, not a database table
- Standard typed columns plus `details_json` snapshot payload
- No `status` column; active state is derived from `cleared_at IS NULL`
- No SHA256 fingerprint column; logical identity is `(alert_type, scope_key)`
- Unique partial index enforces at most one active row per logical alert
- Transition flow is insert / touch / clear / no-op
- `message` and `details_json` are opening snapshots and are not overwritten while active
- `last_seen_at` moves forward on each authoritative run while the alert remains active
- Severity comes from the alert definition in code; rendered opening message is persisted in the row
- Daily refresh writes history; dashboard what-if evaluation is read-only

## Remaining Open Questions

None
