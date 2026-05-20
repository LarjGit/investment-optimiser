---
title: "active_signals query omitted id — FK link in decision log form would KeyError"
tags: [streamlit, sqlite, state, decision-log, signals]
date: 2026-05-20
---

## Problem

`read_shell_state()` fetched `signal_events` rows with `alert_type, severity, message, started_at`
but omitted the `id` primary key. Any UI element that needs to write `decision_log.signal_event_id`
(a FK to `signal_events.id`) would fail with a `KeyError` when reading `row["id"]` from the
DataFrame at render time.

The omission was invisible in the existing stub — the decision log tab only displayed data
and never used the signal FK. The gap only became apparent when implementing the "link to
signal event" dropdown in the form.

## Solution

Add `id` to the `active_signals` query in `read_shell_state()`:

```sql
SELECT id, alert_type, severity, message, started_at
FROM signal_events
WHERE cleared_at IS NULL
ORDER BY started_at DESC
LIMIT 3
```

When building any state query for a table whose rows will be referenced by a FK elsewhere,
include the primary key in the SELECT even if the current display doesn't need it.
