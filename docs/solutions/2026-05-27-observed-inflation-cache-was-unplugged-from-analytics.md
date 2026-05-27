---
title: "observed_inflation_cache was populated but never consumed by IL analytics"
tags: [il-gilts, dmo-d10c, observed-inflation, gilt-analytics]
date: 2026-05-27
---

## Problem

The `observed_inflation_cache` table was fully populated by `dmo_d10c_handler` and
`get_latest_observed_inflation()` existed as a query helper, but `gilt_analytics_handler`
never called it. IL analytics were still running on a single scalar
`rpi_assumption_pct` passed from `app.py` via a `min(pre_2030, post_2030)` bridge.

A new session reading only the schema and the DMO D10C module would reasonably
assume observed data was already flowing into analytics — it was not.

## Solution

Issue #50 introduced `observed_inflation_resolver.py` to bridge the gap:

- `gilt_analytics_handler` now accepts `forward_rpi_pre_2030_pct` and
  `forward_rpi_post_2030_pct` (replacing `rpi_assumption_pct`)
- It calls `get_latest_observed_inflation()` once per run and builds a dict keyed by ISIN
- For each IL gilt it calls `resolve_il_contract()`, which either returns a
  `ResolvedInflationContract` (with observed fields + blended effective RPI) or an
  `InflationResolutionError` (fail-closed if D10C data is missing)
- `app.py` passes the two session-state values directly; the `_active_forward_inflation_bridge_pct()`
  function is retained but scoped to display-only use

When reading the IL gilt analytics path, start at `observed_inflation_resolver.py`
and `gilt_analytics_handler` — the data flow is: D10C cache → resolver → Fisher equation.
