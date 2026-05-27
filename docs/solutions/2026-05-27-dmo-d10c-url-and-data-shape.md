---
title: "DMO D10C URL has no www prefix and is per-gilt index ratios, not breakeven inflation"
tags: [dmo, inflation, index-linked-gilts, market-data]
date: 2026-05-27
---

## Problem

Two non-obvious facts about DMO D10C that contradict reasonable assumptions:

**1. URL subdomain differs from D1A.**
D1A uses `https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1A`.
D10C requires `https://dmo.gov.uk/data/XmlDataReport?reportCode=D10C` — no `www.` prefix.
Using `www.dmo.gov.uk` for D10C returns an error response, not data.

**2. D10C is not a breakeven inflation series.**
D10C delivers one record per IL gilt per settlement date containing:
- `INDEX_RATIO_OR_RPI` — the index ratio (e.g. 1.46186)
- `REFERENCE_RPI` child element — the interpolated daily RPI level (e.g. 408.20000)

This is the per-gilt, per-day pricing-state input. It is not a yield-curve-derived breakeven
inflation figure. Future analytics modules should treat `reference_rpi` as the observed RPI
applicable to a specific gilt on a specific settlement date, not as a market-implied
forward inflation rate.

The DMO D4O feed (`https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D4O`) provides monthly
observed RPI history if a monthly time series is needed instead.

## Solution

Use `_DMO_D10C_URL = "https://dmo.gov.uk/data/XmlDataReport?reportCode=D10C"` (no `www.`).

Store both `index_ratio` and `reference_rpi` per row in `observed_inflation_cache` so consumers
can use whichever field matches their calculation. The `reference_rpi` is the interpolated daily
RPI for that gilt's settlement date; `index_ratio` is the derived multiplier.
