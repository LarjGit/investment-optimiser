# External Tooling Research
## Investment Optimiser — UK SIPP Portfolio Allocation Tool

_Last researched: 26 May 2026._

This document reviews external tooling for a local Python/Streamlit UK SIPP portfolio optimiser. It focuses on libraries, APIs, data sources, MCP servers, and Claude/Anthropic integration patterns. The target user is a private UK investor running a local Windows tool, so free/public data, reproducibility, Windows/`uv` install friction, transparency, and low operational overhead matter more than institutional breadth.

---

## Executive Summary

- **Keep the core local deterministic architecture.** The current architecture — SQLite/WAL, append-only audit history, deterministic scenarios, recommendation-only trades, solver snapshots — is directionally right for a private-investor SIPP optimiser. The big gaps are validation depth, data-source resilience, and future LLM/tooling integration, not a need to rebuild as a cloud platform.
- **Do not blindly replace the hand-rolled gilt engine with QuantLib.** QuantLib is the strongest external fixed-income library and should be added as a validation/cross-check layer immediately. Full replacement should wait until UK-specific conventions are proven against DMO formulae and app-level test vectors.
- **Add BoE fitted yield curves and ONS inflation API support.** The current 6-point BoE curve is useful for signal cards, but BoE fitted nominal/real/OIS curves and ONS RPI/CPI/CPIH series materially improve IL gilt breakeven, duration, and macro regime analysis.
- **Keep `scipy.optimize.linprog` for the current LP unless diagnostics become painful.** Portfolio libraries such as skfolio, PyPortfolioOpt, and Riskfolio-Lib are useful for research/backtesting but do not naturally replace a policy-aware LP with bespoke constraints, friction gates, and scenario floors. CVXPY is the only credible optimiser-layer upgrade.
- **Treat OpenBB/OpenBB MCP as v2 explanation infrastructure, not the core source of truth.** MCP is useful for Claude-facing narrative analysis over live data, but the calculation engine should continue to depend on deterministic, directly persisted raw inputs.

---

## Part 1: Architectural Flags

### 1.1 The current architecture is not the main problem

The app's core design — local-only Python, deterministic pipeline, SQLite audit history, replayable solver snapshots, manual trade execution — is coherent for a private SIPP tool. The biggest risk is not that the app is too simple; it is that hand-rolled financial conventions may be subtly wrong and that free public data sources may be brittle without validation/fallbacks.

### 1.2 The fixed-income analytics layer needs external validation

The current hand-rolled GRY, accrued-interest, settlement-date, modified-duration, and IL gilt logic is the highest-risk area. UK gilts have precise conventions, including ICMA Actual/Actual, settlement conventions, ex-dividend behaviour, 3-month and legacy 8-month indexation lags, and market assumptions for unpublished RPI. The DMO publishes official price/yield formulae and should remain the primary reference. QuantLib should be introduced first as a test oracle/cross-check, not as an unexamined replacement.

### 1.3 The optimiser is policy-aware, not a generic mean-variance optimiser

The current LP is closer to a constraint-driven policy allocator than a conventional portfolio optimiser. Most portfolio libraries optimise statistical return/risk measures from historical returns. That is not a natural fit for short-dated gilts where GRY is the expected-return proxy, for cash/MMF floors, or for deterministic scenario floors. A migration to CVXPY may improve expressiveness and diagnostics, but a migration to a generic portfolio library is unlikely to improve correctness.

### 1.4 LLM/MCP should sit behind the explanation boundary

The planned v2 LLM layer should remain read-only over persisted data, scenario outputs, and solver decisions. MCP servers are valuable as research/explanation tools but should not become hidden mutable dependencies inside the optimiser. The engine should continue to write deterministic inputs and outputs first; Claude should explain, challenge, and narrate them later.

---

## Part 2: UK Public Data Sources

### 2.1 DMO XML API

**What exists**

The UK Debt Management Office site exposes many report endpoints via `ExportReport?reportCode=...` and `pdfdatareport?reportCode=...`. Relevant reports include:

- `D1A` — Gilts in Issue: conventional gilts currently in issue.
- `D1D` — Index-linked Gilts in Issue.
- `D2.1E` — Gilt Issuance History.
- `D5D` — Outright Gilt Issuance Calendar.
- `D5J` — Events Calendar.
- `D5I` — Index-linked gilt cash flows.
- `D9C` — Estimated index-linked gilt redemption payments.
- `D10C` — Index ratios for 3-month lag index-linked gilts.
- `D4O` — RPI data.
- `D4H` — Historical average daily conventional gilt yields.

Useful source pages:

- DMO data index: https://www.dmo.gov.uk/data/
- Gilts in Issue D1A: https://www.dmo.gov.uk/data/pdfdatareport?reportCode=D1A
- Index-linked Gilts D1D: https://www.dmo.gov.uk/data/pdfdatareport?reportCode=D1D
- Index-linked gilts overview: https://www.dmo.gov.uk/data/gilt-market/index-linked-gilts/
- DMO price/yield formulae, 4th edition, 18 Dec 2024: https://www.dmo.gov.uk/media/334d05fo/yldeqns_v4.pdf

**Important quirks**

- D1A/D1D only run for UK working days; if a non-working day is requested the report returns the most recent working day.
- D1D distinguishes 3-month lag and legacy 8-month lag index-linked gilts.
- DMO stopped producing daily gilt reference prices in July 2017. End-of-day reference prices are now produced/administered by FTSE-Tradeweb and are publicly available for non-commercial use after noon the next day via Tradeweb Insite.
- Coupon parsing from instrument names is a fragile convenience, not a proper reference-data model. Prefer explicit coupon fields if exposed by the report; where only names are available, preserve the raw name and parsed coupon with provenance.

