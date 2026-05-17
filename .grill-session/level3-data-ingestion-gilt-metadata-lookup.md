---
section: data-ingestion
subsection: gilt-metadata-lookup
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

### Data Source: DMO XML

`GET https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1A` for conventional gilts and `GET https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1D` for index-linked gilts.

The XML feed is the authoritative source for:

- ISIN
- instrument name
- maturity date
- instrument type
- dividend dates
- current ex-dividend date
- DMO maturity bracket

No LSE TIDM field exists in the DMO XML. Standard browser-style headers are sufficient:

```python
headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/xml",
}
```

Use `timeout=(5, 30)`. Raw XML is written locally on successful refresh so the reference layer can be inspected and, if needed, used as a cold-start fallback.

### TIDM to ISIN bridge

The ii CSV uses LSE TIDMs such as `TR27`, while the DMO XML is keyed by ISIN. A bridge table is therefore required.

Bootstrap seed:

- ship `data/tidm_cache.csv`
- two columns: `ISIN`, `TIDM`
- seeded from a known-good gilt universe snapshot

Monthly refresh uses the LSE bulk price-explorer endpoint:

```text
POST https://api.londonstockexchange.com/api/v1/components/refresh
```

Run this in the same monthly refresh cycle as the DMO reference update, but log it as its own source (`lse_tidm_bridge`) rather than folding it into the `dmo_reference` row. If the live bridge call fails, keep the seeded cache or prior bridge data available as fallback and record the failure in `refresh_log`.

For any ISIN not resolved by the bulk bridge, a per-ISIN search fallback may still be used.

### Coupon parsing

`INSTRUMENT_NAME` embeds the coupon in one of several formats:

1. ASCII fraction, such as `4 1/8% Treasury Gilt 2027`
2. Unicode vulgar fraction display variants
3. Plain decimal
4. Whole number

Parse in that order. On no match, raise a warning-level parsing failure for that instrument and skip it rather than guessing a coupon and corrupting GRY outputs.

### Storage: `gilt_reference`

Parsed rows are stored in the `gilt_reference` table with:

- `isin`
- `tidm`
- `instrument_name`
- `coupon_pct`
- `maturity_date`
- `dividend_months`
- `dividend_day`
- `ex_div_date`
- `instrument_type`
- `maturity_bracket`
- `last_updated`

Monthly refresh uses full replacement for this table inside a short write transaction.

### Monthly refresh trigger

At startup and on manual refresh, check `refresh_log`:

```sql
SELECT 1
FROM refresh_log
WHERE source = 'dmo_reference'
  AND status = 'completed'
  AND strftime('%Y-%m', finished_at) = strftime('%Y-%m', 'now')
LIMIT 1
```

If no row is found, trigger the monthly reference refresh through the coordinator. On success:

- write the raw XML cache
- replace `gilt_reference`
- insert a terminal `refresh_log` row with `source='dmo_reference'` and `status='completed'`

The TIDM bridge attempt records its own `refresh_log` row with `source='lse_tidm_bridge'`.

If the live bridge call fails but the seeded `data/tidm_cache.csv` or prior bridge data still yields a usable mapping set, the reference refresh may still complete successfully while the bridge failure remains visible in the separate `lse_tidm_bridge` log row. If the DMO fetch itself fails, record `status='failed'`, fall back to the last successful local reference data if present, and surface the stale-reference warning through the dashboard freshness layer.

### First run behaviour

If `gilt_reference` is empty and no local XML cache exists, surface a hard error that reference data is unavailable and halt the gilt-analytics path. App-level rendering may continue for unaffected sections, but GRY-dependent analytics cannot proceed.

## Decisions Made

- DMO XML is fetched directly with normal browser-style headers and `timeout=(5, 30)`
- TIDM comes from the LSE bulk endpoint, not the DMO feed; it refreshes in the same monthly cycle but is logged as source `lse_tidm_bridge`
- Bootstrap seed `data/tidm_cache.csv` ships with the repo so first run can still resolve the universe when the live bridge is unavailable
- Coupon is parsed from `INSTRUMENT_NAME`; unrecognised formats are skipped with a logged warning
- `DIVIDEND_DATES` and `CURRENT_EX_DIV_DATE` remain the authoritative dividend-calendar source for accrued-interest logic
- Parsed reference data is stored in `gilt_reference`; raw XML and the TIDM seed are both retained locally as fallbacks
- Monthly refresh uses full replacement for `gilt_reference`
- Monthly freshness is checked from `refresh_log(source='dmo_reference')` using `finished_at`; bridge failures are visible separately in `refresh_log(source='lse_tidm_bridge')`

## Remaining Open Questions

None
