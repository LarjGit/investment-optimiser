---
title: "_render_lp_recommendation requires full portfolio state before rendering results"
tags: [testing, streamlit, apptest, lp-recommendation]
date: 2026-05-21
---

## Problem

`_render_lp_recommendation` guards its display behind three early-return checks:
1. `if holdings.empty` — portfolio snapshot required
2. `if current_baseline is None` — strategic baseline required
3. `if state["gilt_ranking"].empty` — gilt price data required

These checks run **before** the code that reads and displays `allocation_runs` snapshot data. A fresh AppTest that seeds only an `allocation_runs` row (the natural minimal setup for testing blocked-trade display) will always hit the first guard and return early — showing no content from the recommendation section at all.

## Solution

To test the `_render_lp_recommendation` display path via AppTest, seed all three preconditions in addition to the `allocation_runs` row:
- `portfolio_snapshots` — at least one holding
- `strategic_baseline` — at least one baseline row
- `gilt_price_cache` + `gilt_reference` — at least one gilt price (to make gilt_ranking non-empty)

Alternatively, extract the pure display logic (trade categorisation, etc.) into a separate importable module and test it with unit tests. This is the preferred approach for pure functions — it is faster, more reliable, and avoids the full-state seeding requirement. The `blocked_trade_display.py` module (`categorise_blocked_trades`) follows this pattern.
