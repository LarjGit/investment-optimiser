---
title: "Scope free LSE non-gilt classification refresh to symbols already known locally"
tags: [lse, non-gilt-reference, refresh, sqlite]
date: 2026-05-19
---

## Problem
Issue `#39` sounds like a straightforward "download an LSE reference file" task, but the clean LSE reference products (`Daily Tradeable Instruments`, `Datasync`) are paid Data Shop feeds rather than free public endpoints. The free public route is the website, and the company-page URL is not directly derivable from a symbol alone because it includes an issuer slug. Without noticing that upfront, a fresh plan could aim at a whole-exchange refresh shape that is both brittle and unnecessarily expensive in HTTP work.

## Solution
Treat the public-source refresh as a portfolio-scoped enrichment pass, not a full-market download. Build the symbol universe from the latest persisted `portfolio_snapshots` plus any already stored `non_gilt_reference` rows, resolve each symbol to a public LSE company page through the site search page, then parse the visible category label (`ETFs`, `Equity`, `Closed-ended investment funds`, etc.) into the app's fixed `asset_type` taxonomy.

This keeps the refresh aligned with the product's local-authoritative-state model:
- import stays offline and classifies from SQLite only
- refresh remains the only networked path
- the source is workable without pretending a free bulk endpoint exists
- the dataset grows as the user imports or tracks more symbols
