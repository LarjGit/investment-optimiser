---
section: signal-layer
subsection: equity-signal-pe-source
phase: level3
status: complete
date: 2026-05-16
---

## Implementation Detail

### Canonical valuation source

The equity macro signal uses a single canonical valuation source:

- `https://www.blackrock.com/uk/individual/products/251795/ishares-core-ftse-100-ucits-etf`

This is the UK retail `ISF` page for the unhedged iShares Core FTSE 100 UCITS ETF, which tracks the FTSE 100 directly and exposes a dated `P/E Ratio` field in the public HTML. This is the best fit for the signal because:

- it is public and does not require login
- it is date-stamped at the field level
- it tracks the FTSE 100 directly
- it avoids the instability of Yahoo index metadata for valuation fields

Do **not** probe multiple ETF pages and pick the first success. The signal should have one auditable source and one parsing path.

### Transport and parsing approach

Primary source is the live HTML page, not a PDF factsheet.

Fetch the page over HTTPS with a normal browser-style `User-Agent`, then parse the `Portfolio Characteristics` block and extract:

- `P/E Ratio`
- the adjacent `as of` date for that field

Expected page pattern at time of research:

- `P/E Ratio`
- `as of 14/May/2026`
- `16.67`

The parser should search by label rather than fixed line offset, because the page is long and likely to shift structurally.

Suggested parsed record:

```python
@dataclass
class FtsePeSnapshot:
    source_url: str
    pe_ratio: float
    pe_as_of: date
    fetched_at: datetime
    source_name: str = "blackrock_isf_html"
```

### Freshness and fallback policy

The signal must distinguish three states:

1. **Fresh**: valid P/E parsed and `pe_as_of` is within the normal freshness window
2. **Degraded**: no fresh parse today, but a previously cached value exists and its `pe_as_of` is not older than 5 trading days
3. **Unavailable**: no valid parse and cached value is older than 5 trading days, or no cached value exists

If the live page fails to yield a valid P/E on refresh:

- fall back to the most recent cached `FtsePeSnapshot`
- mark the signal degraded
- show a visible stale-data warning in the dashboard

If the cached `pe_as_of` is older than 5 trading days:

- suppress the equity macro banner
- keep the card visible with a plain-English unavailable/stale explanation

The freshness decision is based on the field's own `as of` date, not just the HTTP fetch timestamp.

### Persistence contract

Successful parses are persisted in `equity_valuation_cache` with:

- `cache_date` - refresh date
- `source_name` - `blackrock_isf_html` in v1
- `pe_ratio`
- `pe_as_of`
- `fetched_at`

Source-level freshness is tracked separately in `refresh_log(source='blackrock_ftse_pe')` with the same terminal `completed` / `failed` contract used by the other remote refresh sources. The signal uses `pe_as_of` for valuation freshness decisions, while the dashboard uses `refresh_log` for operational source status.

### Numerical conversion and comparison rule

The source provides P/E, not earnings yield. Convert mechanically:

```python
equity_earnings_yield_pct = 100.0 / pe_ratio
```

The equity macro signal then compares:

- `equity_earnings_yield_pct`
- `best_conventional_gilt_gry_pct`

Signal condition:

```python
fires = equity_earnings_yield_pct < best_conventional_gilt_gry_pct
```

No extra smoothing or thresholding belongs in this adapter. This module's job is only to provide a clean, explicit earnings-yield input. Persistence/debouncing belongs in the signal state machine.

### Scope boundaries

- This sub-section does **not** rebuild FTSE 100 earnings yield from constituents
- This sub-section does **not** use `yfinance.info` or `fast_info` for FTSE valuation metrics
- This sub-section does **not** mix in dividend yield or total shareholder yield
- This sub-section does **not** own signal history, deduplication, or clear-state transitions

### Failure handling

- If the HTML fetch fails: use cached snapshot if within 5 trading days, else mark unavailable
- If `P/E Ratio` label is present but value parse fails: treat as failed parse, not zero
- If parsed `pe_ratio <= 0`: reject as invalid and mark failed parse
- If the best conventional-gilt GRY is unavailable on the same run: suppress the banner and show the equity card as blocked by missing gilt comparison input

## Decisions Made

- Canonical source is BlackRock UK `ISF` HTML page only
- Primary transport is live HTML, not PDF factsheet
- Parse the dated `P/E Ratio` field from `Portfolio Characteristics`
- Cache the parsed P/E snapshot in `equity_valuation_cache` with both `pe_as_of` and `fetched_at`
- Use cached P/E for up to 5 trading days on source failure; mark signal degraded during fallback
- Suppress the equity macro banner once cached P/E is older than 5 trading days
- Convert with `equity_earnings_yield_pct = 100 / pe_ratio`
- Fire when derived trailing earnings yield is below best conventional-gilt GRY
- Keep this adapter simple; debouncing/state belongs in the signal state machine

## Remaining Open Questions

None
