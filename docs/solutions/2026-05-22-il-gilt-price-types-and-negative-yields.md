---
title: "IL gilt solve failures: nominal prices and negative real yields"
tags: [gilt-analytics, il-gilts, lse-prices, negative-yields]
date: 2026-05-22
---

## Problem

Four IL gilts failed real GRY solve in production (`no convergence`) even though the LSE price feed returned valid prices. Two distinct root causes:

**1. Nominal (index-uplifted) prices from LSE for older issuances**
Gilts issued in the 1980s–90s (e.g. GB0008932666 4⅛% IL 2030, GB0031790826 2% IL 2035)
are quoted by LSE as nominal prices with the RPI index uplift already applied. The clean price
can be 200–350+ against a real undiscounted cash-flow sum of ~110. The GRY solver has no
valid bracket — `compute_gry` fails with no convergence.

Detection heuristic: `clean_price > undiscounted_real_sum * 1.5` (ratio ≥ 1.5×).

These gilts cannot be solved without the RPI index ratio; they should be skipped with a user-facing warning rather than silently failing.

**2. Negative real yields for recently-issued short-dated gilts**
Gilts like GB00B128DH60 1¼% IL 2027 and GB00BZ1NTB69 ⅛% IL 2028 have real clean prices
only slightly above their undiscounted cash-flow sum (ratio ~1.01×). This corresponds to
a slightly negative real yield. The standard solver searches v ∈ [0.01, 0.9999] (positive
yields only). For negative real yields, v > 1; the bracket has no root in this range.

## Solution

**For nominal prices**: In `gilt_analytics_handler`, before calling `compute_real_gry`, check
`clean_price > undiscounted_real_sum * 1.5`. If so, append an explanatory warning and skip.

**For negative real yields**: Add `_solve_negative_real_yield()` that searches v ∈ (1, 1.15]
using `brentq`. This covers real yields down to roughly −27%, which is sufficient in practice.
`compute_real_gry` calls `compute_gry` first; if that returns None, falls back to
`_solve_negative_real_yield`.

The two fixes apply to different regimes:
- Ratio < 1.5× → try both positive and negative yield solvers
- Ratio ≥ 1.5× → nominal price, skip with warning
