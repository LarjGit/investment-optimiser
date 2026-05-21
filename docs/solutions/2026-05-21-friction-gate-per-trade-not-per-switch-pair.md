---
title: "Friction gate evaluates buy trades individually, not switch pairs"
tags: [friction-gate, trade-construction, design]
date: 2026-05-21
---

## Problem

The system design formula describes friction for a "round-trip switch" as `(2 × commission) + spread + stamp_duty`. Individual `Trade` objects represent single legs, and there is no explicit switch-pair tagging. A fresh session might attempt to detect switch pairs (e.g. by matching equal and opposite deltas in the same bucket) before computing friction, or might apply commission once per trade and miss that switches need 2×.

## Solution

The friction gate evaluates buy trades (delta > 0) independently:

- **Commission = 2 × fee** for all buy trades (conservative round-trip assumption — always assumes a sell leg exists). This matches the system design formula without requiring switch-pair detection.
- **Sell trades** receive `gate_outcome = "not_gated"` and are always approved. They carry no independent yield improvement and are not subject to break-even gating.
- **Fallback proposed state**: red-gated buys revert to `current_value_gbp`; the freed delta is added to `liquidity_reserve`. This means a blocked switch leaves the new position untaken and any freed cash in MMF — a valid conservative fallback even without reverting the sell leg.

Full switch-pair blocking (reverting both sell and buy legs when the gate is red) is deferred to a future issue and would require explicit pair tagging in `Trade` or `TradeConstructionResult`.
