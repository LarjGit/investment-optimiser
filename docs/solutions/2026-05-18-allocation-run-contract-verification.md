---
title: "Define allocation-run contracts in Python and verify via sqlite3"
tags: [allocation-runs, sqlite, streamlit, testing]
date: 2026-05-18
---

## Problem
Issue `#5` reads like a schema task, but the codebase already had the
`allocation_runs` table and indexes in the initial migration. The missing piece
was the replayable payload contract and a proven write/read path. A second trap
was using Streamlit's cached SQL connection helpers for immediate verification:
they can legitimately return stale results right after a write because `query()`
is cache-backed.

## Solution
Treat `allocation_runs` as a contract-and-persistence slice, not a migration
slice. Keep the JSON payload in `TEXT` with an explicit internal
`schema_version`, validate the payload shape in Python before insert, and use
raw `sqlite3` round-trip tests for verification. That keeps the audit record
readable, deterministic, and independent from Streamlit read caching.
