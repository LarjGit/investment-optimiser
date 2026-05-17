---
section: data-ingestion
subsection: csv-normalisation
phase: level3
status: complete
date: 2026-05-15
---

## Implementation Detail

### BOM and encoding
Read with `encoding='utf-8-sig'`. This strips the UTF-8 BOM that ii includes in its CSV exports. No other encoding parameter is needed.

### Totals row stripping
Do not use `skipfooter`. After reading the full DataFrame, drop any row where `Symbol` is NaN or `Name` contains `"totals"` case-insensitively. This survives blank trailing lines and future ii footer variations.

### Column mapping config
A plain Python dict `II_COLUMN_MAP` defined in `ingestion/adapters/ii.py` maps raw ii column names to canonical internal names. A second set `II_REQUIRED_COLUMNS` lists columns that must be present. Both are module-level constants; no YAML or external config file is required.

Example shape:

```python
II_COLUMN_MAP = {
    "Symbol": "symbol",
    "Name": "name",
    "Quantity": "qty",
    "Price": "_raw_price",
    "Market Value": "market_value_gbp",
    "Book Cost": "book_cost_gbp",
}
II_REQUIRED_COLUMNS = {"Symbol", "Name", "Quantity", "Price", "Market Value", "Book Cost"}
```

### Hard fail on missing columns
At import time, before processing any rows, check that all `II_REQUIRED_COLUMNS` are present in the DataFrame. If any are missing, raise `IngestionError` with a message listing exactly which columns were expected, which are missing, and which were actually found.

### Price format parsing
A single `parse_price(raw: str) -> float | None` function handles all formats:

- Strip leading `GBP` or `£` marker and parse directly for gilt clean prices per GBP1 nominal
- Strip trailing `p`, remove commas, divide by 100 for pence-quoted holdings
- Return `None` on parse failure and let the row continue with `import_warning`

The parser stays self-contained and does not branch on asset type.

### Asset type classification
Classification runs as a cascade after price parsing:

1. **`ASSET_TYPE_OVERRIDES` first** - keyed by symbol, value is the final persisted asset type. Manually maintained in `ingestion/adapters/ii.py`.
2. **MMF** - if `Name` contains `"money market"` case-insensitively, classify as `mmf`.
3. **Gilt** - if `symbol` resolves through the DMO plus LSE bridge reference, classify as `gilt_index_linked` or `gilt_conventional`.
4. **Non-gilt instrument map** - consult a maintained symbol-to-class map for `equity`, `etf`, `investment_trust`, `reit`, `fund`, or `other`.
5. **Secondary metadata fallback** - if no explicit map entry exists, use lightweight exchange-traded metadata or name heuristics to infer a broad class where it is obvious.
6. **Safe fallback** - classify as `other` and populate `import_warning` instructing the user to add an override or map entry.

`exchange_traded` is not a persisted asset type. The ingest layer must emit the categories required by persistence, friction, and sleeve logic. A new symbol can still enter the system without breaking import, but until it is classified beyond `other`, only generic pricing and display behaviour should apply.

If the DMO table has not yet been downloaded on first run, potential gilt symbols remain importable but should carry `import_warning` and be revisited after the monthly reference refresh rather than silently masquerading as a generic exchange-traded asset.

### Canonical Holding dataclass

```python
@dataclass
class Holding:
    symbol: str
    name: str
    asset_type: str          # gilt_conventional | gilt_index_linked | mmf | equity | etf | investment_trust | reit | fund | other
    qty: float               # nominal face value (GBP) for gilts; share count for everything else
    clean_price_gbp: float   # per GBP1 nominal for gilts; per share in GBP for most other holdings
    market_value_gbp: float  # taken directly from ii CSV - authoritative
    book_cost_gbp: float
    import_warning: str | None = None
```

`market_value_gbp` is always taken from the ii CSV rather than recomputed from `qty x clean_price_gbp` because ii already captures accrued interest and other adjustments.

`__post_init__` checks for impossible states such as NaN market value or empty symbol and populates `import_warning` rather than raising, so one bad row does not block the rest of the import.

### Soft warn on per-row failure
If price parsing returns `None` or any row-level check fails, the `Holding` is still created with `import_warning` set. The row appears in the portfolio table with a visible warning indicator. The rest of the import continues.

## Decisions Made

- `encoding='utf-8-sig'` for BOM; no `skipfooter`; totals row filtered by content
- `parse_price()` stays self-contained; no asset-type dependency inside the parser
- `II_COLUMN_MAP` and `II_REQUIRED_COLUMNS` remain module-level constants in the ii adapter
- `IngestionError` is raised immediately if required columns are missing
- Per-row failures populate `import_warning`; import continues
- Classification cascade: overrides -> MMF -> DMO-backed gilt resolution -> non-gilt class map -> metadata heuristics -> `other`
- Persisted asset classes must align with downstream storage and analytics; `exchange_traded` is not a final category
- New or ambiguous symbols remain importable via `other`, but they surface an explicit warning until classified
- `Holding` dataclass keeps `market_value_gbp` from the CSV rather than recomputing it

## Remaining Open Questions

None
