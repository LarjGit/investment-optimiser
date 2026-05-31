---
title: "Filtering gilt candidates from gilt_candidates_df breaks lot-rounding for held gilts"
tags: [security-selection, mip, lp-recommendation, lot-rounding, gilt]
date: 2026-05-30
---

## Problem

`select_trades` uses `_extract_gilt_prices(gilt_candidates_df)` to look up clean prices
for held conventional gilt lot-rounding. When `gilt_candidates_df` is filtered to only
unowned switch candidates (as done in `_filter_gilt_candidates`), held gilt ISINs are
absent from the dict. Lot-rounding is then silently skipped for all held conventional
gilt resizes, which may produce non-standard nominal amounts.

This manifests as a silent regression: tests pass (none check lot-rounding directly),
but production trades for held gilts are no longer rounded to standard £100 nominal lots.

## Solution

Add a separate `gilt_price_lookup_df` keyword-only parameter to `select_trades` that
defaults to `gilt_candidates_df`. `build_lp_recommendation` passes the full
`gilt_ranking_df` (which includes held gilt rows with their prices) via this parameter,
while `gilt_candidates_df` remains the pre-filtered candidates-only DataFrame.

```python
selection = select_trades(
    ...,
    gilt_candidates_df=filtered_candidates or None,
    gilt_price_lookup_df=gilt_ranking_df or None,
)
```

Inside `select_trades`:
```python
gilt_prices = _extract_gilt_prices(gilt_price_lookup_df or gilt_candidates_df)
```

Any future extension that passes a filtered `gilt_candidates_df` must also supply
`gilt_price_lookup_df` with the full gilt ranking to preserve lot-rounding.