**API shape**

The DMO site is report-oriented rather than a modern JSON API. Typical usage:

```python
import pandas as pd

url = "https://www.dmo.gov.uk/data/ExportReport?reportCode=D1A"
df = pd.read_xml(url)  # if XML output is returned for the report
```

Where HTML/PDF pages sit in front of XML links, the ingestion layer should explicitly resolve the XML link from the DMO data index rather than assume every `pdfdatareport` URL is parseable.

**Verdict: keep and expand.**

DMO remains the authoritative source for gilt reference data and formulae. Keep DMO ingestion, add D10C/D4O support for index ratios/RPI, and use the 2024 DMO formulae PDF as the canonical test reference for pricing/yield logic.

---

### 2.2 Bank of England Statistics Database

**What exists**

The Bank of England publishes:

- Official Bank Rate history.
- Interest and exchange-rate series.
- Yield curves.
- Daily fitted UK yield curves: nominal gilt curves, real gilt curves, implied inflation term structure, and nominal OIS curves.

Important BoE pages:

- BoE database: https://www.bankofengland.co.uk/boeapps/database/
- BoE yield curves: https://www.bankofengland.co.uk/statistics/yield-curves
- Yield curve terminology: https://www.bankofengland.co.uk/statistics/yield-curves/terminology-and-concepts
- Further details about yields data: https://www.bankofengland.co.uk/statistics/details/further-details-about-yields-data

The BoE states that it publishes daily estimated UK yield curves and aims to publish the latest daily curves by noon on the following business day. The fitted curves include nominal/real gilt curves and implied inflation, while OIS curves are nominal-only.

**Current app gap**

A 6-point yield curve classification is useful for a simple dashboard, but the fitted curves are much more useful for:

- IL gilt real yield comparison.
- Breakeven inflation estimates.
- Duration positioning.
- Spot/forward curve regime signals.
- Scenario calibration.

**API shape**

The older Interactive Statistical Database CSV pattern is typically:

```text
https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/2020&Dateto=26/May/2026&SeriesCodes=IUDBEDR&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N
```

Example Python wrapper:

```python
import pandas as pd
from urllib.parse import urlencode

params = {
    "csv.x": "yes",
    "Datefrom": "01/Jan/2020",
    "Dateto": "26/May/2026",
    "SeriesCodes": "IUDBEDR",
    "CSVF": "TN",
    "UsingCodes": "Y",
    "VPD": "Y",
    "VFD": "N",
}
url = "https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp?" + urlencode(params)
df = pd.read_csv(url)
```

**Series/code notes**

- `IUDBEDR` is commonly used for Official Bank Rate.
- For fitted curves, do not rely only on hand-entered series codes. Use BoE export pages or an explicit catalogue in the app, because the curve data are wider than single Bank Rate-style series.
- RPI/CPI are also available from ONS and should generally be treated as ONS-sourced primary inflation series, with BoE used where the app needs BoE-specific curve construction or Bank Rate.

**Third-party wrappers**

- `pyscraper` / `BOE_API`: useful as references for URL construction, but not recommended as production dependencies unless maintenance is verified in the repo at implementation time.
- The R package `boe` is a useful design reference because it exposes named helpers such as `boe_bank_rate()`, `boe_yield_curve()`, and `boe_curve()` and explicitly covers fitted curve panels. It is not directly useful in the Python app but suggests a good internal Python wrapper design.

**Verdict: augment.**

Keep the existing BoE CSV fetcher but add a small internal `boe_client.py` abstraction with named functions:

```python
get_bank_rate(start, end)
get_nominal_fitted_curve(date=None, measure="spot")
get_real_fitted_curve(date=None, measure="spot")
get_ois_curve(date=None, measure="spot")
get_implied_inflation_curve(date=None)
```

Do not add a weakly maintained BoE Python dependency unless it materially reduces maintenance.

---

### 2.3 ONS API

**What exists**

ONS exposes APIs at:

```text
https://api.beta.ons.gov.uk/v1
```

The API is open and unrestricted with no API keys required. ONS documents that it returns JSON and that the v1 API is the strategic direction after retirement of older v0 endpoints.

Useful pages:

- ONS developer hub: https://developer.ons.gov.uk/
- ONS datasets endpoint docs: https://developer.ons.gov.uk/dataset/datasets/
- ONS API tour: https://developer.ons.gov.uk/tour/latest-version/
- ONS v0 retirement notice: https://developer.ons.gov.uk/retirement/v0api/
- ONS RPI annual % series CZBH: https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/czbh/mm23
- ONS RPI index series CHAW: https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23

**Useful inflation series**

- `CHAW` — RPI All Items Index: Jan 1987=100.
- `CZBH` — RPI All Items: percentage change over 12 months.
- CPI/CPIH equivalents should be resolved through the ONS time-series pages and pinned in a local series-code catalogue.

**API shape**

For classic website time-series JSON:

```text
https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23/data
```

For beta API dataset/version observations:

```text
https://api.beta.ons.gov.uk/v1/datasets/{dataset_id}/editions/{edition}/versions/{version}/observations?time=*&...
```

Example simple time-series fetch:

```python
import requests
import pandas as pd

url = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23/data"
js = requests.get(url, timeout=20).json()
rows = js["months"]
df = pd.DataFrame(rows)[["date", "value"]]
df["value"] = pd.to_numeric(df["value"], errors="coerce")
```

**dcorney/ons_api_demo**

The `dcorney/ons_api_demo` repo is a useful small Python example, not a production dependency. It demonstrates the `api.beta.ons.gov.uk/v1` flow, datasets, dimensions, and observations with `requests` and pandas.

