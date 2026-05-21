---
title: "LP recommendation module is where the full pipeline first runs end-to-end"
tags: [lp-recommendation, pipeline, architecture, risk-gate]
date: 2026-05-21
---

## Problem

Issues #27–#30 each built a library module (LP solver, holdings translator, trade construction, friction gate) but none wired them together. A fresh session might assume the pipeline was already connected, or might try to wire it in a different module.

## Solution

`lp_recommendation.py` is the single place that owns the full pipeline sequence:

```
solve_bucket_weights → translate_bucket_targets_to_holdings → construct_trades
→ gate_trades (friction) → apply_gate_to_proposed_state
→ risk_gate_trades → apply_risk_gate_to_proposed_state
```

It returns an `LPRecommendationResult` containing the `AllocationRunRecord` (ready to persist), the `trades_payload` (for display/audit), and the `executable_df` (the post-gate portfolio state). The app calls this module from the Scenarios tab and stores the result via `insert_allocation_run`. Downstream issues (#33 scenario compare, #34 change summary, #35 blocked-trade explanations) should read from `allocation_runs.snapshot_json → outputs` rather than re-running the pipeline.
