---
title: "MMF/liquidity holdings must not appear in gated_trades — risk gate applies concentration check"
tags: [security-selection, risk-gate, mmf, concentration]
date: 2026-05-29
---

## Problem

`risk_gate_trades` applies a concentration check to every `GatedTrade` with
`gate_outcome != "red"` and `delta_value_gbp > 0`. This includes MMF buy trades.

After a gilt sell, the MIP routes proceeds to the liquidity_reserve (MMF) bucket.
If the MMF buy trade is included in `gated_trades`, the risk gate sees it as a
position with, say, 41% weight (> `max_single_position_pct = 25%`) and blocks it —
then `apply_risk_gate_to_proposed_state` reverts MMF back to its current value and
routes the freed cash back to MMF, creating a circular no-op.

## Solution

Exclude MMF/liquidity holdings from `gated_trades` entirely. The MIP handles them
as continuous "slack" variables (no binary, no commission, no minimum trade),
and their proposed values are derived from the cash-balance identity:

```
mmf_net_delta = -(sum of non-MMF net deltas) + gilt_rounding_residual
```

This is applied directly to `proposed_state_df` after the solve, without creating
a `GatedTrade` object. The risk gate never sees the MMF adjustment.

The split between non-MMF (binary + commission) and MMF (continuous + no-cost)
is how `security_selection.py` partitions `nm_indexed` vs `mmf_indexed`.
