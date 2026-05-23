---
title: "render_signals_tab does not receive database_url — signals needing sqlite3.Connection must thread it in"
tags: [app, signals-tab, sqlite3, architecture]
date: 2026-05-23
---

## Problem

`render_signals_tab(state)` originally only received the cached app `state` dict, which is populated via Streamlit's SQL connection (`st.connection`). Functions that need a bare `sqlite3.Connection` (e.g. for pandas-based in-memory computation rather than a Streamlit-cached query) have no way to get one unless `database_url` is also passed.

A plan that assumed the signals tab could pass a `sqlite3.Connection` to a new card function would fail at wiring — the URL is only available in `main()` and in functions that already accept `database_url` (e.g. `render_scenarios_tab`).

## Solution

Add `database_url: str` as a second parameter to `render_signals_tab` and update the call site in `main()`. Inside the new card function, open a short-lived connection with:

```python
db_path = sqlite_path_from_url(database_url)
with sqlite3.connect(str(db_path)) as conn:
    render_equity_opportunity_signal_card(conn, benchmark_ticker)
```

This is consistent with how other write/compute operations in the app obtain a direct connection (e.g. `insert_baseline`, `_render_narrative_explanation_panel`).
