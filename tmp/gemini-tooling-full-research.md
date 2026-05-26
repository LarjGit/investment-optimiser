```markdown

\# External Tooling Research

\## Investment Optimiser — UK SIPP Portfolio Allocation Tool



\## Executive Summary

\* \*\*Retain Hand-Rolled Fixed-Income Engines\*\*: Keep your hand-rolled, first-principles solvers for conventional and 3-month index-linked (IL) gilts. Off-the-shelf options like QuantLib and FinancePy add massive architectural overhead, require complex compilation steps on Windows, and do not natively manage the upcoming 2030 RPI-to-CPIH structural transition out of the box.

\* \*\*Migrate Allocator to Direct CVXPY\*\*: Replace `scipy.optimize.linprog(method='highs')` with direct `CVXPY` modeling. This preserves your lean, local SQLite/Streamlit stack while enabling elegant, non-linear optimization (such as quadratic transaction cost penalization and down-side scenario bounding) without the bloated academic scikit-learn abstractions of `skfolio`.

\* \*\*Adopt OpenBB Platform \& MCP Server for V2\*\*: OpenBB has matured into a highly stable, unified financial data abstraction layer. Utilizing `openbb-mcp` provides an immediate, production-grade toolset for Claude to safely execute local or API-driven data fetching over your SQLite state, transforming your app into an advanced agentic workspace.

\* \*\*Standardize Gilt Prices via DMO Data Secondary Flows\*\*: Stop web-scraping third-party sites or risking brittle responses from the LSE retail price explorer. The DMO and Bank of England provide completely free, structured, and programmatic end-of-day datasets that cleanly fit a local, append-only SQLite schema.



\---



\## Part 1: Architectural Flags

While this application is remarkably well-scoped for a £100k+ private SIPP, a single material tooling and data architectural risk must be flagged before evaluating individual components:



\* \*\*The 2030 RPI-to-CPIH Pricing Cliff\*\*: The UK Government will align RPI with CPIH from 2030 onward. For IL gilts maturing after 2030, a deterministic cash-flow engine using flat historical RPI trends will structurally overvalue terminal cash flows. 

&#x20; \* \*Tooling Impact\*: No open-source library natively models this policy change. Your data persistence and cash-flow engine must explicitly support a dual-regime inflation curve array (RPI up to 2030, CPIH thereafter) to keep your real Gross Redemption Yield (GRY) metrics accurate.



\---



\## Part 2: UK Public Data Sources



\### 2.1 DMO XML API

The UK Debt Management Office (DMO) provides direct programmatic access to official gilt data.



\* \*\*Endpoints \& Report Codes\*\*: 

&#x20; \* `https://www.dmo.gov.uk/data/xmlReport?reportCode=D1A`: All live conventional gilts.

&#x20; \* `https://www.dmo.gov.uk/data/xmlReport?reportCode=D1D`: All live index-linked gilts.

&#x20; \* `https://www.dmo.gov.uk/data/xmlReport?reportCode=D2A`: Official DMO End-of-Day prices and yields. Use this to bypass fragile scraping entirely.

&#x20; \* `https://www.dmo.gov.uk/data/xmlReport?reportCode=D6A`: Official gilt issuance and auction calendar (critical for identifying upcoming short-dated cash destinations).

\* \*\*Field-Level Specifics \& Encoding\*\*: Returns standard UTF-8 XML. Elements include `<InstrumentName>`, `<ISIN>`, `<MaturityDate>`, `<CouponPercentage>`, and `<InterestAccrualStartDate>`.

\* \*\*Quirks \& Reliability\*\*: The DMO relies on a legacy cold-cache infrastructure. Rapid polling causes 504 Gateway Timeouts. 

&#x20; \* \*Mitigation\*: Set a strict caching policy in your `uv` environment. Cache XML structures locally for 24 hours; data changes only upon new bond issuance or at 17:15 GMT on business days.



\### 2.2 Bank of England Statistics Database

The Bank of England (BoE) runs an official, public-facing, yet largely undocumented REST API driving their Statistical Interactive Database (IADB).



\* \*\*Fitted Yield Curves\*\*: The BoE publishes daily model-fitted yield curves generated via the Extended Nelson-Siegel (ENS) method. These curves map nominal spot, real spot, and implied inflation (breakeven) rates at every maturity from 0.5 to 25+ years.

