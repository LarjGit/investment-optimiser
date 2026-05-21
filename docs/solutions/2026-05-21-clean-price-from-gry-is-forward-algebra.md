---
title: "clean_price_from_gry is pure algebra — no root-finding needed"
tags: [gilt-analytics, scenario-engine, yield, pricing]
date: 2026-05-21
---

## Problem

`compute_gry` solves for yield given price using Newton/brentq. A fresh session implementing the inverse (price given yield) would likely reach for scipy optimizers again — either by inverting the root-finding or following the external research which recommends brentq for yield-to-price work.

## Solution

The price-from-yield direction is a pure forward computation. Given GRY `y`:

```
v = 1 / (1 + y/2)
dirty_price = v^(r/s) * (d1 + d2*v + c/f * v²/(1-v) * (1-v^(n-1)) + 100*v^n)
clean_price = dirty_price - accrued
```

No solver needed. The same cash-flow structure used inside `compute_gry`'s objective function is evaluated directly at the shocked yield. This is implemented in `gilt_analytics.clean_price_from_gry()`. The n=0 case (last coupon period) simplifies to `(d1 + 100) * v^(r/s)`.
