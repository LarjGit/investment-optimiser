---
title: "Use the existing portfolio snapshot ISIN column during holdings classification"
tags: [portfolio-import, classification, gilt-reference, sqlite]
date: 2026-05-19
---

## Problem
Issue `#12` looks like a pure taxonomy-classification task, but the codebase already
had two important persistence pieces in place: `portfolio_snapshots.isin` and the full
stored `asset_type` enum. The real gap was only in the importer. Without noticing that
up front, a fresh plan could easily invent a new schema change or keep gilt resolution
as transient in-memory state.

## Solution
Keep classification in the import path and use the existing `gilt_reference.tidm`
bridge to resolve broker symbols during import. Persist the resulting taxonomy on
`portfolio_snapshots.asset_type` and, when a gilt match is found, persist the matched
`isin` into the already-available `portfolio_snapshots.isin` column. This keeps the
import result authoritative without adding a new table or widening the holdings schema.