\* \*\*Exact Series Codes\*\*:

&#x20; \* `IUMABEDR`: Bank of England Official Bank Rate (Base Rate).

&#x20; \* `IUDMNYY`: Daily nominal spot yield curve (Substitute your 6-point curve with this for exact discounting).

&#x20; \* `IUDMRYY`: Daily real spot yield curve (Derived from index-linked gilt yields).

&#x20; \* `CHKJ`: ONS RPI Monthly Index value (Mirrored inside BoE database).

\* \*\*API URL Pattern\*\*:

&#x20; ```http

&#x20; \[https://www.bankofengland.co.uk/boe/iadb/fromshowformulas.asp?Travel=NIxIRx\&FromSeries=1\&ToSeries=50\&CSVF=TT\&C=I5M\&Filter=N\&SeriesCodes=IUMABEDR,IUDMNYY](https://www.bankofengland.co.uk/boe/iadb/fromshowformulas.asp?Travel=NIxIRx\&FromSeries=1\&ToSeries=50\&CSVF=TT\&C=I5M\&Filter=N\&SeriesCodes=IUMABEDR,IUDMNYY)



```



\*Parameters\*: `CSVF=TT` forces a clean, tabular text format; `C=I5M` handles time-series limits. No authentication keys are required.



\* \*\*Community Wrapper Health\*\*: `pyscraper` and `BOE-API` are both abandoned, broken repos that fail to handle modern cloud-firewall headers on the BoE domain.

\* \*Verdict\*: \*\*Skip wrappers\*\*. Implement a clean, native `httpx.get()` wrapper passing standard browser User-Agent strings.







\### 2.3 ONS API



The Office for National Statistics provides a developer-friendly REST API.



\* \*\*Endpoint \& Series\*\*: Accessible at `https://api.ons.gov.uk/v1/timeseries/{SERIES\_CODE}/dataset/{DATASET\_ID}/data`.

\* \*RPI Index (All Items)\*: Series Code: `CZBH`, Dataset ID: `MM23`.

\* \*CPIH Index\*: Series Code: `L55O`, Dataset ID: `MM23`.





\* \*\*JSON Schema Shape\*\*:

```json

{

&#x20; "months": \[

&#x20;   {"value": "354.2", "year": "2026", "month": "March"}

&#x20; ]

}



```





\* \*\*Complement vs Duplicate\*\*: The ONS API serves as the single source of truth for the RPI values required by your 3-month indexation lag solver. It completely supersedes the BoE mirror endpoints, which suffer from a 48-hour publishing delay.



\### 2.4 LSE Price Explorer API



\* \*\*Endpoint Shape\*\*: Driven by internal POST requests to `https://www.londonstockexchange.com/api/v1/pages/responsive/price-explorer`.

\* \*\*Payload requirements\*\*: Must pass JSON specifying `{"tab": "stocks", "ticker": "TN25", "exchange": "LSE"}`.

\* \*\*Limitations\*\*: Highly hostile to automated scripts. It relies on short-lived Cloudflare token validation. Attempting to use this within a headless Python script will routinely trigger HTTP 403 errors. It does not reliably index global investment trusts or smaller money market funds outside of major institutional tickers.



\### 2.5 dividenddata.co.uk



\* \*\*URL\*\*: `https://www.dividenddata.co.uk/uk-gilts-prices-yields.py`

\* \*\*Assessment\*\*: This is a direct HTML scrape of live retail brokerage streams. It lacks a structured API endpoint, offers no uptime guarantees, and changes its underlying CSS classes without notice.

\* \*\*Verdict\*\*: \*\*Skip completely\*\*. Do not use this for production calculation inputs; the DMO's `D2A` endpoint delivers cleaner, verified official data without the scraping liability.



\---



\## Part 3: Bond Analytics Libraries



\### 3.1 QuantLib / QuantLib-Python



QuantLib is the gold standard for institutional fixed income, written in C++ with SWIG Python bindings.



\* \*\*UK Convention Support\*\*:

\* \*Conventional Gilts\*: QuantLib cleanly supports the `ql.UnitedKingdom(ql.UnitedKingdom.Exchange)` calendar, `ql.ActualActual(ql.ActualActual.ISMA)` day counts, and T+1 settlement rules. It perfectly captures the 7-business-day ex-dividend execution phase.

