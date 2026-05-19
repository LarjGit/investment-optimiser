---
title: "Newton solver converges to negative-yield root for over-par gilt prices"
tags: [gilt-analytics, gry, scipy, solver]
date: 2026-05-19
---

## Problem

The GRY solver uses `scipy.optimize.newton` as the primary solve path with `brentq` as fallback. For clean prices that exceed the undiscounted sum of all future cash flows (e.g. 200 for a 5-year 4% gilt whose undiscounted sum is ~120), no valid root exists in the economic range v ∈ [0.01, 0.9999] (positive yields). However, Newton does not search a bounded interval — it can converge to a root at v > 1, which corresponds to a negative yield. This is mathematically valid but physically meaningless and should be rejected.

Without a bounds check, Newton returns a negative-yield solution silently and the handler persists a negative GRY rather than emitting a warning.

## Solution

After `optimize.newton` converges, validate that the result is within the physical range before accepting it:

```python
v = optimize.newton(fn, v0)
if not (0.01 <= v <= 0.9999):
    raise RuntimeError("solution outside valid discount-factor range")
```

Raising `RuntimeError` causes the code to fall through to the `brentq` fallback with bracket `[0.01, 0.9999]`. `brentq` will then correctly raise `ValueError` (no sign change in bracket) and the function returns `(None, None)`.

This check is not in the original grill-session design doc — add it whenever implementing a Newton-primary / brentq-fallback yield solver.
