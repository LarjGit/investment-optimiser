---
title: "app.py loads gilt ranking via its own SQL, not via fetch_gilt_ranking()"
tags: [app, gilt-signals, gilt-ranking, state-loading]
date: 2026-05-22
---

## Problem

`gilt_signals.py` contains `fetch_gilt_ranking()` and `build_gilt_candidate_universe()`.
A fresh session implementing a ranking change would naturally update those functions
and assume the UI picks up the change.

In practice, `app.py` loads the gilt ranking into `state["gilt_ranking"]` via a raw
`connection.query(...)` SQL block (around line 251) that is completely separate from
`fetch_gilt_ranking()`. Changes to `gilt_signals.py` queries are NOT reflected in the
Signals tab or in the LP recommendation pipeline without also updating this SQL block.

## Solution

When adding new columns to the gilt ranking (e.g. `instrument_type`,
`real_gry_pct`, `nominal_equivalent_gry_pct`), update both:

1. The SQL constants in `gilt_signals.py` (`_RANKING_SQL_*`, `_CANDIDATE_SQL_*`)
2. The `connection.query(...)` block in `app.py` `_load_state()`

The app's state query intentionally loads ALL gilts (conventional + IL) with all
columns, and the render / LP functions then filter based on session state at display
time. `gilt_signals.py` functions are used by tests and by `build_gilt_candidate_universe`
(which is currently only used in tests — `lp_recommendation.py` receives the pre-built
`gilt_ranking_df` from the app layer).
