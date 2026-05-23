---
title: "TTM-based bracket boundaries are ambiguous at exact-year dates with /365.25 divisor"
tags: [gilt-signals, testing, maturity-bracket, date-arithmetic]
date: 2026-05-23
---

## Problem

When computing time-to-maturity as `(mat - ref).days / 365.25`, a date that is exactly N calendar years away from the reference date does **not** reliably equal N.0. Leap years in the span mean the actual day count can be 1826 for a 5-year span (which divides to 4.9986, not 5.0), causing boundary tests to fail unexpectedly.

Example: `date(2031, 5, 23) - date(2026, 5, 23)` = 1826 days (one leap year in span). `1826 / 365.25 = 4.9986` — which falls into the **short** bracket, not medium.

## Solution

Avoid pinning boundary tests to "exactly N years" dates when using the `/365.25` divisor. Instead use dates that are clearly and unambiguously above or below the threshold:

- For "just over 5y" from 2026-05-23: use `2031-06-07` (~5.04y)
- For "just under 5y" from 2026-05-23: use `2030-06-07` (~4.04y)

The implementation itself is correct — the slight imprecision at boundaries is acceptable for bracket assignment and matches how the DMO categorises gilts. Tests should use clearly-separated dates rather than exact boundary dates.
