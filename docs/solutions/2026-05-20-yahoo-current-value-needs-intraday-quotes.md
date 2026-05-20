---
title: "Current-value refresh for Yahoo equities needs intraday quotes"
tags: [yahoo, yfinance, equities, refresh, dashboard]
date: 2026-05-20
---

## Problem
The Portfolio tab labels refreshed non-gilt values as `Current Value`, but the
existing Yahoo refresh path used `yf.download(..., period="2d", interval="1d")`
and persisted the latest daily bar under the local refresh date. For LSE equities
this can turn a previous close into an apparently current same-day quote after
midnight or before Yahoo rolls the daily bar forward.

That mismatch is user-visible and severe: a broker can show the live/current
holding value while the app shows the prior close and still labels it as current.

## Solution
Use a per-ticker intraday quote path first for refreshed equity prices. Persist
the quote's own market date from the returned timestamp, and only fall back to
the daily-bar batch when no live quote is available.

This keeps `Current Value` aligned with an actual live/intraday quote when Yahoo
can provide one, and prevents a stale daily bar from masquerading as today's
current price solely because the refresh ran on a later calendar date.