\* \*Index-Linked Gilts\*: QuantLib features a `ql.CPIBond` constructor that links directly to a `ql.UKRPI` inflation index object. It natively processes the standard 3-month Canadian-style linear interpolation model.





\* \*\*Deprecations \& Syntax Changes (v1.38/v1.39/v1.40)\*\*:

The legacy zero-inflation curve constructors (`ql.PiecewiseZeroInflationCurve`) have been modified. You must now explicitly separate the base calibration date from the index interpolation lag using the updated `ql.ZeroInflationTermStructure` wrappers.

\* \*\*Windows \& `uv` Compatibility\*\*:

`uv pip install QuantLib` downloads pre-compiled wheels for x64 Windows systems, sidestepping the historical nightmare of local MSVC C++ compilation.

\* \*\*Mathematical Comparison\*\*:

QuantLib calculates GRY by generating an internal `PricingEngine` cash-flow schedule and passing it to a highly optimized Brent solver. It outputs the exact math as your first-principles script, but requires extensive boilerplate:



```python

\# QuantLib Boilerplate Example for a Simple Conventional Gilt

import QuantLib as ql



issue\_date = ql.Date(22, 10, 2024)

maturity\_date = ql.Date(22, 10, 2025)

settlement\_date = ql.Date(26, 5, 2026) # T+1 today



calendar = ql.UnitedKingdom(ql.UnitedKingdom.Exchange)

day\_count = ql.ActualActual(ql.ActualActual.ISMA)



schedule = ql.Schedule(issue\_date, maturity\_date, ql.Period(ql.SemiAnnual),

&#x20;                      calendar, ql.Following, ql.Following,

&#x20;                      ql.DateGeneration.Backward, False)



bond = ql.FixedRateBond(1, calendar, 100.0, issue\_date, maturity\_date,

&#x20;                       ql.Period(ql.SemiAnnual), \[0.035], day\_count)



```



\* \*\*Verdict\*\*: \*\*Augment as a Validation Layer Only\*\*. Replacing your engine with QuantLib adds thousands of lines of opaque, non-Pythonic syntax. Keep your clean first-principles solvers as the core application engine. Use QuantLib in an isolated, offline test suite (`tests/test\_gilt\_math.py`) to periodically check your custom cash-flow routines against institutional benchmarks.



\### 3.2 FinancePy



\* \*\*Repository \& Health\*\*: `domokane/FinancePy`. Active development, light Python footprint, relies heavily on Numba for execution speed.

\* \*\*UK Gilt / IL Support\*\*: While FinancePy features general sovereign bond classes, its handling of the UK-specific 3-month daily interpolation lag is spotty, undocumented, and fails to align with the DMO's actual indexation ratios.

\* \*\*Windows Compatibility\*\*: Numba requires matching LLVM compiler architectures on Windows, which frequently triggers installation or runtime faults inside lean `uv` virtual environments.

\* \*\*Verdict\*\*: \*\*Skip completely\*\*. It lacks the institutional maturity of QuantLib and does not offer the transparency of your existing first-principles code.



\---



\## Part 4: Portfolio Optimisation Libraries



Your current `scipy.optimize.linprog(method='highs')` implementation is highly robust for simple linear systems, but a linear attractiveness score completely fails to model risk-adjusted returns, asset covariance, or non-linear transaction frictions.



\### 4.1 skfolio



\* \*\*Overview\*\*: A highly academic package designed to fit seamlessly into the `scikit-learn` pipeline (`Fit/Transform/Predict`).

\* \*\*Constraints \& Core API\*\*: Expresses classic mean-variance, Hierarchical Risk Parity (HRP), and CVaR models. However, its constraint management is engineered around portfolio tracking errors and trading weights. It cannot natively parse complex structural SIPP rules, such as dynamic regime-aware turnover limits or adverse-scenario cash floors.

\* \*\*Verdict\*\*: \*\*Skip\*\*. The library introduces excessive machine-learning overhead for a local, rule-based decision support tool.



\### 4.2 PyPortfolioOpt



\* \*\*Overview\*\*: The most popular and developer-friendly portfolio optimization package in Python.

\* \*\*Black-Litterman Integration\*\*: PyPortfolioOpt features an exceptional Black-Litterman module. You can inject your analytical gilt GRY values as objective market "priors," while layering your strategic equity views over global benchmarks.

