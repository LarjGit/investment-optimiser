---
title: "Fisher equation: compute_gry returns decimal, RPI input is percentage"
tags: [gilt-analytics, il-gilts, fisher-equation, units]
date: 2026-05-22
---

## Problem

`compute_gry()` returns yield as a decimal fraction (e.g. `0.02` means 2%).
The RPI assumption entered by the user is in percentage points (e.g. `3.0` means 3%).

When implementing the semi-annual Fisher equation, mixing these units silently
produces a wrong answer. The formula divides both rates by 2 to get the
semi-annual rate:

```python
# WRONG — divides real_gry (decimal) by 200 instead of 2
nominal_equiv = 2.0 * ((1.0 + real_gry / 200.0) * (1.0 + rpi_pct / 200.0) - 1.0) * 100.0

# CORRECT — real_gry is decimal (/2), rpi_pct is percentage (/200)
nominal_equiv = 2.0 * ((1.0 + real_gry / 2.0) * (1.0 + rpi_pct / 200.0) - 1.0)
```

The wrong formula gives `≈3.02` instead of `≈0.0503` for a 2% real / 3% RPI case.
The result is also in the wrong unit (percentage vs decimal), compounding the error.

## Solution

Remember: every yield that flows through the gilt analytics pipeline (from
`compute_gry`, from `gilt_price_cache.gry_pct`) is stored and returned as a
**decimal** (0.05 = 5%). The user-facing RPI input is a **percentage** (5.0 = 5%).

Fisher exact, semi-annual, with these units:
```python
nominal_equiv = 2.0 * ((1.0 + real_gry / 2.0) * (1.0 + rpi_assumption_pct / 200.0) - 1.0)
```

Result is also decimal, consistent with `gry_pct` storage.
