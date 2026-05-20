---
title: "Gilt maturity enrichment already existed at app layer; migration version needs bumping"
tags: [portfolio-import, enrich-with-buckets, migrations, gilt-maturity]
date: 2026-05-20
---

## Problem

A reasonable assumption when fixing gilt short/long bucketing was that maturity data
was completely absent from the enrichment path. In fact, `app.py` already contained
`enrich_holdings_with_maturity_years`, which joins `gilt_reference.maturity_date`
at render time and passes `maturity_years` into the holdings DataFrame before calling
`build_allocation_table`. The library-level function `enrich_with_buckets` was
deliberately designed to receive that pre-computed column from callers.

A fresh session could accidentally build a second enrichment path or conclude the
fix was unnecessary.

## Solution

The fix properly closes the footgun at the source: `maturity_date` is now stored
in `portfolio_snapshots` at import time (via `_ClassifiedAsset`, `_GiltReference`,
`_PersistedHolding`, and the INSERT/SELECT). `enrich_with_buckets` computes
`maturity_years` from the stored column automatically so callers no longer need
to do a separate join. The app-layer `enrich_holdings_with_maturity_years` remains
for backward compatibility but is now redundant.

**Migration version bump**: `test_app_smoke.py` asserts `user_version == N` where N
equals the length of the `MIGRATIONS` list. Every new migration must bump this
assertion, or the smoke test will fail with `assert N+1 == N`.

**Choke-point for gilt metadata**: `_ClassifiedAsset` is the right internal dataclass
to carry any new metadata that flows from `gilt_reference` through import and onto
`Holding`. Adding a field to `_GiltReference` and `_PersistedHolding` alone is not
enough — `_ClassifiedAsset` sits between them and must carry the value forward.