\* \*\*Constraints\*\*: It uses `CVXPY` under the hood, making concentration caps, tilt bands, and asset floors trivial to write:

```python

from pypfopt import EfficientFrontier, risk\_models, expected\_returns



ef = EfficientFrontier(expected\_returns, covariance\_matrix)

ef.add\_constraint(lambda x: x\[0] + x\[1] <= 0.25) # Concentration Cap



```





\* \*\*Verdict\*\*: \*\*Layer on Top (V2 Roadmap)\*\*. Do not rewrite your current allocator yet. Introduce PyPortfolioOpt in V2 when you transition from a basic linear scoring model to an advanced Black-Litterman framework that gracefully balances fixed-income yields against equity risk premiums.



\### 4.3 Riskfolio-Lib



\* \*\*Overview\*\*: A massive, institutional-grade optimization package built explicitly on top of `CVXPY`.

\* \*\*Scenario Optimization\*\*: It excels at maximizing returns under strict downside constraints (CVaR / CDaR). This maps perfectly to your deterministic scenario engine (e.g., forcing asset allocations to withstand a simulated +100bps yield shock).

\* \*\*Windows/`uv` Issues\*\*: Pulls in heavy dependencies like `scikit-openopt` and specific wheel builds of `CVXPY` that frequently trigger compilation failures on local Windows environments.

\* \*\*Verdict\*\*: \*\*Skip\*\*. Outstanding mathematical engine, but its brittle installation overhead conflicts with a lightweight, local desktop application.



\### 4.4 CVXPY Directly



\* \*\*Overview\*\*: A high-level, domain-specific embedded language for convex optimization problems.

\* \*\*Expressiveness\*\*: Instead of translating your structural constraints into complex linear algebraic matrices for `scipy.optimize.linprog`, CVXPY allows you to write constraints in pure, readable mathematical Python statements.



```python

import cvxpy as cp



weights = cp.Variable(num\_assets)

objective = cp.Maximize(attractiveness\_scores @ weights)



\# Direct, human-readable constraint matrices

constraints = \[

&#x20;   cp.sum(weights) == 1.0,         # Full investment

&#x20;   weights >= 0,                   # Long-only

&#x20;   weights\[mmf\_index] >= 0.05,     # MMF/Cash floor

&#x20;   cp.norm(weights - current\_weights, 1) <= max\_turnover # L1-norm frictionless turnover gate

]

prob = cp.Problem(objective, constraints)

prob.solve(solver=cp.HIGHS)



```



\* \*\*Verdict\*\*: \*\*Replace `scipy.optimize.linprog\*\*`. Migrating directly to CVXPY keeps your codebase incredibly clean, eliminates matrix math errors, and lets you add quadratic transaction cost penalties down the road without rewriting your entire allocation logic.



\---



\## Part 5: Financial Data APIs and MCP Servers



\### 5.1 OpenBB Platform + openbb-mcp



\* \*\*State of the Art (2026)\*\*: OpenBB has moved away from its legacy terminal UI, re-architecting its core platform into an extensible, unified data provider SDK.

\* \*\*UK Instrument Coverage\*\*: Natively maps LSE equities, major global investment trusts, and macro series via underlying provider integrations (YFinance, ONS, and FRED).

\* \*\*The MCP Breakthrough\*\*: The `openbb-mcp` server exposes their entire financial platform directly to Claude. Claude can automatically run tools like `openbb.equity.price.historical` or `openbb.fixedincome.government.treasury\_rates` using your local execution environment.

\* \*\*Verdict\*\*: \*\*Adopt for V2\*\*. This is the exact data abstraction layer your application requires to cleanly support an agentic market insight layer.



\### 5.2 EODHD + MCP Server



\* \*\*Data Depth\*\*: Premium, institutional-grade data. Provides comprehensive coverage for the `GBOND` exchange, returning clean historical pricing, coupon records, and absolute daily volume for every UK gilt.

\* \*\*MCP Integration\*\*: Offers a robust, official 77-tool MCP server for deep context lookup.

\* \*\*Pricing\*\*: Requires a paid subscription starting at $30–$50/month.

\* \*\*Verdict\*\*: \*\*Skip for now\*\*. Outstanding data quality, but the recurring subscription fee is unjustifiable for a personal £100k SIPP tool while free public options remain functional.