**Verdict: add.**

Add ONS as the primary inflation-series source. Use direct `requests` calls; do not add a dependency unless it has obvious maintenance value. Persist raw JSON/CSV snapshots for reproducibility because inflation data release dates matter.

---

### 2.4 LSE Price Explorer API

**What exists**

The public London Stock Exchange price explorer exposes current instrument search/quote pages for all instruments traded on London Stock Exchange markets. Relevant public pages:

- Price explorer: https://www.londonstockexchange.com/live-markets/market-data-dashboard/price-explorer
- All market data dashboard: https://www.londonstockexchange.com/market-data/all
- LSEG market data commercial overview: https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/equities-market-data/lse-market-data

**Assessment**

The app's current LSE price-explorer use is best treated as an unofficial web endpoint. It may cover non-gilt instruments and can supplement yfinance for LSE equities/ETFs, but it should not be treated as a stable public API unless LSE/LSEG explicitly documents the endpoint and usage rights.

**Likely strengths**

- Good for current/delayed London-listed instrument quotes.
- Useful for TIDM/ISIN bridging and current gilt quote cross-checking.
- May cover equities, ETFs, investment trusts, and retail bonds.

**Likely weaknesses**

- Unclear rate limits.
- Web endpoint can change without notice.
- Licensing/redistribution restrictions matter if the app ever becomes public/commercial.
- Historical price depth is likely not sufficient compared with paid LSEG products or provider APIs.

**Verdict: keep as a fragile source with caching and fallbacks.**

Use it for personal/local quote refresh and TIDM/ISIN bridging, but wrap it behind a provider interface with caching, retry/backoff, and provenance. For anything commercial, revisit licensing.

---

### 2.5 dividenddata.co.uk

**What exists**

DividendData exposes simple public pages for UK gilt prices/yields and index-linked gilt prices/yields:

- Conventional gilts: https://www.dividenddata.co.uk/uk-gilts-prices-yields.py
- Index-linked gilts: https://www.dividenddata.co.uk/index-linked-gilts-prices-yields.py

Fields shown include EPIC, name, coupon, maturity, time to maturity, price, running yield, and yield to maturity.

**Assessment**

This is convenient and human-readable, but it is not an official source and should be treated as a scrape/fallback/cross-check only. It is useful precisely because it calculates and displays the thing the app cares about — yield to maturity — but that also makes it risky to depend on without knowing its calculation conventions.

**Verdict: fallback/cross-check only.**

Use it to sanity-check current yields and spot obvious provider failures. Do not use it as the primary source of record.

---

## Part 3: Bond Analytics Libraries

### 3.1 QuantLib / QuantLib-Python

**Current state**

QuantLib is the leading open-source quantitative-finance library. The Python package is now installed as:

```bash
uv add QuantLib
# or
pip install QuantLib
```

`QuantLib-Python` on PyPI is a backward-compatible meta-package and should not be the direct dependency. QuantLib publishes precompiled Python wheels for common platforms, so Windows installation should normally be acceptable without compiling C++.

Important docs/pages:

- PyPI QuantLib: https://pypi.org/project/QuantLib/
- QuantLib download page: https://www.quantlib.org/download.shtml
- QuantLib Windows Python install: https://www.quantlib.org/install/windows-python.shtml
- QuantLib-Python inflation docs: https://quantlib-python-docs.readthedocs.io/en/latest/instruments/inflation.html
- QuantLib bonds docs: https://quantlib-python-docs.readthedocs.io/en/latest/instruments/bonds.html
- QuantLib 1.39 notes/removals discussion: https://www.implementingquantlib.com/2025/07/new-in-1-39.html
- Inflation constructor deprecation discussion: https://www.implementingquantlib.com/2024/05/inflation-curves.html

**Conventional gilts**

QuantLib can represent fixed-rate bonds, schedules, calendars, day counters, settlement days, and yield calculations. Relevant objects include:

```python
import QuantLib as ql

calendar = ql.UnitedKingdom(ql.UnitedKingdom.Exchange)
settlement_days = 1
face = 100.0
coupon = 0.04125
issue = ql.Date(29, ql.January, 2024)
maturity = ql.Date(29, ql.January, 2027)

schedule = ql.Schedule(
    issue,
    maturity,
    ql.Period(ql.Semiannual),
    calendar,
    ql.Unadjusted,
    ql.Unadjusted,
    ql.DateGeneration.Backward,
    False,
)

bond = ql.FixedRateBond(
    settlement_days,
    face,
    schedule,
    [coupon],
    ql.ActualActual(ql.ActualActual.ICMA),
)
```

Open questions to validate before replacement:

- Does the app need explicit ex-dividend periods? QuantLib has ex-coupon features in bond-leg construction, but UK gilt ex-div behaviour must be tested against DMO examples.
- Does QuantLib's settlement-date adjustment exactly match current UK gilt market convention in the app's use case?
- Does `BondFunctions.bondYield` match DMO gross redemption yield formulae for all relevant coupon/maturity cases?

**Index-linked gilts**

QuantLib exposes `CPIBond` and UK inflation indices such as `UKRPI`. The Python CPIBond constructor shape is:

```python
ql.CPIBond(
    settlementDays,
    notional,
    growthOnly,
    baseCPI,
    contractObservationLag,
    inflationIndex,
    observationInterpolation,
    fixedSchedule,
    fixedRates,
    fixedDayCounter,
    fixedPaymentConvention,
)
```

Skeleton:

