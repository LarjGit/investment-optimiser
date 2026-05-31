---
title: "MIP bucket epsilon must be tight (0.5%) and MMF bucket must be excluded from constraints"
tags: [security-selection, mip, epsilon, mmf, constraint-formulation]
date: 2026-05-29
---

## Problem

Two related bugs caused the MIP to produce £0 improvement (no trades generated) in production.

### Bug 1 — epsilon too wide

`_BUCKET_EPSILON_PCT = 3.0` created a ±3% tolerance around each LP bucket target.
On an £89k portfolio that is ±£2,670 per bucket.  The LP was recommending 1–3% weight
shifts (£890–£2,670), which all fell within the band, so `required_delta ± epsilon`
included zero for every bucket.  The MIP trivially satisfied all constraints by doing
nothing.

### Bug 2 — MMF bucket constraint conflicts with non-MMF constraints

When the LP routes money through empty buckets (e.g., IL gilts with no current
holdings), the constraint for those buckets is skipped.  If the LP says "−7% long
gilts, +2% IL gilts (no holdings), +5% MMF", the remaining constraints are:

    long gilts: delta ∈ [−7,120, −3,560]   (i.e., required_delta=−6,230 ±2,670)
    MMF:        delta ∈ [+1,780, +7,120]   (i.e., required_delta=+4,450 ±2,670)

Via cash balance: mmf_delta = −gilt_delta.  If gilt_delta = −6,230 → mmf_delta = +6,230,
which is outside [+1,780, +7,120].  The constraints are **jointly infeasible**.  The MIP
would either fail or, if epsilon were wide enough to paper over the mismatch, silently
produce zero trades.

## Solution

### Fix 1 — tighten epsilon to 0.5%

    _BUCKET_EPSILON_PCT = 0.5

0.5% on £89k = £445, which comfortably absorbs gilt lot-rounding residuals (~£100 per
holding at most) while enforcing LP recommendations of ≥0.5% weight shifts.

### Fix 2 — skip MMF-only bucket constraints entirely

MMF level is always derived from the cash-balance identity post-solve:

    mmf_net_delta = −Σ nm_delta + total_rounding_residual

Adding a constraint for the MMF bucket in the MIP is both redundant and conflicting.
The fix is to `continue` in the bucket constraint loop whenever `nm_in_bucket` is empty
(whether the bucket is completely empty OR contains only MMF holdings).

After this change, only non-MMF, non-empty buckets get hard constraints.  The
cash-balance constraint ensures the total net trade across all nm variables sums to zero
(via the x_mmf slack), and the post-solve code assigns the correct MMF level.
