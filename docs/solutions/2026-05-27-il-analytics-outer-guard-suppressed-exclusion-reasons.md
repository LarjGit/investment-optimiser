---
title: "IL analytics outer 'if' guard suppressed exclusion reasons when forward assumptions absent"
tags: [gilt-analytics, il-gilts, observed-inflation, exclusion-reasons]
date: 2026-05-27
---

## Problem

`gilt_analytics_handler` had an outer `if` block that gated the entire IL processing
loop on both forward assumptions being non-None and > 0:

```python
if (
    forward_rpi_pre_2030_pct is not None and forward_rpi_pre_2030_pct > 0.0
    and forward_rpi_post_2030_pct is not None and forward_rpi_post_2030_pct > 0.0
):
    ...
```

This meant: when forward assumptions were absent, the IL block was silently skipped.
No warnings were produced, and no exclusion reasons were written to the DB.

A new session reading the schema and the resolver module would reasonably assume the
handler always processes IL gilts — but it did not when forward assumptions were unset.

## Solution

Remove the outer guard entirely. Always run the IL loop and always call
`resolve_il_contract()` for each IL gilt. The resolver already handles absent or
invalid forward assumptions by returning a distinct `InflationResolutionError`, so the
right exclusion reason is produced regardless of which input is missing.

The side effect of removing the guard is that `get_latest_observed_inflation()` is
always called (one extra DB read per analytics run when forward assumptions are absent).
This is acceptable for a local decision-support tool.

Related: [[2026-05-27-observed-inflation-cache-was-unplugged-from-analytics]]