```python
import QuantLib as ql

calendar = ql.UnitedKingdom()
settlement_days = 1
notional = 100.0
growth_only = False
base_cpi = 100.0
lag = ql.Period(3, ql.Months)
rpi = ql.UKRPI(False)  # interpolation setting must be validated
interp = ql.CPI.AsIndex

schedule = ql.Schedule(
    ql.Date(22, ql.March, 2024),
    ql.Date(22, ql.March, 2034),
    ql.Period(ql.Semiannual),
    calendar,
    ql.Unadjusted,
    ql.Unadjusted,
    ql.DateGeneration.Backward,
    False,
)

bond = ql.CPIBond(
    settlement_days,
    notional,
    growth_only,
    base_cpi,
    lag,
    rpi,
    interp,
    schedule,
    [0.00125],
    ql.ActualActual(ql.ActualActual.ICMA),
    ql.Unadjusted,
)
```

Open questions to validate:

- UK IL gilts use RPI, not CPI/CPIH, despite the generic `CPIBond` naming.
- 3-month lag gilts and older 8-month lag gilts must be modelled separately.
- The DMO formulae document remains the authoritative source for 3-month and 8-month indexation.
- QuantLib's inflation curve constructors changed/deprecated around 1.38/1.39, so any implementation should target current signatures, not old blog examples.
- The `growthOnly` parameter and interpolation choices need explicit tests because documentation is sparse.

**Validation strategy**

Add QuantLib as a dev/test dependency first:

```toml
[project.optional-dependencies]
analytics = ["QuantLib>=1.40"]
```

Create validation tests:

```python
def test_conventional_gilt_yield_matches_quantlib():
    ours = calc_gilt_gry(...)
    ql_yield = calc_quantlib_yield(...)
    assert abs(ours - ql_yield) < 1e-6


def test_il_gilt_cashflows_match_dmo_reference():
    ours = calc_il_cashflows(...)
    ql_flows = calc_quantlib_cpi_flows(...)
    assert_cashflows_close(ours, ql_flows)
```

Then add DMO formulae test vectors. If QuantLib and app disagree, DMO wins.

**Verdict: augment first, possible replace later.**

QuantLib should be introduced immediately as a cross-check and regression-test engine. Do not replace the transparent hand-rolled engine until QuantLib has been proven against DMO formulae for conventional gilts, 3-month IL gilts, legacy 8-month IL gilts, settlement, accrued interest, and ex-div behaviour.

---

### 3.2 FinancePy

**What exists**

FinancePy is a pure-Python finance library maintained on GitHub:

- GitHub: https://github.com/domokane/FinancePy

It is attractive because it avoids C++/SWIG complexity and is more inspectable than QuantLib.

**Assessment**

FinancePy may be useful for learning, prototyping, and comparing conventional bond analytics. However, for this app the key question is UK-specific correctness: ICMA Actual/Actual, gilt settlement/ex-dividend handling, index-linked gilt RPI observation lag, and DMO convention compatibility. QuantLib has broader industry coverage and deeper fixed-income infrastructure.

**Verdict: skip as a core dependency; maybe use for comparison.**

FinancePy is not better than QuantLib for this use case. If added, use it only as a third-opinion validation tool, not as the main analytics engine.

---

## Part 4: Portfolio Optimisation Libraries

### 4.1 skfolio

**What exists**

skfolio is a modern portfolio-optimisation/risk-management library built around the scikit-learn paradigm. It supports cross-validation, model selection, HRP, NCO, mean-risk optimisation, CVaR-style risk measures, stress testing, and pipeline-style workflows.

Sources:

- Website/docs: https://skfolio.org/
- Optimisation docs: https://skfolio.org/user_guide/optimization.html
- Weight constraints example: https://skfolio.org/auto_examples/mean_risk/plot_5_weight_constraints.html
- Paper: https://arxiv.org/abs/2507.04176

**Fit for this app**

Strengths:

- Excellent for research workflows and comparing allocation methods.
- Scikit-learn compatibility is useful for walk-forward validation and parameter tuning.
- Supports linear constraints, budgets, groups, min/max weights.

Weaknesses:

- Its natural input is historical returns `X`; the app's expected returns for gilts are analytical GRY/cash-flow based, not purely historical.
- The current policy constraints are highly bespoke: baseline tilt bands, friction gates, scenario floors, MMF/cash floors, maturity caps, and concentration vetoes.
- Migrating the production allocator would likely reduce transparency before it increases correctness.

**Verdict: layer on top for research/backtesting, not replacement.**

Use skfolio to compare current LP recommendations against mean-risk/HRP/NCO portfolios in a research tab. Do not make it the production allocator.

---

### 4.2 PyPortfolioOpt

**What exists**

PyPortfolioOpt supports classical mean-variance optimisation, Black-Litterman, HRP, covariance shrinkage, expected-return models, and efficient-frontier workflows.

Sources:

- Docs: https://pyportfolioopt.readthedocs.io/
- PyPI: https://pypi.org/project/pyportfolioopt/
- Black-Litterman docs: https://pyportfolioopt.readthedocs.io/en/latest/BlackLitterman.html

**Fit for this app**

Strengths:

- Good educational/prototyping library.
- Black-Litterman could be useful for expressing tactical views, e.g. equity risk premium or gilt-yield views.
- Covariance shrinkage and HRP may be useful for equity/fund sleeve analytics.

Weaknesses:

- Less natural for direct cash-flow assets and policy constraints.
- Constraint system is not a clean replacement for the current LP.
- Black-Litterman can give false sophistication if the priors/views are not carefully designed.

**Verdict: skip for production; maybe use for educational comparison.**

Useful for a research notebook or explanatory appendix, but not the right allocator backbone.

---

### 4.3 Riskfolio-Lib

**What exists**

