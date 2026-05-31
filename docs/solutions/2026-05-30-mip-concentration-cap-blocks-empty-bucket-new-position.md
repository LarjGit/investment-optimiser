---
title: "MIP concentration cap can make new-position constraints infeasible when bucket target > max_single_position_pct"
tags: [security-selection, mip, concentration, new-position, constraint]
date: 2026-05-30
---

## Problem

When a bucket is empty and the LP target for that bucket exceeds `max_single_position_pct`,
the new-position candidate variable `x_new[j]` is bounded at `max_position_gbp` but the
bucket constraint requires a delta of `target_value > max_position_gbp`. The MIP is then
infeasible even though the LP computed the target as valid.

Example: portfolio £40k, `max_single_position_pct=25%` (max £10k), LP target for empty
long-duration bucket = 30% (£12k). `x_new` is capped at £10k < £12k required → infeasible.

## Solution

Test scenarios for new-position MIP tests must keep the empty-bucket target within the
concentration limit. In production, the LP respects the concentration constraint
(`max_single_position_pct` is a default constraint in `lp_solver`), so the LP will never
produce a target that exceeds the cap for a single-security bucket. The issue only
surfaces in direct `select_trades` tests that bypass the LP.

No code change needed — the concentration limit is correct. Design tests so that
`target_pct ≤ max_single_position_pct` for any bucket with a single candidate.
