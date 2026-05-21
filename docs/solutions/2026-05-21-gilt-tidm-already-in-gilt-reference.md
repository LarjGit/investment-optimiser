---
title: "TIDM is already in gilt_reference — use it, don't match by maturity date"
tags: [gilt-reference, tidm, isin, scenario-engine, gilt-signals]
date: 2026-05-21
---

## Problem

When building the scenario engine, gilt holdings in `portfolio_snapshots` are identified by symbol (TIDM, e.g. "TR27"), while yield and coupon data in `gilt_price_cache` is keyed by ISIN. The initial plan proposed matching by maturity date as a workaround to bridge the gap without a schema change.

## Solution

`gilt_reference` already has `tidm TEXT UNIQUE` (with an index). The `gilt_signals.py` queries join `gilt_price_cache` to `gilt_reference` but simply did not SELECT `r.tidm`. Adding `r.tidm` to both `_RANKING_SQL` and `_CANDIDATE_SQL` gives the gilt_ranking_df a proper TIDM column. The scenario engine (and any future module needing ISIN↔TIDM bridging) can match directly by `symbol == tidm` — no schema migration, no maturity-date heuristic.
