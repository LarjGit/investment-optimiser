---
title: "Yahoo non-gilt prices need raw closes and quote-currency normalisation"
tags: [yahoo, yfinance, prices, market-data]
date: 2026-05-19
---

## Problem
Yahoo Finance looks like a straightforward daily close source for UK non-gilt
holdings, but two defaults can silently produce the wrong persisted
`close_price_gbp`.

First, current `yfinance` defaults to adjusted prices unless `auto_adjust=False`
is passed explicitly. That is the wrong default for a valuation cache, which
should persist the observable market close rather than a corporate-action-
adjusted series.

Second, UK Yahoo quotes are not guaranteed to arrive in pound units. Some LSE
symbols are quoted in `GBp`, so persisting the raw close as GBP without
normalisation can inflate stored prices by 100x.

## Solution
For the non-gilt Yahoo refresh:

- call `yf.download(..., auto_adjust=False, period="2d", interval="1d")`
- inspect per-ticker quote currency separately
- normalise `GBp` or `GBX` quotes to pounds before writing
- reject unsupported currencies with a warning instead of silently persisting a
  wrong GBP value

This keeps `equity_price_cache.close_price_gbp` aligned with the schema
contract and avoids silent valuation errors.