Riskfolio-Lib is a CVXPY-based portfolio optimisation library with many risk measures, including CVaR/CDaR-style downside measures and robust optimisation variants.

Sources:

- Docs: https://riskfolio-lib.readthedocs.io/
- Portfolio optimisation docs: https://riskfolio-lib.readthedocs.io/en/latest/portfolio.html
- Changelog: https://riskfolio-lib.readthedocs.io/en/latest/changelog.html

**Fit for this app**

Strengths:

- Rich set of risk measures.
- CVXPY backend means a more expressive mathematical foundation than plain matrix-built LPs.
- Useful for research into downside risk and stress-based allocation.

Weaknesses:

- More dependency and conceptual weight than the app needs.
- Still built around statistical return/risk optimisation rather than a bespoke SIPP policy engine.
- CVXPY dependency is manageable on modern Python, but direct CVXPY is cleaner if the app needs custom constraints.

**Verdict: skip as production dependency; consider only for research.**

Riskfolio-Lib is powerful but too broad for the production allocator. If the goal is better constraints and diagnostics, use CVXPY directly.

---

### 4.4 CVXPY directly

**What exists**

CVXPY is a Python-embedded modelling language for convex optimisation. It lets you express problems naturally rather than manually building solver-standard matrices. CVXPY is not itself a solver; it uses solvers such as Clarabel, SCS, OSQP, and HiGHS.

Sources:

- CVXPY homepage: https://www.cvxpy.org/
- PyPI: https://pypi.org/project/cvxpy/
- Install docs: https://www.cvxpy.org/install/
- Updates: https://www.cvxpy.org/updates/

**Fit for this app**

The current LP can be expressed directly:

```python
import cvxpy as cp
import numpy as np

n = len(assets)
w = cp.Variable(n)
score = np.array(asset_scores)

constraints = [
    cp.sum(w) == 1,
    w >= 0,
    w <= max_weight_by_asset,
    group_matrix @ w <= group_upper_bounds,
    group_matrix @ w >= group_lower_bounds,
    scenario_return_matrix @ w >= scenario_floor_by_scenario,
    cp.norm1(w - current_weights) <= turnover_limit,
]

problem = cp.Problem(cp.Maximize(score @ w), constraints)
problem.solve(solver="HIGHS")
```

Benefits over `scipy.optimize.linprog`:

- Constraint expressions are more readable.
- Easier to add L1 turnover constraints, piecewise penalties, and soft constraints.
- Better diagnostics for infeasible models if structured carefully.
- Easier future migration to quadratic/risk-aware objectives.

Costs:

- Adds dependency complexity.
- Requires discipline to keep constraints auditable and deterministic.
- For a pure LP, `linprog(method='highs')` is already excellent.

**Verdict: watch / prototype, not urgent replacement.**

CVXPY is the best candidate if the optimiser becomes more complex. Current recommendation: build a parallel CVXPY prototype and compare outputs/infeasibility diagnostics against the existing LP. Replace only if it clearly improves maintainability or supports needed constraints that are awkward in `linprog`.

---

## Part 5: Financial Data APIs and MCP Servers

### 5.1 OpenBB Platform + openbb-mcp

**What exists**

OpenBB's Open Data Platform is positioned as a “connect once, consume everywhere” layer for financial data. It can expose data through Python, REST/FastAPI, Workspace, Excel, CLI, and MCP. The `openbb-mcp-server` library can convert a FastAPI application into an MCP server.

Sources:

- OpenBB GitHub: https://github.com/OpenBB-finance/OpenBB
- OpenBB MCP docs: https://docs.openbb.co/odp/python/extensions/interface/openbb-mcp
- OpenBB release notes: https://github.com/OpenBB-finance/OpenBB/releases
- OpenBB site: https://openbb.co/

**MCP usage shape**

OpenBB docs show local MCP server startup:

```bash
openbb-mcp
# default: http://127.0.0.1:8001
```

Then Cursor/VS Code/Claude-style MCP clients connect to the local server.

**Fit for this app**

Strengths:

- Strong candidate for v2 Claude market-insight layer.
- Good abstraction for exposing the app's own persisted data as tools/resources.
- FastAPI-to-MCP pattern is directly relevant: the app could expose local read-only endpoints for positions, scenarios, solver decisions, and market data.

Weaknesses:

- UK gilt coverage is not guaranteed from OpenBB's public/free provider set.
- Provider coverage depends on installed OpenBB extensions and API keys.
- It should not replace the current deterministic ingestion layer for core gilt analytics.

**Verdict: adopt for v2 explanation/tooling experiments.**

Best use: build a local read-only MCP server over the app's own SQLite/output state, possibly using OpenBB patterns, and separately use OpenBB for supplemental market context.

---

### 5.2 EODHD + MCP Server

**What exists**

EODHD provides paid financial data APIs and an official MCP server. Its site says the MCP server currently exposes around 75 tools and 100+ embedded docs. It also references government bond data via a `GBOND` exchange code.

Sources:

- EODHD home: https://eodhd.com/
- EODHD MCP: https://eodhd.com/financial-apis/mcp-server-for-financial-data-by-eodhd
- MCP update: https://eodhd.com/financial-apis-blog/eodhd-mcp-server-update-75-tools-oauth-and-api-versioning
- Government bonds data: https://eodhd.com/financial-apis-blog/government-bonds-data-in-economic-api

**Fit for this app**

Strengths:

- More production-grade than scraping/yfinance.
- Official MCP server lowers v2 integration friction.
- Potentially useful for global equities, ETFs, fundamentals, and historical prices.

Weaknesses:

- Paid tiers likely required for serious use.
- Need to verify actual UK gilt instrument coverage, not just generic 10-year government bond data.
- May not cover the specific retail gilt/IL gilt quote fields needed for SIPP trade decisions.

**Verdict: watch / paid fallback.**

Worth testing only if free/public sources become too brittle. Do not add as a mandatory dependency for a local private-investor tool unless coverage is verified and cost is acceptable.

---

### 5.3 Alpha Vantage + MCP

**What exists**

Alpha Vantage provides financial data APIs and an official MCP server.

Sources:

- Alpha Vantage: https://www.alphavantage.co/
- Alpha Vantage support/rate limits: https://www.alphavantage.co/support/
- Alpha Vantage MCP: https://mcp.alphavantage.co/

**Rate limits**

Alpha Vantage currently states that free API service covers most datasets up to **25 requests per day**. Community references also commonly mention 5 requests/minute.

**Fit for this app**

Strengths:

- Official MCP server.
- Easy to start.
- Useful for equities, ETFs, technical indicators, FX, and some macro/economic data.

Weaknesses:

- Free tier is too small for broad portfolio refresh if used naively.
- UK/LSE equity coverage via suffixes such as `.L` needs instrument-by-instrument validation.
- Not a gilt analytics source.

**Verdict: limited v2 context provider.**

Use for Claude experiments or occasional equity/ETF cross-checking, not as the primary data feed.

---

### 5.4 Financial Modeling Prep + MCP

**What exists**

FMP provides market data APIs, developer docs, and an MCP integration. Its MCP docs present direct integration with Claude/Cursor/custom bots. Pricing docs show a free plan with a rolling 30-day bandwidth limit and paid plans above that.

Sources:

- FMP site: https://site.financialmodelingprep.com/
- FMP MCP docs: https://site.financialmodelingprep.com/developer/docs/mcp-server
- FMP pricing: https://site.financialmodelingprep.com/pricing-plans
- FMP FAQs: https://site.financialmodelingprep.com/faqs

**Fit for this app**

Strengths:

- Broad stock/fundamental coverage.
- MCP integration available.
- Could be useful for equities, ETFs, investment trusts, REITs, and benchmark valuation data.

Weaknesses:

- UK coverage and licensing must be verified for the exact instruments.
- Not an obvious primary source for UK gilts or IL gilts.
- Free plan likely insufficient if the app refreshes many instruments often.

**Verdict: watch for equity/fundamental enrichment.**

Potentially useful for v2 market narrative. Not a core calculation dependency.

---

### 5.5 yfinance — current usage and gaps

**What exists**

yfinance remains a convenient unofficial Yahoo Finance wrapper. It supports LSE-style tickers using suffixes such as `.L`, and `yf.download(..., multi_level_index=False)` remains a practical pattern when the app wants flatter output.

Useful sources:

- yfinance GitHub issues showing 2024–2025 rate-limit problems: https://github.com/ranaroussi/yfinance/issues/2128 and https://github.com/ranaroussi/yfinance/issues/2422
- yfinance guide: https://algotrading101.com/learn/yfinance-guide/

**Known limitations**

- It is unofficial and can be rate-limited or broken by Yahoo changes.
- `.info` fields such as `trailingPE` are inconsistent, especially for non-US instruments, ETFs, funds, and investment trusts.
- UK tickers and LSE instruments often need manual mapping.
- It is fine for personal/local use, but should be cached and treated as fragile.

**Verdict: keep with caching and provider abstraction.**

Continue using yfinance for UK equity/ETF history and benchmark PE where it works, but add:

- retry/backoff;
- local cache;
- “data stale/failed” status;
- provider-specific provenance;
- fallback/cross-check via LSE/FMP/Alpha Vantage where useful.

---

### 5.6 LSEG Data Library — out of scope, for completeness

**What exists**

The LSEG Data Library for Python gives uniform access to LSEG Data Platform content through desktop or platform sessions.

Sources:

- LSEG Data Library: https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python
- Documentation: https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python/documentation
- PyPI: https://pypi.org/project/lseg-data/

**Assessment**

This is likely the best institutional answer for high-quality market data, but it requires LSEG Workspace/Eikon or platform subscription access. It is out of scope for a free/local private-investor tool.

**Verdict: out of scope.**

Document only as the “paid institutional ideal”. Do not design the app around it.

---

### 5.7 investpy / investiny

**What exists**

`investpy` is an Investing.com scraper-style library with broad historical coverage on paper. `investiny` was created by the same maintainer as a lighter, more adaptable alternative while `investpy` issues were being addressed.

Sources:

- investpy PyPI: https://pypi.org/project/investpy/
- investpy bonds docs: https://investpy.readthedocs.io/_api/bonds.html
- investiny issue note: https://github.com/alvarobartt/investpy/issues/611

**Assessment**

Because Investing.com-style access is scraping-dependent and historically fragile, it should not be a core dependency. It may provide occasional extra coverage, but the maintenance/reliability risk is not worth it for a deterministic SIPP tool.

**Verdict: skip.**

Use direct public APIs and better-known providers instead.

---

## Part 6: Open Source Trackers — context only

### 6.1 Ghostfolio

Ghostfolio is a mature open-source wealth/portfolio tracker. It is useful context but not a direct building block for this app.

Likely gap vs this app:

- Tracking and performance reporting rather than trade recommendation.
- No UK gilt/IL gilt cash-flow analytics focus.
- No SIPP-specific optimiser with friction gates, GRY switching, BoE curve signals, or scenario floors.

**Verdict: monitor UX/data-model ideas only.**

Do not rebuild on Ghostfolio unless the project goal changes from optimiser to tracker.

---

### 6.2 Wealthfolio

