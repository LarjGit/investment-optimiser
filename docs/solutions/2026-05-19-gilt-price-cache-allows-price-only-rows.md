---
title: "Allow gilt price cache rows before analytics exist"
tags: [gilt-price-cache, migrations, lse, gry, duration]
date: 2026-05-19
---

## Problem
Issue `#13` refreshes live LSE gilt prices, but issue `#14` computes GRY and
modified duration later. The existing `gilt_price_cache` schema required
`gry_pct` and `modified_duration_years` on every row, which would have pushed a
fresh plan toward either inventing placeholder analytics or incorrectly merging
the two issues into one slice.

## Solution
Make `gilt_price_cache.gry_pct` and `modified_duration_years` nullable and treat
price refresh as an explicit intermediate state. Issue `#13` persists today's
authoritative price snapshot for all known TIDM-mapped gilts with those
analytics left empty; issue `#14` can then fill them in from persisted price and
reference data. Keep the columns nullable even after the shared yield engine
exists so real solve failures can degrade gracefully instead of forcing fake
values or schema churn.
