# External Tooling Research Brief
## For: Deep-Dive Research Document Agent

---

## The Real Question

The owner of this application is asking: **"I don't know what I don't know — am I doing this the right way, using the best modern tools, or am I reinventing wheels badly?"**

This is not a validation exercise. It is a genuine open review. You should approach it as a knowledgeable colleague who has just been handed the codebase and asked to give an honest second opinion. If a current architectural or library choice is wrong, suboptimal, or has been superseded by something better, say so clearly and say what to do instead. There is no attachment to the current implementation.

Your output is a single comprehensive research document saved to `docs/external-tooling-research.md`. It should be detailed enough that a developer can act on it without re-researching the basics. Include actual API shapes, code snippets where illustrative, version numbers, rate limits, cost, and honest maintenance health assessments.

---

## What This Application Is

A **local, Python/Streamlit decision-support tool for a UK SIPP portfolio** of roughly £100k+. It is a whole-portfolio investment optimiser — not a tracker, not a gilt-only tool. The user actively optimises and rebalances across the full range of SIPP-eligible asset classes:

- Conventional gilts
- Index-linked gilts (RPI-linked)
- Equities (UK and global, including ETFs, investment trusts, REITs, funds)
- Money market funds (MMF)
- Cash

**Core purpose**: given the current portfolio, market data, and a user-authored strategic baseline, recommend which trades to make — sized, friction-adjusted, and risk-gated — and explain why.

### Key design facts (from `docs/system-design.md`)

- **Recommendation-only**: user executes trades manually via Interactive Investor (£3.99/trade)
- **Whole-portfolio allocator**: anchored to a strategic baseline, not current holdings. Current holdings are implementation state, not policy truth
- **Solver**: `scipy.optimize.linprog(method='highs')` continuous LP. Linear attractiveness score objective. Constraints: full investment, long-only, baseline tilt bands, regime-aware turnover limits, concentration caps, MMF/cash floors, maturity caps, adverse-scenario floors
- **Friction model**: round-trip cost (commission + spread + stamp duty) gates every trade — green/amber/red against expected hold period
- **Risk gate**: final veto layer post-solve — concentration, liquidity, maturity policy
- **Scenario engine**: deterministic named scenarios (e.g. yield shock +100bps), exact cash-flow repricing for gilts, held-flat for unmodelled assets
- **Signal layer**: five cards — GRY switch opportunity, Equity Risk Premium vs gilts, Equity Opportunity composite score, Yield Curve shape (BoE 6-point), Duration/Liquidity alerts
- **Data sources (all free/public)**: DMO XML (gilt reference), LSE price-explorer API (gilt prices), Yahoo Finance (equities, benchmark PE), Bank of England CSV API (yield curve, base rate)
- **Persistence**: SQLite with WAL, 14 tables, append-only audit/decision history, replayable solver snapshots in JSON
- **Stack**: Python, Streamlit, uv, Windows, local-only, SQLite

### What has been built from scratch (assess each honestly)

The application currently hand-rolls several things that may or may not be the right approach. For each, the research document must give an honest verdict — **replace, augment, or keep as-is** — with justification. "Keep as-is" is a valid answer if the hand-rolled version is genuinely correct and a library would add unnecessary complexity. "Replace" is equally valid if a battle-tested library handles edge cases the current code might be missing.

| Component | Current approach |
|-----------|-----------------|
| GRY calculation | Newton/brentq solve from first principles, ICMA actual/actual, T+1 settlement, England & Wales bank holidays |
| IL gilt real GRY | RPI-uplifted redemption cash flow, Fisher equation for nominal equivalent, 3-month observation lag |
| Modified duration | Derived from the same cash-flow solve as GRY |
| Yield curve fetch | Direct HTTP to BoE CSV API, 6-point curve classification (normal/inverted/flat/humped) |
| DMO data ingestion | XML parse of two DMO report endpoints, coupon parsing from instrument name strings |
| TIDM–ISIN bridge | Seeded CSV + monthly LSE bulk price-explorer refresh |
| Portfolio allocator | `scipy.optimize.linprog(method='highs')` with hand-coded constraint matrices |
| Data persistence | SQLite with WAL, hand-written schema migrations via `PRAGMA user_version` |
| Dashboard | Streamlit single-file app, `layout="wide"` |

### V2 direction

V2 will add an **LLM market insight layer** — Claude reasoning over live market data and portfolio state to produce narrative analysis, regime commentary, and decision support. This means:

- MCP servers for live financial data are on the roadmap as real infrastructure, not hypotheticals
- The explanation layer already designed in the system (read-only over persisted state) is the natural integration point
- Claude plugin/skill architecture for domain-specific SIPP reasoning is directly relevant
- The agent should treat LLM/MCP tooling as a first-class v2 concern and research it accordingly

---

## Research Mandate

The focus is **tooling**: libraries, APIs, data sources, and MCP servers. For each item below, go deep — look at the actual GitHub repo, PyPI page, official docs, and recent community discussion (2025–2026). Do not rely on training data alone for version numbers, API shapes, or maintenance status. Web search for current state.

**Architecture is secondary**: if you encounter something architecturally significant — a choice that is materially wrong or where a different approach would unlock substantially better tooling — flag it briefly in Part 1. But don't dwell on it. The main body is tooling.

---

## Tools to Research

### UK Public Data Sources

#### DMO XML API (already in use)
Document fully for completeness:
- All available endpoints and report codes — are there any beyond D1A (conventional) and D1D (IL) that are useful for this app? Historical prices? Issuance calendar?
- Field-level documentation: exactly what fields come back, update cadence, encoding, known quirks
- Are there any known reliability issues or planned API changes?

#### Bank of England Statistics Database
The app already fetches the BoE 6-point yield curve and base rate. But the BoE publishes much more:
- **Fitted yield curves**: the BoE publishes daily model-fitted nominal spot, real spot, and OIS curves — these are not the same as the 6-point curve the app currently uses. The fitted real curve could be directly useful for IL gilt breakeven analysis and duration positioning.
- Document the exact series codes for: nominal spot curve (short and long end), real spot curve, Bank Rate, RPI, CPI
- Document the API shape: URL pattern, parameters, response format, any rate limits
- Is there an official API spec, or is it undocumented?
- Assess: `pyscraper` (https://github.com/jzuccollo/pyscraper) and `BOE-API/BOE_API` (https://github.com/BOE-API/BOE_API) — maintenance health, whether either is worth using as a base

#### ONS API
- REST API at `api.ons.gov.uk`, no authentication required
- RPI series code CZBH and others — document what's actually available (monthly, annual, component indices, RPI-H, CPIH)
- Actual JSON schema returned
- How does this complement or duplicate what's available via BoE?
- Reference: `dcorney/ons_api_demo` (https://github.com/dcorney/ons_api_demo)

#### LSE Price Explorer API (already in use for gilt prices)
- Document the endpoint shape, fields returned, rate limits
- Does it cover non-gilt instruments? Could it replace or supplement yfinance for LSE equities?
- Known reliability issues?

#### dividenddata.co.uk
- URL: `https://www.dividenddata.co.uk/uk-gilts-prices-yields.py`
- Is this a reliable source, a fragile scrape, or something in between?
- Could it serve as a cross-check or fallback for LSE gilt prices?

---

### Bond Analytics Libraries

#### QuantLib / QuantLib-Python
The single most important research item for the fixed-income side. The app hand-rolls everything. QuantLib is the industry-standard open source library for bond analytics.

- `pip install QuantLib` — C++ with Python SWIG bindings, v1.40
- `ql.UKRPI` index class, `CPIBond` class for IL gilts
- Key questions to answer:
  - Does QuantLib's `CPIBond` + `UKRPI` correctly model UK IL gilts? The UK convention is a 3-month observation lag using RPI (not CPI/CPIH). Is the lag, interpolation method, and floor guarantee implemented correctly for UK gilts specifically?
  - For conventional UK gilts: does QuantLib implement ICMA actual/actual day count, T+1 settlement, and ex-dividend handling (7 business days before coupon) correctly? Is this verifiably correct against DMO conventions?
  - Is QuantLib's GRY calculation for a conventional gilt equivalent to a Newton/brentq solve from the cash-flow definition, or does it do something materially different?
  - What was deprecated in v1.38/v1.39 regarding inflation curve constructors? What are the current correct constructor signatures?
  - Windows install story with `uv` — any known issues with the SWIG bindings?
  - Is there a way to use QuantLib purely as a validation/cross-check layer without replacing the hand-rolled engine entirely?
- **Verdict required**: should QuantLib replace the hand-rolled GRY and IL gilt engine, augment it, or is the hand-rolled approach defensible?

#### FinancePy
- `pip install financepy` — pure Python, no C++ compile
- https://github.com/domokane/FinancePy
- Does it implement ICMA actual/actual and UK gilt conventions correctly?
- IL gilt support with RPI observation lag?
- Maintenance health (last commit, open issues, PyPI release cadence)?
- Windows compatibility?
- **Verdict required**: better than QuantLib for this use case, worse, or not in the running?

---

### Portfolio Optimisation Libraries

The current allocator is a hand-coded LP via `scipy.optimize.linprog`. The constraint matrices are constructed manually. The objective is a linear attractiveness score (not a proper risk-adjusted return). There is no walk-forward validation, no statistical expected return model, and no covariance-aware optimisation.

For each library, answer:
- What objective functions does it support, and are any of them better suited to this problem than a linear attractiveness score?
- Can it express the constraints the current LP uses (turnover limits, scenario floors, concentration caps, tilt bands)?
- How does it handle assets with no statistical return history or unreliable return distributions (i.e. short-dated gilts where GRY is the right expected return proxy)?
- Is there a meaningful improvement in correctness or robustness over `scipy.optimize.linprog` for this specific problem?
- What is the realistic migration cost?
- **Verdict required for each**: replace, layer on top, or skip.

#### skfolio
- https://github.com/skfolio/skfolio / https://skfolio.org/
- scikit-learn paradigm, HRP, NCO, mean-variance, CVaR, walk-forward validation, GridSearchCV
- Academic paper published May 2026
- Deep-dive: constraint API, how it handles mixed analytical/statistical expected returns

#### PyPortfolioOpt
- https://github.com/PyPortfolio/PyPortfolioOpt
- Mean-variance, Black-Litterman, HRP, covariance shrinkage
- Deep-dive: Black-Litterman with gilt yield views as priors, constraint API

#### Riskfolio-Lib
- https://github.com/dcajasn/Riskfolio-Lib
- CVXPY-based, CVaR/CDaR risk measures
- Deep-dive: CVXPY as a Windows dependency, scenario-floor constraint support

#### CVXPY directly
- If Riskfolio-Lib wraps CVXPY, assess whether using CVXPY directly as the solver backend (replacing `scipy.optimize.linprog`) would give better constraint expressiveness and diagnostics without the overhead of a full portfolio library.

---

### Financial Data APIs and MCP Servers

#### OpenBB Platform + openbb-mcp
- https://github.com/OpenBB-finance/OpenBB (last release March 2026)
- https://docs.openbb.co/odp/python/extensions/interface/openbb-mcp
- "Connect once, consume everywhere" — unified API wrapping multiple providers
- Deep-dive: what UK-specific data is actually available (LSE equities, gilt prices, BoE data, ONS data)? What providers are free vs requiring paid keys? What does the MCP server actually expose to Claude as tools and resources? Is this the right infrastructure layer for v2 LLM market context?
- Claude Code plugin: `openbb-terminal@claude-code` — what does it actually install and expose?

#### EODHD + EODHD MCP Server
- https://eodhd.com/ — `GBOND` exchange, 77-tool MCP server, paid
- Deep-dive: GBOND exchange coverage (which gilts, what fields, price history depth), MCP tool list for UK instruments, pricing tiers

#### Alpha Vantage + Alpha Vantage MCP
- https://www.alphavantage.co/ / https://mcp.alphavantage.co/
- Free tier, official MCP server, LSE equities via `.L`
- Deep-dive: free tier rate limits, UK equity field coverage, what the MCP server exposes

#### Financial Modeling Prep (FMP) + FMP MCP
- https://site.financialmodelingprep.com/developer/docs/mcp-server
- Deep-dive: UK/LSE coverage, free tier limits, what's available for UK equities vs US

#### yfinance (already in use)
- Documents the current usage and known limitations for 2026
- `.L` suffix for LSE stocks, `trailingPE` via `.info`, broken UK ticker methods
- Is `multi_level_index=False` still the correct batch download pattern?
- Any 2026 rate limit or auth changes to be aware of?
- Is there a better free alternative for the specific use cases (UK equity price history, benchmark PE)?

#### LSEG Data Library for Python
- Requires paid subscription — document what it offers and why it's out of scope, for completeness

#### investpy / investiny
- `investpy` abandoned (Cloudflare-blocked), `investiny` as lightweight replacement
- Does investiny cover anything not available from yfinance for UK instruments?

---

### Open Source Portfolio Trackers

Not building blocks but context for the gap this app fills. Brief sections only.

#### Ghostfolio (https://github.com/ghostfolio/ghostfolio)
- What UK-specific features exist (ISA, GBP, SIPP)? What's missing for this use case?

#### Wealthfolio (https://wealthfolio.app/)
- UK/SIPP/gilt support? What's missing?

---

### Claude / Anthropic Integrations

#### anthropics/financial-services (https://github.com/anthropics/financial-services)
Institutional FSI plugins — already reviewed at high level. Two specific things to go deep on for v2:
1. **Skill/plugin authoring format**: the exact markdown+JSON schema — document it precisely so it can be replicated for SIPP-specific skills
2. **`wealth-management` vertical**: every skill and command in detail — `portfolio-rebalance`, `tax-loss-harvesting`, `financial-plan`, `investment-proposal`, `client-review`, `client-report` — what exactly do they do, and is any of it portable to a UK retail SIPP context even partially?

---

### Anything the Survey May Have Missed

Actively investigate beyond the predefined list. Specifically check:

- **awesome-quant** (https://github.com/wilsonfreitas/awesome-quant): scan the full list for anything UK fixed-income, gilt, or SIPP-relevant
- **BoE GitHub** (https://github.com/bank-of-england): what repos has the Bank actually published? Any Python tooling?
- **UK gilt pricing validation references**: are there any published test vectors or reference implementations for UK gilt clean/dirty price, accrued interest, or GRY that could be used to validate the hand-rolled engine?
- Any MCP servers not listed above covering UK financial data, bond analytics, or macro data
- Any OpenBB provider extensions for UK gilts or FTSE data (similar to the AKShare extension for HK/A-share)
- **pandas-datareader**: any useful UK data integrations?
- The `pyscraper` library (https://github.com/jzuccollo/pyscraper): look at it as a reference for BoE API shape even though unmaintained
- If anything architectural surfaces naturally during tooling research and seems material, flag it in Part 1

---

## Research Output Format

Write the output as `docs/external-tooling-research.md`. Use this structure:

```
# External Tooling Research
## Investment Optimiser — UK SIPP Portfolio Allocation Tool

## Executive Summary
[3–5 bullet points: the most important findings and recommended actions]

## Part 1: Architectural Flags (brief — only material issues)
[Any architectural choice that is materially wrong or where a different approach
unlocks substantially better tooling. One paragraph max per flag. Skip entirely
if nothing is material.]

## Part 2: UK Public Data Sources
### 2.1 DMO XML API
### 2.2 Bank of England Statistics Database
### 2.3 ONS API
### 2.4 LSE Price Explorer API
### 2.5 dividenddata.co.uk

## Part 3: Bond Analytics Libraries
### 3.1 QuantLib / QuantLib-Python
### 3.2 FinancePy

## Part 4: Portfolio Optimisation Libraries
### 4.1 skfolio
### 4.2 PyPortfolioOpt
### 4.3 Riskfolio-Lib
### 4.4 CVXPY directly

## Part 5: Financial Data APIs and MCP Servers
### 5.1 OpenBB Platform + openbb-mcp
### 5.2 EODHD + MCP Server
### 5.3 Alpha Vantage + MCP
### 5.4 Financial Modeling Prep + MCP
### 5.5 yfinance (current usage and gaps)
### 5.6 LSEG Data Library (out of scope, for completeness)
### 5.7 investpy / investiny

## Part 6: Open Source Trackers (brief — context only)
### 6.1 Ghostfolio
### 6.2 Wealthfolio

## Part 7: Claude / Anthropic Integrations
### 7.1 anthropics/financial-services
### 7.2 OpenBB Claude Code Plugin

## Part 8: Additional Findings
[Anything discovered beyond the predefined list]

## Part 9: Prioritised Recommendations
[Ranked action list: what to adopt now, what to watch for v2, what to skip and why.
For each current hand-rolled component: replace / augment / keep-as-is with one-line justification.]
```

---

## Standards for this document

- **Honest**: if the current approach is fine, say so. If it's wrong or outdated, say that clearly.
- **Specific**: version numbers, API endpoint URLs, code snippets, rate limits, pricing tiers. Not "may support" — go find out and state what actually exists.
- **Actionable**: each section should end with a concrete verdict and, where relevant, a sketch of what the integration or replacement would look like.
- **Aware of context**: this is a solo private investor's local Windows tool. Free tiers, `uv` compatibility, Windows install stories, and low operational overhead matter. Paid enterprise subscriptions are out of scope unless there is a meaningful free tier.
