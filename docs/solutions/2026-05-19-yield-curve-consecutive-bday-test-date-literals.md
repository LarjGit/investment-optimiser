---
title: "Verify actual weekday when writing yield curve consecutive-business-day tests"
tags: [testing, yield-curve, business-days, dates]
date: 2026-05-19
---

## Problem

When writing tests for consecutive UK business day counting, date literals chosen by
"feel" (e.g. "May 19 is Monday, so May 16 is Friday") can be wrong. In May 2026,
May 19 is a Tuesday and May 16 is a Saturday. Tests that wrote `("2026-05-16", ...)  # Fri`
got an unexpected data gap: the algorithm correctly found Monday May 18 as an unmapped
business day and broke the streak, returning 1 instead of the expected 3.

This is a silent failure — the test runs but asserts the wrong expected value, or
the implementation returns a count that makes no sense given the comments.

## Solution

Before committing a date literal in a business-day test, verify it with Python:

```python
import datetime
datetime.date(2026, 5, 16).strftime("%A")  # → 'Saturday'
```

For consecutive-streak tests, build the date list by stepping backward from the anchor
date using `datetime.timedelta`, or verify all literals with the above check.
The key invariant: every business-day entry in a history list that is supposed to
extend a streak must have no unmapped business day between it and the next newer entry.
