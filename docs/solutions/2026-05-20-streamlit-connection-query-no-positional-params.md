---
title: "connection.query() rejects positional ? params — fetch all and merge in Python instead"
tags: [streamlit, sqlite, sql, connection]
date: 2026-05-20
---

## Problem

`connection.query(sql, params=tuple(...))` with `?` positional placeholders raises:

```
pandas.errors.DatabaseError: List argument must consist only of dictionaries
```

The Streamlit SQLConnection uses SQLAlchemy's `text()` construct, which expects
named parameters (`:name` style) not positional `?` placeholders. Passing a tuple
triggers this error.

## Solution

Follow the pattern already used by `enrich_holdings_with_latest_non_gilt_prices`:
fetch the entire reference table without a WHERE filter and merge/filter in Python.

```python
# Instead of:
connection.query("SELECT ... WHERE isin IN (?,?,?)", params=tuple(isins))

# Do:
all_rows = connection.query("SELECT isin, maturity_date FROM gilt_reference", ttl=3600)
frame.merge(all_rows, on="isin", how="left")
```

The gilt_reference table is small (~50 rows) so fetching all rows is cheap and
benefits from the TTL cache. Named params (`:name` style with a dict) also work
but the fetch-all-and-merge pattern is simpler and consistent with the codebase.
