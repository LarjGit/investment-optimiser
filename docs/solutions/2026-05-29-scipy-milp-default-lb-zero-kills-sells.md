---
title: "scipy.optimize.milp default lb=0 silently prevents negative (sell) variables"
tags: [scipy, milp, mip, security-selection]
date: 2026-05-29
---

## Problem

`scipy.optimize.milp` defaults all variable lower bounds to **0**, not −∞.
Any variable intended to represent a sell (negative delta) or a signed change will
be silently clamped at zero, producing a wrong but status=0 (optimal) result.

This is the top gotcha when using `milp` for portfolio rebalancing: a formulation
that uses a single signed `x_i` variable for net trade would receive `lb=0` on all
`x_i` and would never be able to sell anything.

## Solution

Always pass an explicit `Bounds` object to `milp`:

```python
from scipy.optimize import Bounds, milp

bounds = Bounds(lb=lb_array, ub=ub_array)
result = milp(c, constraints=constraints, integrality=integrality, bounds=bounds)
```

The workaround used in `security_selection.py` is to split the signed trade into
`x_plus[i] ≥ 0` (buy) and `x_minus[i] ≥ 0` (sell), both with natural non-negative
bounds. The big-M binary constraints then ensure at most one direction per position.

Also note: `milp` can return status=0 while the solution violates bounds
(known bug scipy#22812). Always verify `result.success` AND check solution bounds.
