---
title: "equity_valuation_cache has no benchmark_ticker or earnings_yield column"
tags: [equity-signal, sqlite, schema, testing]
date: 2026-05-20
---

## Problem

The system design doc describes `equity_valuation_cache` storing the benchmark `trailingPE`
and derived `earnings_yield` by fetch date and `source_name`. A reasonable assumption when
seeding test data or writing queries is that the table stores `benchmark_ticker` and
`earnings_yield` as columns. It does not.

The actual schema (as of initial migrations) is:

```sql
equity_valuation_cache (
    cache_date  TEXT NOT NULL,
    source_name TEXT NOT NULL,
    pe_ratio    REAL NOT NULL,
    pe_as_of    TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (cache_date, source_name)
)
```

`benchmark_ticker` is in the policy pack, not in this table. `earnings_yield` is derived
at query time, not stored. `pe_as_of` is the as-of date for the PE figure (not `fetched_at`).

## Solution

When seeding `equity_valuation_cache` in tests, use exactly these five columns.
When querying, derive `earnings_yield = 1 / pe_ratio` in Python rather than reading
a stored column. `fetch_equity_valuation()` in `equity_signals.py` returns the raw
`pe_ratio` — compute the earnings yield from that.
