---
title: "yfinance returns EQUITY quoteType for UK investment trusts"
tags: [yfinance, non-gilt-reference, classification, investment-trust]
date: 2026-05-22
---

## Problem
UK closed-ended investment companies (investment trusts) such as Scottish Mortgage (SMT.L)
return `quoteType: "EQUITY"` from `yf.Ticker().info` — not a dedicated "INVESTMENT_TRUST"
type. A plan that assumed `quoteType` could distinguish investment trusts from ordinary
equities would produce silent misclassification.

## Solution
Within the `quoteType == "EQUITY"` branch, apply name-signal heuristics on the `longName`
field to detect investment trusts before defaulting to `equity`:

```python
_INVESTMENT_TRUST_SIGNALS = (
    "investment trust",
    "investment company",
    "trust plc",
    "it plc",
    "fund plc",
)
if any(signal in long_name for signal in _INVESTMENT_TRUST_SIGNALS):
    return "investment_trust", quote_type
```

For REITs, `sector == "Real Estate"` combined with `"REIT" in industry` is the reliable
discriminator (also under `quoteType == "EQUITY"`). The `ASSET_TYPE_OVERRIDES` dict in
`portfolio_import.py` is the intended escape hatch for trusts whose names don't match.
