---
title: "LSE has no public bulk TIDM endpoint; dividenddata.co.uk cross-reference is the correct v1 approach"
tags: [lse, tidm, bridge, market-data, dividenddata]
date: 2026-05-19
---

## Problem

The system design states the TIDM bridge "refreshes monthly from the LSE bulk price-explorer endpoint." A reasonable assumption is that a programmatic URL exists for this. It does not.

The LSE Daily Tradable Instruments (DTI) report covers all instruments including TIDMs and ISINs, but it is delivered via LSEG's commercial Managed File Transfer (MFT) service — not a public HTTP endpoint. The price-explorer UI has no documented CSV export API. Community scrapers target individual equity pages and are fragile.

## What does NOT work: OpenFIGI

OpenFIGI (`POST https://api.openfigi.com/v3/mapping`, `idType: "ID_ISIN"`, `micCode: "XLON"`) looks plausible but returns Bloomberg-style bond descriptors in the `ticker` field for government bonds — e.g. `"UKT 0 1/2 10/22/61"` — not the short LSE TIDM (`TG61`). This is consistent with OpenFIGI's documentation, which shows US Treasuries returning `"ticker": "T 2 08/15/25"`. OpenFIGI tickers are Bloomberg-derived, not LSE TIDM-derived. Do not attempt this path again.

## Solution

Cross-reference two public HTML pages from dividenddata.co.uk against the ISIN data already in `gilt_reference` from the DMO import.

| Page | Gilts | Coupon format |
|------|-------|---------------|
| `https://www.dividenddata.co.uk/uk-gilts-prices-yields.py` | ~73 conventional | Fractional: `"1 1/2%"` |
| `https://www.dividenddata.co.uk/index-linked-gilts-prices-yields.py` | ~32 index-linked | Decimal: `"1.25%"` |

Both pages share the same column layout: `EPIC(0), Name(1), Coupon(2), Maturity Date(3), …`

The join key is `(coupon_pct, maturity_date)` — already present in `gilt_reference` from the DMO import. UK gilts never share both coupon and maturity date, so this is a clean unique key.

### Implementation summary

1. Fetch both HTML pages (2 HTTP requests, no API key, plain HTML tables).
2. Parse each page: convert fractional coupon text to float, convert `"DD-MMM-YYYY"` maturity to `"YYYY-MM-DD"`.
3. Build `{(coupon_pct, maturity_date): tidm}` lookup.
4. `SELECT isin, coupon_pct, maturity_date FROM gilt_reference` and for each row look up the TIDM.
5. `UPDATE gilt_reference SET tidm = ? WHERE isin = ?`.

A bundled `tidm_cache.csv` acts as a local fallback if dividenddata is unreachable. On fallback, the CSV is parsed and applied by ISIN directly.

When implementing any LSE TIDM slice:
- Do not assume OpenFIGI returns the short TIDM for UK government bonds — it does not.
- Do not attempt to scrape 100 individual HL gilt pages (fragile, slow).
- dividenddata.co.uk is the correct free programmatic source.
