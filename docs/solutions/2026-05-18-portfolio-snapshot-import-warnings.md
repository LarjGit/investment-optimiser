---
title: "Persist portfolio import warnings alongside snapshot rows"
tags: [portfolio-snapshots, ingestion, sqlite, warnings]
date: 2026-05-18
---

## Problem
Issue `#6` looked like a straightforward CSV import slice, but the existing
`portfolio_snapshots` table could not carry the row-level warning state that the
design doc's canonical holding model already allowed through `import_warning`.
Keeping warnings only in Streamlit session state would have made the import path
less auditable and would have broken replayability for later diagnostics.

## Solution
Extend `portfolio_snapshots` with a nullable `import_warning` column and persist
row-level parse warnings on the same authoritative snapshot rows as the imported
holdings. Surface those warnings in the UI from the import result, but keep the
database row as the durable source of truth so later slices can inspect import
quality without depending on ephemeral upload state.
