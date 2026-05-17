---
topic: investment-optimiser - UK SIPP portfolio allocation optimiser
phase: level1
status: complete
date: 2026-05-15
---

## Summary

The investment-optimiser is a local decision-support tool that helps the owner of a UK SIPP (~GBP100k+) determine how capital should be allocated across any SIPP-eligible asset class. The portfolio engine is whole-portfolio, hierarchical, and baseline-anchored: it can recommend reallocating across cash, MMFs, conventional gilts, index-linked gilts, ETFs, investment trusts, REITs, equities, funds, and other supported instruments while staying honest about which sleeves are strongly modelled and which are only bounded or monitored. Current holdings are implementation state, not policy truth, so the tool may recommend a material reshaping of the portfolio when the evidence supports it. The system is alert-driven, backed by a SQLite store, and surfaced through an on-demand Streamlit dashboard with scenario controls, friction assumptions, and trade diagnostics. It runs locally on the user's Windows machine, ingests the live portfolio from a manually updated CSV, and refreshes free public market data daily from BoE curve feeds, monthly DMO reference data, the LSE price-explorer API for live gilt prices, Yahoo Finance for non-gilt exchange-traded holdings, and the BlackRock `ISF` page for the dated FTSE 100 P/E snapshot used by the equity macro signal.

## Key Decisions & Constraints

- **Decision-support only** - recommends, user acts. No automated execution.
- **Open asset class scope** - any SIPP-eligible instrument is a valid recommendation: cash, money market funds, gilts (conventional and index-linked, any maturity), ETFs, investment trusts, equities, REITs, funds, and beyond.
- **Allocation architecture** - a whole-portfolio hierarchical allocator tilts around a user-authored strategic baseline; sleeves without a credible local model are bounded, tracked, and stress-labelled rather than fake-optimised.
- **Investment objective** - flexibility and optionality: potential drawdown within ~5 years, no desire to lock everything into 10+ year bonds, but willingness to hold long duration on part of the portfolio.
- **SIPP tax wrapper** - no CGT or income tax on internal transactions; maximise gross yield, not tax-adjusted yield; 25% tax-free lump sum already taken.
- **Platform** - Interactive Investor (ii) at GBP3.99/trade; friction model is parameterised but defaults to ii.
- **Data** - portfolio positions via manually updated CSV; BoE yield curve and base rate daily; DMO gilt metadata monthly; LSE price-explorer API for live gilt prices; Yahoo Finance for non-gilt exchange-traded holdings; BlackRock `ISF` HTML for the dated FTSE 100 P/E snapshot; no paid feeds.
- **Tech stack** - local Python, Streamlit dashboard, SQLite persistence.
- **No artificial phasing** - all four signals and the allocation engine are designed together unless there is a concrete technical reason to split.
- **Scenario modelling** - named deterministic scenarios with explicit adverse floors and side-by-side current versus executable recommended portfolios; no Monte Carlo in v1.
- **Alert delivery** - in-app Streamlit banners first; Windows Task Scheduler plus toast notification can be added later after the dashboard path is stable.

## Section Map

- [x] data-ingestion - Portfolio CSV schema, asset classification, BoE/DMO/LSE/Yahoo refresh inputs, daily refresh mechanism
- [x] allocation-engine - Whole-portfolio allocation policy, sleeve logic, optimisation rules, scenario simulation
- [x] signal-layer - Four signals: GRY ranking across gilts, yield-curve shape detection, duration/liquidity analysis, equity macro signal
- [x] friction-model - Transaction cost calculation (ii fees plus bid-offer spread), break-even yield improvement threshold, net-positive trade gate
- [x] dashboard-ux - Streamlit layout, knobs panel, signal alert display, scenario output tables, portfolio visualisation
- [x] persistence-layer - SQLite schema, daily portfolio snapshots, signal history, decision log with free-text notes

## Open Questions

None
