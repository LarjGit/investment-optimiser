---
title: "LP solver: turnover limit and tilt bands can jointly produce infeasibility"
tags: [lp-solver, turnover, tilt-bands, testing]
date: 2026-05-20
---

## Problem

A test for "turnover limit prevents large shifts" used a starting position of
100% in `liquidity_reserve` with the standard ±10% tilt band and 15% turnover
limit. This is immediately infeasible: the tilt bands require `short_duration`
>= 10% and `long_duration` >= 10% (both currently 0%), which alone demands 20%
of total movement — exceeding the 15% budget before any other bucket moves.

The problem only becomes visible when you try to formulate the LP; the
constraint interaction is non-obvious from the policy parameters alone.

## Solution

When designing LP test cases that involve turnover constraints, verify that the
starting position can reach the tilt-band feasible region within the turnover
budget before asserting `solver_status == "optimal"`. The safe pattern is to
start from a position that is already within the tilt bands (e.g. baseline ±
something < tilt_band) so the turnover constraint is the only binding limit.

For issue #27, the test was redesigned: current holdings are long_duration 10%
above baseline and equities 10% below (both still within tilt bands), with a
strong score preference for equities. The 15% turnover cap then visibly binds
the shift.
