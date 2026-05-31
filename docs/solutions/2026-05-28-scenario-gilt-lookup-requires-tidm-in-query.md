---
title: "Scenario engine gilt lookup was always empty in production (missing r.tidm in query)"
tags: [scenario-engine, gilt-signals, app-query, tidm]
date: 2026-05-28
---

## Problem

`_build_gilt_lookup` in `scenario_engine.py` is keyed by `tidm` and guards with:

```python
if gilt_ref_df.empty or "tidm" not in gilt_ref_df.columns:
    return {}
```

The test helpers always supply `tidm` directly, so tests passed. But the
`gilt_ranking_rows` SQL query in `app.py` did **not** include `r.tidm` — only
`p.isin`, `r.instrument_name`, `r.instrument_type`, etc. This meant:

- In production: `_build_gilt_lookup` always returned `{}`
- All gilts (conventional and IL) were silently repriced as `unmodelled_held_flat`
- No test caught this because test helpers bypassed the production data path

A new session reading `_build_gilt_lookup` would reasonably assume the lookup
was populated; it was not.

## Solution

Add `r.tidm` to the `gilt_ranking_rows` query in `app.py`:

```sql
SELECT
    p.isin,
    r.tidm,          -- ← required for _build_gilt_lookup to produce a non-empty dict
    r.instrument_name,
    ...
```

When adding new fields to the scenario gilt lookup, always verify that the
upstream SQL query in `app.py` (and any other caller) selects those fields from
`gilt_reference`. The test data path and the production data path diverge here.
