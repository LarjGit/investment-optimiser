---
section: data-ingestion
subsection: yfinance-refresh
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

### Scope change from Level 2

Yahoo Finance does not carry individual UK gilt securities. The yfinance batch therefore covers equities, ETFs, investment trusts, REITs, listed funds, and any other non-gilt exchange-traded holding that the classification layer maps to a Yahoo-supported ticker. Individual gilt prices for the full candidate universe come from the LSE price-explorer API. Portfolio gilt positions may also carry a CSV import price, but that is not the authoritative live market snapshot.

### Batch fetch pattern

```python
import yfinance as yf
import yfinance.shared as yf_shared

df = yf.download(
    equity_tickers,
    period="2d",
    interval="1d",
    multi_level_index=False,
    actions=False,
    progress=False,
)
latest = df["Close"].iloc[-1]
```

`period="2d"` is used instead of `1d` because some exchanges appear effectively T+1 in Yahoo data; taking the last non-null row gives the freshest available close.

### Per-ticker error handling

After the batch, inspect `yfinance.shared._ERRORS` to distinguish likely failure modes:

- **4xx / symbol not found** - treat as a per-ticker permanent miss, surface a named warning, and use the last cached SQLite price for that ticker if available
- **5xx or connection error** - retry once with `yf.Ticker(symbol).history(period="2d")`; if that also fails, fall back to cached price with a staleness warning
- **All-NaN row with no explicit error** - treat as transient and apply the same retry path

Per-ticker misses do not introduce extra `refresh_log.status` values. Source-level logging stays aligned with the persistence schema:

- write `status='completed'` for `source='yfinance_equities'` when the batch produced a usable daily snapshot, even if some tickers needed cached fallback
- write `status='failed'` only when the source run could not produce a usable equity snapshot at all
- include summary detail for degraded tickers in warnings and, where useful, in the source-level `error_msg`

### SQLite upsert pattern

Table shape:

```text
equity_price_cache(
    cache_date TEXT,
    ticker TEXT,
    close_price_gbp REAL,
    volume INTEGER,
    fetched_at TEXT,
    PRIMARY KEY (cache_date, ticker)
)
```

```sql
INSERT INTO equity_price_cache (cache_date, ticker, close_price_gbp, volume, fetched_at)
VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(cache_date, ticker)
DO UPDATE SET
    close_price_gbp = excluded.close_price_gbp,
    volume          = excluded.volume,
    fetched_at      = excluded.fetched_at;
```

`fetched_at` is stored as ISO8601 text.

### Staleness thresholds

The refresh layer applies independent freshness states per source:

- equity prices from `yfinance_equities`
- gilt prices from `lse_gilt_prices`

The dashboard warns after more than two trading days stale and escalates to error after more than five trading days stale. Neither state suppresses signals; the UI annotates freshness explicitly.

## Decisions Made

- yfinance fetches non-gilt exchange-traded holdings only; individual UK gilts are not on Yahoo Finance
- Single batch `yf.download(period="2d", multi_level_index=False, actions=False)` remains the primary fetch path
- `_ERRORS` is used to classify ticker-level failures; retries and cached fallback happen per ticker without inventing extra `refresh_log.status` values
- Source-level logging uses `refresh_log(source='yfinance_equities', status in ('completed', 'failed'))`
- `fetched_at` is stored as ISO8601 text; upserts use `INSERT ON CONFLICT ... DO UPDATE`
- Staleness thresholds stay independent for equity and gilt price sources

## Remaining Open Questions

None
