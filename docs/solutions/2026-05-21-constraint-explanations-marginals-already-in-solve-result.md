---
title: "Marginals are already in LPSolveResult — just wire them through the snapshot"
tags: [lp-solver, constraint-explanations, snapshot, diagnostics]
date: 2026-05-21
---

## Problem

Issue #36 asks for binding-constraint explanations including shadow prices. A fresh session might assume shadow prices need to be added to the LP solve itself, or might look for a way to re-run the solver to extract them.

## Solution

`lp_solver.py` already computes and returns `marginals: dict[str, float]` in `LPSolveResult` — populated from `res.ineqlin.marginals`, `res.lower.marginals`, and `res.upper.marginals` via scipy HiGHS. The only gap was that `lp_recommendation.py` passed `lp_result.binding_constraints` to the snapshot but discarded `lp_result.marginals`.

The pattern for adding new diagnostic data to downstream display is always:
1. Confirm the data exists in `LPSolveResult` (read `lp_solver.py`)
2. Add it to `_build_snapshot` in `lp_recommendation.py` via a new keyword-only param with `None` default
3. Store it in `snapshot["diagnostics"]` (no schema validation change needed — validator only checks required fields)
4. Read from `diagnostics` in the UI with a graceful fallback for old runs

New pure-logic modules (like `constraint_explanations.py`) should take `bucket_labels: dict[str, str]` as a pre-extracted param rather than extracting from policy internally — the caller already has this dict.
