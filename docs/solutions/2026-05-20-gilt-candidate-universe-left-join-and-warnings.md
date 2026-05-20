---
title: "Gilt candidate universe needs LEFT JOIN to surface unpriced reference gilts"
tags: [gilt-signals, candidate-universe, sqlite, streamlit]
date: 2026-05-20
---

## Problem

`fetch_gilt_ranking()` uses an INNER JOIN between `gilt_reference` and
`gilt_price_cache`. Gilts that exist in `gilt_reference` but have no entry in
`gilt_price_cache` (e.g. TIDM not yet resolved, or LSE price fetch failed for
that ISIN) are silently dropped. Planning a "full candidate universe" against
the existing signal function would produce a universe scoped only to already-priced
gilts, missing the acceptance criterion that the universe covers the full reference
scope with warnings for omissions.

## Solution

`build_gilt_candidate_universe()` uses a LEFT JOIN so every conventional gilt in
`gilt_reference` appears in the initial result set. Rows with `clean_price_gbp IS
NULL` after the join represent gilts in reference with no current price — these are
removed from the returned DataFrame and surfaced as a warning string instead.

The function returns `(pd.DataFrame, list[str])`. The DataFrame contains only priced
gilts (GRY may still be null). Unpriced gilts, gilts with price but missing analytics,
and gilts excluded by a maturity cutoff all become warning strings.

The app computes equivalent warnings from its Streamlit-connection queries by adding
a cheap `COUNT(*)` query against `gilt_reference` and comparing against the priced
count already in `gilt_ranking_rows` — no need to mix connection types in
`read_shell_state()`.
