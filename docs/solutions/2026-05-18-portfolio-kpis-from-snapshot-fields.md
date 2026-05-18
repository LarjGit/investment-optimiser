---
title: "Limit initial portfolio KPIs to fields already persisted on snapshot rows"
tags: [portfolio, kpis, sqlite, streamlit]
date: 2026-05-18
---

## Problem
Issue `#7` sounds like a simple Portfolio-tab KPI task, but the design doc's richer
examples (`weighted-average duration` and `weighted-average GRY`) are not stored on
`portfolio_snapshots`. Planning against the design doc alone would suggest those
metrics were ready to render from holdings persistence, when in reality that would
have required extra joins or a larger analytics slice.

## Solution
Keep the first Portfolio-tab KPI slice anchored to fields already persisted on the
latest `portfolio_snapshots` rows: total market value, holding count, and other
simple holdings-derived percentages such as MMF share. That satisfies the
persisted-holdings requirement cleanly, keeps the UI honest about its data source,
and leaves duration or GRY for a later slice once those analytics are persisted or
joined intentionally.