Wealthfolio is an open-source, local-first portfolio tracker with desktop/mobile/self-hosted options and local data storage.

Sources:

- Website: https://wealthfolio.app/
- GitHub: https://github.com/wealthfolio/wealthfolio
- Quick start docs: https://wealthfolio.app/docs/quick-start/

**Fit vs this app**

Wealthfolio aligns philosophically with local/private data, but it is still a tracker. It does not replace the app's core value: UK SIPP trade recommendations across gilts, IL gilts, equities, MMF, and cash.

**Verdict: borrow UX ideas, not architecture.**

---

## Part 7: Claude / Anthropic Integrations

### 7.1 anthropics/financial-services

**What exists**

Anthropic's financial-services repository contains reference agents, skills, and data connectors for finance workflows including wealth management. It is file-based Markdown/JSON, usable as Claude Cowork plugins or through Claude Code/Managed Agents patterns.

Sources:

- GitHub: https://github.com/anthropics/financial-services
- Anthropic support article: https://support.claude.com/en/articles/13851150-install-financial-services-plugins-for-cowork
- Anthropic finance agents news: https://www.anthropic.com/news/finance-agents
- Wealth management tax-loss harvesting skill example: https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/wealth-management/skills/tax-loss-harvesting/SKILL.md

**Relevant wealth-management skills**

The wealth-management vertical is reported to include skills/commands such as:

- `portfolio-rebalance` / `/rebalance` — allocation drift and rebalancing analysis.
- `tax-loss-harvesting` — identifies taxable-account loss harvesting opportunities.
- `financial-plan` — financial plan narrative/workflow.
- `investment-proposal` — proposal generation.
- `client-review` — meeting prep, performance, talking points.
- `client-report` — reporting narrative.

**Portability to UK SIPP context**

Portable:

- Skill structure and workflow discipline.
- Rebalance explanation patterns.
- Review/report narrative templates.
- Guardrails: do not execute trades, disclose assumptions, cite data, separate facts from recommendations.

Not directly portable:

- US tax-loss harvesting logic is mostly irrelevant inside a UK SIPP.
- Advisor/client framing should be rewritten for self-directed retail use.
- UK wrappers, SIPP rules, gilt tax quirks, RPI-linked gilts, and Interactive Investor costs require custom content.

**Recommended SIPP skill layout**

```text
plugins/sipp-investment-optimiser/
  plugin.json
  skills/
    sipp-market-review/SKILL.md
    sipp-rebalance-review/SKILL.md
    gilt-switch-analysis/SKILL.md
    il-gilt-breakeven-analysis/SKILL.md
    scenario-explainer/SKILL.md
    decision-audit-review/SKILL.md
```

Example `SKILL.md` shape:

```markdown
# Gilt Switch Analysis

Use this skill to explain whether a proposed gilt switch is attractive after spreads,
commission, tax-wrapper context, and expected holding period.

## Required inputs
- Current holding
- Candidate gilt
- Clean/dirty prices
- GRY/real GRY
- Modified duration
- Spread estimate
- Commission model
- Expected hold period
- Scenario outputs

## Rules
- Do not tell the user to trade without showing the friction gate.
- Separate deterministic calculations from market commentary.
- Cite persisted source data where available.
- Flag stale or missing prices.
```

**Verdict: adopt the format, rewrite the content.**

The Anthropic finance repo is highly relevant as a template for v2, but the SIPP optimiser needs its own UK-retail, read-only, calculation-aware skills.

---

### 7.2 OpenBB Claude Code Plugin

There are community/plugin listings for `openbb-terminal@claude-code` style integrations. Treat these as useful inspiration rather than core infrastructure unless verified directly in Claude Code's current plugin registry at implementation time.

**Verdict: optional experiment.**

For this app, a custom local MCP over the app's own SQLite state is more important than a generic OpenBB Claude Code plugin.

---

## Part 8: Additional Findings

### 8.1 Official DMO formulae are the most important validation asset

The DMO's 2024 “Formulae for Calculating Gilt Prices from Yields” is the reference document for conventional gilts, 8-month IL gilts, 3-month IL gilts, strips, and accrued interest. This should become a first-class test fixture source. If QuantLib, the app, and the DMO formulae disagree, investigate until the DMO convention is reproduced or the difference is explicitly explained.

### 8.2 BoE fitted real curves are materially underused

The app's signal layer should be expanded from a simple 6-point curve to:

- nominal spot curve;
- real spot curve;
- implied inflation term structure;
- OIS curve;
- slope/curvature metrics;
- real-yield z-scores;
- IL gilt breakeven comparison.

This is one of the highest-value data upgrades.

### 8.3 pandas-datareader is not a primary answer

`pandas-datareader` can be useful for FRED and some public economic data, but it is not the right abstraction for the app's UK gilt-specific needs. Direct BoE/ONS/DMO wrappers are clearer and more auditable.

### 8.4 FTSE Actuaries UK Gilts Index data is institutionally relevant but likely paid/licensed

LSEG/FTSE Russell publishes FTSE Actuaries UK Gilts Index Series, including conventional and index-linked gilt indices, duration/yield-related data, and maturity bands. This is highly relevant conceptually, but likely not a free retail API. Use it as a benchmark reference if accessible through fund factsheets or paid data, not as a core dependency.

### 8.5 MCP servers are abundant but equity-biased

Most financial MCP servers are oriented around equities, fundamentals, technical indicators, and news. None found in this sweep appears to solve UK gilt cash-flow analytics or retail SIPP-specific allocation. For v2, the best MCP architecture is probably:

1. app-owned local MCP server over trusted persisted state;
2. OpenBB/FMP/Alpha/EODHD as optional supplemental context providers;
3. Claude skills that know how to interpret the app's own schema.