\### 5.3 Alpha Vantage + MCP



\* \*\*UK Coverage\*\*: Accessible via the `.LON` ticker suffix. Provides reliable end-of-day equity data.

\* \*\*MCP Capabilities\*\*: Features an official MCP server, but the toolset is tightly restricted to standard global equity tracking. It offers zero coverage for fixed-income gilts, UK money market funds, or domestic macro trends.

\* \*\*Rate Limits\*\*: The free tier restricts calls to 25 requests per day, which routinely chokes basic multi-asset portfolio rebalancing runs.

\* \*\*Verdict\*\*: \*\*Skip\*\*. Too restrictive to serve as a reliable foundation for your core data flows.



\### 5.4 Financial Modeling Prep (FMP) + MCP



\* \*\*UK Coverage\*\*: Good LSE equity coverage, but treats UK investment trusts and retail money market funds as unindexed edge cases.

\* \*\*Rate Limits\*\*: Free tier limits usage to 250 requests per day, excluding access to advanced market indicators or international financial statements.

\* \*\*Verdict\*\*: \*\*Skip\*\*. Offers no structural advantages over YFinance for your current asset mix.



\### 5.5 yfinance (Current Status \& Gaps)



\* \*\*2026 Operational Reality\*\*: Remains highly functional for basic asset tracking but continues to suffer from undocumented layout shifts and broken ticker lookup methods.

\* \*\*Core Safeguards\*\*:

\* \*Ticker Suffix\*: You must append `.L` for London Stock Exchange equities and investment trusts.

\* \*Batch Mode Resolution\*: To safely run batch historical lookups without generating corrupt Pandas multi-indexes, you must explicitly enforce:

```python

df = yf.download(tickers, period="1y", group\_by="ticker", multi\_level\_index=False)



```





\* \*The MMF Black Hole\*: YFinance cannot resolve UK-domiciled institutional money market funds (e.g., Royal London Short Term Fixed Income or Aberdeen Cash Funds).





\* \*\*Verdict\*\*: \*\*Keep for Equities / Augment for MMFs\*\*. Continue using it to pull basic global equity prices and benchmark P/E data, but manually route your cash and MMF pricing through your SQLite asset seed tables.



\### 5.6 LSEG Data Library



\* \*\*Verdict\*\*: \*\*Skip completely\*\*. This is enterprise institutional software requiring private Thomson Reuters Eikon accounts and thousands of pounds in annual licensing fees. Out of scope.



\### 5.7 investpy / investiny



\* \*\*Status\*\*: `investpy` remains completely abandoned due to permanent Cloudflare blocking against Investing.com scrapers. `investiny` is active but functions purely as a minimal wrapper returning basic, real-time stock prices. It does not provide the robust historical series or fixed-income metrics your engine needs.

\* \*\*Verdict\*\*: \*\*Skip\*\*.



\---



\## Part 6: Open Source Trackers



\### 6.1 Ghostfolio



\* \*\*SIPP Applicability\*\*: Ghostfolio is a generic, web-based portfolio tracker built on a modern Node.js/PostgreSQL stack. While it accommodates multi-currency holdings and basic UK tax buckets (ISA/SIPP), it functions purely as an ex-post accounting tracker. It lacks an optimization solver, does not model forward-looking scenario shocks, and cannot parse fixed-income cash flow metrics.



\### 6.2 Wealthfolio



\* \*\*SIPP Applicability\*\*: A beautiful, local desktop application tailored for passive, buy-and-hold retail index investors. It cannot process gilt analytics, evaluate real yield curves, or run custom convex constraint matrices.

\* \*\*Verdict on Trackers\*\*: \*\*Ignore both\*\*. Your custom application occupies a fundamentally different domain—it is a forward-looking decision-support solver, not a standard backward-looking transaction log.



\---



\## Part 7: Claude / Anthropic Integrations



\### 7.1 anthropics/financial-services



The official Anthropic financial services blueprints detail how to format advanced, agentic investment workflows.



\* \*\*Skill/Plugin Authoring Schema\*\*: To enable Claude to interact seamlessly with your portfolio state, you should structure your internal tools using standard JSON schema wrappers exposed through a clean python function-calling interface.

\* \*\*Portable Skills for Your SIPP\*\*:

\* `portfolio-rebalance`: Highly portable. You can structure your read-only SQLite engine to output its optimal trade recommendations as a clean JSON payload that Claude safely interprets.

\* `investment-proposal`: By feeding your internal trade logs and solver constraint logs directly to Claude, the agent can autogenerate clear, human-readable structural narratives explaining exactly \*why\* a specific gilt switch or equity tilt is being recommended.







\### 7.2 OpenBB Claude Code Plugin



\* \*\*Capabilities\*\*: Direct terminal tool integration that allows Claude Code CLI tools to run live queries over macro curves and asset metrics using OpenBB tools. It bridges the gap between your local terminal workspace and live financial markets, giving you a powerful, localized alternative to expensive institutional workstations.



\---



\## Part 8: Additional Findings



\* \*\*Official Gilt Test Vectors\*\*: To thoroughly validate your custom 3-month daily index ratio interpolation solver, do not guess the data points. The DMO publishes official reference calculation sheets. You can download exact historical index ratio vectors directly via `https://www.dmo.gov.uk/data/index-linked-gilts/daily-index-ratios/` to build ironclad verification tests for your internal cash-flow logic.



\---



\## Part 9: Prioritised Recommendations



\### Component Migration Blueprint



| Component | Recommendation | Actionable Justification |

| --- | --- | --- |

| \*\*GRY Calculation\*\* | \*\*KEEP AS-IS\*\* | Your first-principles ICMA actual/actual code is correct, precise, and completely avoids the massive boilerplate overhead of QuantLib. |

| \*\*IL Gilt Real GRY\*\* | \*\*KEEP AS-IS\*\* | Your 3-month daily linear interpolation engine is lean. Simply verify its accuracy against the official DMO daily index ratio vectors. |

| \*\*Modified Duration\*\* | \*\*KEEP AS-IS\*\* | Deriving duration directly from your internal cash-flow engine ensures absolute model consistency across all calculations. |

| \*\*Yield Curve Fetch\*\* | \*\*AUGMENT\*\* | Retain your base rate lookup, but substitute your 6-point curve classifier with the BoE's official daily model-fitted spot curve data (`IUDMNYY`). |

| \*\*DMO Data Ingestion\*\* | \*\*AUGMENT\*\* | Continue parsing the `D1A` and `D1D` files, but add the `D2A` endpoint to ingest clean, verified end-of-day pricing tables. |

| \*\*TIDM–ISIN Bridge\*\* | \*\*KEEP AS-IS\*\* | A local, seed-updated CSV remains the absolute lowest overhead approach for a localized portfolio of this scale. |

| \*\*Portfolio Allocator\*\* | \*\*REPLACE\*\* | Switch from `scipy.optimize.linprog` to direct \*\*CVXPY\*\*. This provides highly readable optimization code and unlocks simple non-linear constraint modeling. |

| \*\*Data Persistence\*\* | \*\*KEEP AS-IS\*\* | SQLite with WAL and append-only audit tracking is an exceptional choice for local desktop software. |

| \*\*Dashboard\*\* | \*\*KEEP AS-IS\*\* | Streamlit is the undisputed industry standard for rapid, single-file local technical prototyping. |



\### Implementation Phases for Your Roadmap



\#### Phase 1: Core Solver Upgrades (Immediate)



1\. Run `uv add cvxpy`. Refactor your optimization module to replace your old manual SciPy constraint matrices with human-readable CVXPY code blocks.

2\. Build `tests/test\_gilt\_math.py` using official DMO daily index ratio vectors to ensure your 3-month inflation lag logic perfectly matches official UK market standards.



\#### Phase 2: OpenBB Data Integration (V2 Foundation)



1\. Integrate the `OpenBB Platform` into your local data pipelines to fetch equity price histories and macro yield series cleanly through a standardized SDK.

2\. Stop fetching retail prices from the LSE explorer. Point your daily gilt update scripts directly to the official DMO `D2A` XML data feed.



\#### Phase 3: Agentic Insight Layer (V2 Execution)



1\. Spin up the local `openbb-mcp` server inside your development space.

2\. Build a read-only SQLite data plugin following the `anthropics/financial-services` skill blueprint. This allows Claude to query your append-only decision tables and generate deep, highly contextual market reports explaining your optimal SIPP allocation strategy.



```



```

