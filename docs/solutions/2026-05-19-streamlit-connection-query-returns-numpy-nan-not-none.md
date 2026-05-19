---
title: "Streamlit connection.query() returns np.nan for nulls, not None"
tags: [streamlit, pandas, nullable, signals]
date: 2026-05-19
---

## Problem

When using Streamlit's `connection.query()` to fetch rows from SQLite, nullable float
columns return `np.nan` for NULL values — not Python `None` and not `pd.NA`.

A null check written as `if value is not None` evaluates to `True` for `np.nan`
(because `np.nan is not None`), so code like:

```python
f"{value:.2f} yrs" if value is not None else "—"
```

silently produces `"nan yrs"` instead of the intended fallback `"—"`.

## Solution

Use `pd.notna(value)` (or `pd.isna(value)`) for any null guard on values that came
through `connection.query()`. This correctly handles `np.nan`, `None`, and `pd.NA`:

```python
f"{value:.2f} yrs" if pd.notna(value) else "—"
```

This requires `import pandas as pd` in the module — make that import explicit even
if pandas is used implicitly through Streamlit's query return type.