---

## Part 9: Prioritised Recommendations

### 9.1 Adopt now

1. **Add QuantLib as a validation dependency.** Build tests comparing conventional GRY, accrued interest, duration, and IL gilt cash flows against both QuantLib and DMO formulae.
2. **Add BoE fitted curve ingestion.** Extend beyond the 6-point curve to nominal, real, implied inflation, and OIS fitted curves.
3. **Add ONS inflation ingestion.** Use ONS RPI index/growth series as primary inflation data, especially for IL gilt analysis.
4. **Provider abstraction for market data.** Wrap DMO, BoE, ONS, LSE, yfinance, and dividenddata behind explicit provider interfaces with caching, provenance, and staleness flags.
5. **Create a validation dashboard.** Show discrepancies between app-calculated yields, QuantLib yields, LSE/dividenddata displayed yields, and DMO-derived reference tests.

### 9.2 Prototype/watch

1. **CVXPY optimiser prototype.** Recreate the existing LP in CVXPY and compare readability, diagnostics, and future extensibility.
2. **skfolio research tab.** Use skfolio to compare the current policy allocator against HRP/mean-risk portfolios, but keep it out of production decisions.
3. **OpenBB/openbb-mcp.** Experiment with a local MCP server for Claude-facing analysis, but keep core calculations independent.
4. **EODHD/FMP/Alpha Vantage.** Test exact UK instrument coverage and free-tier limits before depending on them.
5. **Anthropic-style SIPP skills.** Create custom Claude skills for `gilt-switch-analysis`, `sipp-rebalance-review`, and `scenario-explainer`.

### 9.3 Skip for now

1. **Replacing the whole allocator with PyPortfolioOpt/Riskfolio-Lib.** Too much mismatch with bespoke SIPP policy constraints.
2. **FinancePy as primary bond engine.** Not stronger than QuantLib for UK gilt convention coverage.
3. **investpy/investiny.** Scrape-dependent and fragile.
4. **LSEG Data Library.** Excellent but paid/institutional and out of scope.
5. **Using MCP providers as source of truth.** MCP should explain trusted data, not silently create calculation inputs.

### 9.4 Hand-rolled component verdicts

| Component | Verdict | One-line justification |
|---|---:|---|
| GRY calculation | **Augment** | Keep transparent code, validate against DMO and QuantLib before any replacement. |
| IL gilt real GRY | **Augment urgently** | Highest convention risk; add DMO D10C/RPI and QuantLib CPIBond cross-checks. |
| Modified duration | **Augment** | Same cash-flow basis is good; validate against QuantLib and scenario repricing. |
| BoE 6-point curve fetch | **Augment** | Keep simple signal, add fitted nominal/real/OIS curves for better insight. |
| DMO ingestion | **Keep + expand** | Authoritative reference data; add more DMO reports and stronger parsing/provenance. |
| TIDM–ISIN bridge | **Keep + harden** | Seeded CSV plus monthly refresh is sensible; add source confidence and manual override. |
| Portfolio allocator | **Keep for now** | Bespoke LP is appropriate; CVXPY only if constraints/diagnostics outgrow linprog. |
| SQLite migrations | **Keep** | For a local app, `PRAGMA user_version` is acceptable if tests cover migrations. |
| Streamlit dashboard | **Keep** | Good enough for local decision support; split files/modules when maintainability suffers. |
| yfinance usage | **Keep with caution** | Useful free source but fragile; cache, backoff, and add fallback providers. |
| LSE price explorer | **Keep with caution** | Useful personal/local source, but unofficial and licensing-sensitive. |
| dividenddata.co.uk | **Fallback only** | Helpful cross-check, not authoritative. |

---

## Appendix A: Suggested immediate implementation tickets

### T1 — QuantLib validation harness

- Add optional dependency `QuantLib>=1.40`.
- Build `tests/analytics/test_quantlib_conventional_gilts.py`.
- Build `tests/analytics/test_quantlib_index_linked_gilts.py`.
- Add DMO formulae-derived test cases for conventional and IL gilts.
- Output discrepancies to a validation report.

### T2 — BoE fitted curve client

- Create `src/data_sources/boe.py`.
- Add `get_bank_rate`, `get_nominal_curve`, `get_real_curve`, `get_ois_curve`, `get_implied_inflation_curve`.
- Persist raw CSV/JSON and normalised tables.
- Add signal cards: real yield level, implied inflation slope, OIS-vs-gilt spread.

### T3 — ONS inflation client

- Create `src/data_sources/ons.py`.
- Add series catalogue with `CHAW`, `CZBH`, CPI, CPIH.
- Persist raw response and normalised monthly observations.
- Use ONS RPI as source for IL gilt reference-index logic where appropriate.

### T4 — Provider abstraction

```python
class MarketDataProvider(Protocol):
    name: str
    def fetch_quote(self, instrument_id: str) -> Quote: ...
    def fetch_history(self, instrument_id: str, start: date, end: date) -> pd.DataFrame: ...
```

Add provider health metadata:

```python
@dataclass
class DataProvenance:
    provider: str
    source_url: str
    fetched_at: datetime
    as_of_date: date | None
    raw_snapshot_id: str
    confidence: Literal["authoritative", "official", "unofficial", "fallback"]
```

### T5 — Local SIPP MCP proof of concept

Expose read-only tools/resources:

- `get_portfolio_state`
- `get_solver_recommendation`
- `get_trade_friction_breakdown`
- `get_scenario_results`
- `get_signal_cards`
- `get_data_staleness_report`

Claude should never write directly to the optimiser database.

