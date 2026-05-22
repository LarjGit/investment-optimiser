---
title: "BoE spot curve ZIP contains multiple files and phantom trailing rows"
tags: [boe, yield-curve, openpyxl, excel, market-data]
date: 2026-05-22
---

## Problem

Three non-obvious facts about the BoE nominal spot curve ZIP archive
(`glcnominalddata.zip`) that would break a naive implementation:

**1. Multiple xlsx files, not one.**
The ZIP contains eight Excel files split by date range:
- `GLC Nominal daily data_1979 to 1984.xlsx`
- …
- `GLC Nominal daily data_2025 to present.xlsx`

`zf.namelist()` returns them in archive order (oldest first). Picking
`xlsx_names[0]` loads the 1979–1984 file. The current data is always in the
last alphabetically-sorted file.

**2. Sheet name differs between older and newer files.**
Files up to 2004 use `"4. nominal spot curve"`.
Files from 2005 onwards (including the current file) use `"4. spot curve"`.
Hardcoding either name works only for half the archive.

**3. Phantom trailing rows inflate `ws.max_row`.**
The 2025-to-present file reports `max_row=1607` but contains only ~348 rows
of real data. openpyxl in `read_only=True` mode trusts the XML `<dimension>`
element, which is wrong. The remaining ~1259 rows are phantom empty tuples
where every cell is `None`. A `deque(rows_iter, maxlen=60)` fills entirely
with these phantom rows, yielding zero usable data.

**4. Sheet layout has a 4-row preamble.**
Row 0: title (`'UK nominal spot curve'`). Row 1: empty. Row 2: `'Maturity'`.
Row 3: `('years:', 0.5, 1, 1.5, 2, …)` — the actual column-header row.
Row 4: all `'Refresh'` (formula placeholders). Data starts at row 5.

**5. Publishing lag.**
The Excel archive is updated with a lag of roughly 3–4 weeks. As of
late May 2026, the most recent data in the file is 2026-04-30. The IADB
CSV API (used for 5y/10y/20y) is updated daily with no meaningful lag.

## Solution

```python
# Pick the current file: last alphabetically = most recent date range
xlsx_names = sorted(n for n in zf.namelist() if n.endswith(".xlsx"))
xlsx_bytes = zf.read(xlsx_names[-1])

# Find the header row by detecting the first column whose second cell is 0.5
rows_iter = ws.iter_rows(values_only=True)
header = None
for row in rows_iter:
    if len(row) > 1 and isinstance(row[1], (int, float)) and float(row[1]) == 0.5:
        header = row
        break

# Filter phantom rows before deque — never feed rows_iter directly to deque()
recent: collections.deque = collections.deque(maxlen=60)
for row in rows_iter:
    if row[0] is not None:   # skip phantom empty rows
        recent.append(row)
```

The `row[0] is not None` guard also silently skips the `'Refresh'` formula
row and any holiday dates with no yields — both have `None` at date position
or are handled downstream by the `isinstance(date_val, datetime)` check.
