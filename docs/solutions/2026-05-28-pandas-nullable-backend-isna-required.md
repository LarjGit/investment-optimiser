---
title: "Use pd.isna() for null checks on values from DataFrame.to_dict('records') with nullable backend"
tags: [pandas, nullable-backend, null-check, scenario-engine]
date: 2026-05-28
---

## Problem

The codebase uses `numpy_nullable` dtype backend (`dtype_backend="numpy_nullable"`)
when querying the database via `pd.read_sql_query`. With this backend, missing
values in Float64/Int64/string columns are stored as `pd.NA`, not `numpy.nan`
or `None`.

When `DataFrame.to_dict("records")` is called on such a DataFrame, missing
values appear as `pd.NA` in the resulting dicts. The following checks all fail
silently or raise `TypeError`:

```python
value is None          # False for pd.NA — misses it
value != value         # returns pd.NA, not True — falsy trap
math.isnan(value)      # TypeError on pd.NA
numpy.isnan(value)     # TypeError on pd.NA
```

This is the pattern the scenario engine uses when reading `real_gry_pct` out of
the gilt lookup dict built from `to_dict("records")`.

## Solution

Always use `pd.isna(value)` or `pd.notna(value)` for null checks on values
extracted from dicts that originated from a pandas DataFrame:

```python
real_gry_raw = row.get("real_gry_pct")
"real_gry_pct": None if pd.isna(real_gry_raw) else float(real_gry_raw),
```

This converts `pd.NA`, `numpy.nan`, `None`, and `float("nan")` all to `None`
at the boundary — normalising the sentinel before it propagates into pure-Python
code that won't handle `pd.NA`.

Apply this pattern anywhere a column from a `numpy_nullable`-backend DataFrame
flows through `to_dict("records")` into logic that checks for missing values.
