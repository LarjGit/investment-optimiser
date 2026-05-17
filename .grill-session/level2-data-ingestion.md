---
section: data-ingestion
phase: level2
status: complete
date: 2026-05-15
---

## What We Established

### Portfolio CSV
The tool ingests a CSV downloaded directly from Interactive Investor (ii). The format uses Symbol (LSE ticker or platform symbol, e.g. `TR27`, `ADM`), Name, Qty, Price, Market Value, Book Cost, and other platform-provided columns. Prices are mixed format: gilts show GBP clean price per GBP1 nominal, while most exchange-traded holdings show pence with a trailing `p`. The file has a UTF-8 BOM and a Totals row at the bottom that must be stripped.

The ingestion layer is a normalisation adapter, not a fixed ii parser. It maps raw platform columns to a canonical internal schema `(symbol, name, asset_type, qty, clean_price_gbp, market_value_gbp, book_cost_gbp)`. The ii format is the first adapter; others can be added later by extending the mapping configuration.

### Asset Type Classification
Asset type is inferred from Symbol and Name because the ii CSV has no explicit type column. The owning ingestion model must emit the persisted asset classes used downstream, not a generic `exchange_traded` catch-all. The authoritative categories are:

- `gilt_conventional`
- `gilt_index_linked`
- `mmf`
- `equity`
- `etf`
- `investment_trust`
- `reit`
- `fund`
- `other`

Classification therefore uses a layered approach: overrides first, DMO lookup for gilts, MMF name rules, then a maintained non-gilt instrument classification map with secondary metadata heuristics only as a fallback. Newly seen exchange-traded symbols may still be priced through Yahoo Finance, but they fall back to `other` with an explicit warning until classified well enough for class-specific friction and sleeve logic.

The persisted `asset_type` taxonomy stays limited to the categories above. Friction-specific distinctions that cut across that taxonomy, especially `gilt_etf` and `corporate_bond`, are owned by a separate derived friction-routing layer built from the same maintained symbol metadata and overrides. In other words, a gilt ETF still persists as `etf`, but the friction model may route it to the `gilt_etf` spread bucket without widening the stored enum.

### Gilt Metadata
GRY calculation requires exact coupon and maturity date, which are not reliably derivable from the name string alone. The DMO "Gilts in Issue" feeds are the authoritative metadata source for coupon, maturity date, coupon calendar, and instrument type. The DMO feed does not carry TIDM, so the ingestion section also owns the LSE TIDM/ISIN bridge used to join ii symbols to DMO reference rows. DMO metadata is refreshed monthly; the bridge is refreshed in the same monthly cycle but logged as its own source.

### Market Data Sources
- **Individual UK gilts**: live prices come from the LSE price-explorer API, not Yahoo Finance. That source owns the daily market snapshot for the held-gilt comparison, the full gilt candidate universe, and GRY computation inputs.
- **Non-gilt exchange-traded holdings**: equities, ETFs, investment trusts, REITs, listed funds, and similar symbols are fetched through batch `yfinance` calls with an `.L` suffix where required.
- **FTSE 100 valuation snapshot**: the dated `P/E Ratio` used by the equity macro signal comes from the public BlackRock UK `ISF` HTML page. The refresh path parses `pe_ratio` plus the field-level `pe_as_of` date and persists that snapshot in SQLite for deterministic fallback behaviour.
- **MMF positions**: no exchange ticker is assumed. Market value comes from the imported CSV; running yield is modelled from the BoE base rate.
- **BoE yield curve and base rate**: six maturity points (`1y`, `2y`, `5y`, `10y`, `20y`, `30y`) plus base rate are fetched daily via the BoE CSV API. Exact series codes are implementation constants owned by the refresh-source module rather than an unresolved design question.
- **DMO gilts-in-issue plus LSE bridge data**: monthly refresh, cached locally, and used as the reference layer behind all gilt analytics.

### Daily Refresh Mechanism
Refresh runs through the persistence-layer coordinator on app startup when today's data is missing, and it can also be triggered manually from the dashboard. The coordinator first normalises the saved `data/portfolio_latest.csv` into today's `portfolio_snapshots`, then refreshes remote sources independently, then evaluates and persists `signal_readings` and `signal_events` from the latest stored data. Remote refresh is per source, not all-or-nothing: a failure in one source does not block successful writes for the others. Freshness is determined from the latest successful `refresh_log` row for each remote source.

### Staleness Handling
Stale data is shown with visible per-source warnings rather than hidden. Threshold: more than 2 trading days stale triggers warning state; more than 5 trading days stale triggers error state. Signals remain visible at all staleness levels; the UI annotates degraded freshness rather than suppressing the analysis.

### CSV Import Mechanism
The Streamlit app exposes a `st.file_uploader` widget. When a new CSV is imported it is saved to `data/portfolio_latest.csv` and persists across app restarts. On startup, the app reads from this saved file. No folder-watching is needed; the import action is explicit.

The dashboard itself does not read the CSV directly after upload. The saved file becomes the local source for the persistence-layer import step, which parses and upserts today's `portfolio_snapshots` before downstream signals and allocation views query the database.

## Decisions Made

- Flexible normalisation adapter, not a fixed ii parser
- Asset type inferred from Symbol and Name into the downstream persisted categories; no generic `exchange_traded` type survives into storage
- Persisted `asset_type` stays narrow; friction-only distinctions such as `gilt_etf` and `corporate_bond` are routed through derived metadata/overrides rather than added to the stored enum
- Live individual gilt prices come from the LSE price-explorer API; Yahoo Finance is only for non-gilt exchange-traded holdings
- The dated FTSE 100 P/E input comes from the BlackRock `ISF` HTML page and is cached in SQLite with both `pe_as_of` and `fetched_at`
- MMF yield = BoE base rate; MMF market value comes from the imported CSV
- BoE API supplies the six curve points and base rate in the daily refresh path
- DMO gilt metadata plus the LSE TIDM bridge form the monthly-refreshed gilt reference layer
- Startup and manual refresh both run through the persistence refresh coordinator; the saved CSV is first normalised into `portfolio_snapshots`, then remote sources refresh with per-source logging
- Stale data is shown with warnings/errors by source; signals are not suppressed
- File uploader saves to `data/portfolio_latest.csv` for persistence

## Sub-section Map

- [x] csv-normalisation - BOM handling, price format parsing (pence/pounds), totals-row stripping, asset type detection rules, column mapping config
- [x] gilt-metadata-lookup - DMO download, coupon/maturity extraction, Symbol-to-DMO matching, monthly cache refresh
- [x] yfinance-refresh - batch fetch pattern, rate limiting, per-ticker error handling, staleness timestamp storage in SQLite

## Remaining Open Questions

None
