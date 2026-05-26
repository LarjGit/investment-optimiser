# External Tooling Research
## Investment Optimiser — UK SIPP Portfolio Allocation Tool

*Generated: 2026-05-26*

---

## Executive Summary

- **Keep the hand-rolled GRY and IL gilt engine for now; augment with rateslib for validation.** QuantLib is viable but the SWIG binary is opaque and IL gilt support requires care around deprecated constructor signatures. FinancePy is inactive. rateslib (v2.7.1) has explicit UK DMO mode and ex-dividend support but carries a non-commercial-only licence — fine for a private investor's local tool but worth documenting.

- **The DMO XML endpoint only exposes conventional gilts (D1A); D1D has no XML export.** This is already known to the codebase (see `2026-05-19-dmo-d1a-only-xml-feed.md`). The additional DMO report codes (D5D issuance calendar, D10C for IL index ratios) are worth adding; they are available and documented below.

- **The BoE fitted yield curve data (Anderson-Sleath nominal, real, OIS, implied inflation) is available as daily-updated Excel ZIPs — not via the IADB CSV API.** The IADB covers only three par yield maturities (5y, 10y, 20y). The real spot curve from the ZIP is directly useful for IL gilt breakeven analysis and is currently untapped.

- **For the V2 LLM layer, OpenBB Platform + openbb-mcp-server (v1.4.0, April 2026) is the strongest free option** for a multi-source unified financial data MCP. Alpha Vantage MCP and EODHD MCP both have free tiers too thin for production use (25 req/day and 20 req/day respectively). FMP has no gilt data. The anthropics/financial-services wealth-management plugin is US-market-centric (IRA, wash-sale rules) and not portable without significant rewriting, but its skill authoring format is directly replicable.

- **scipy.optimize.linprog(method='highs') is a defensible solver for a continuous LP** at this problem size. CVXPY (which skfolio and Riskfolio-Lib both wrap) brings richer constraint diagnostics and non-LP objective functions. The migration path from linprog to CVXPY is low-cost and worth considering for v2 when scenario-CVaR floors are added.

---

## Part 1: Architectural Flags (brief — only material issues)

**BoE yield curve coverage gap.** The IADB CSV API route only returns 5y, 10y, 20y nominal par yields. The app currently sources the 1y/2y/30y points (and all real curve points) from separate Excel ZIP archives. The BoE also publishes fitted real spot curves and implied inflation term structures in those same ZIPs. These are directly useful for IL gilt breakeven analysis, but the app does not currently consume them. This is a data-richness gap, not a correctness bug — the codebase already documents the ZIP parsing approach.

**TIDM–ISIN bridge fragility.** dividenddata.co.uk is correctly identified as the free source for this bridge (documented in `2026-05-19-lse-tidm-bridge-no-public-api.md`). It is an HTML scrape of an unaffiliated third-party site with no API contract. No viable alternative exists at zero cost — OpenFIGI returns Bloomberg-style bond descriptors, not LSE TIDMs. The bundled CSV fallback is the right defence. This is a known architectural fragility, not an oversight.

**IL gilt analytics: the 3-month lag is correct, but the observation interpolation is flat by convention.** UK DMO IL gilts use flat (not linear) interpolation of the reference RPI for coupon/redemption calculations, matching `ql.CPI.Flat` in QuantLib and the `"uk_gb"` calc_mode in rateslib. The hand-rolled engine should verify it uses flat interpolation; linear interpolation is subtly wrong for UK gilts.

---

## Part 2: UK Public Data Sources

### 2.1 DMO XML API

**Endpoint pattern:**
```
https://www.dmo.gov.uk/data/XmlDataReport?reportCode={CODE}
```

**Available XML report codes (confirmed working):**

| Code | Description | Key fields |
|------|-------------|------------|
| `D1A` | Gilts in Issue (both conventional and IL) | `ISIN_CODE`, `INSTRUMENT_TYPE`, `INSTRUMENT_NAME`, `MATURITY_BRACKET`, `REDEMPTION_DATE`, `DIVIDEND_DATES`, `CURRENT_EX_DIV_DATE`, `FIRST_ISSUE_DATE`, `TOTAL_AMOUNT_IN_ISSUE`, `TOTAL_AMOUNT_INCLUDING_IL_UPLIFT`, `BASE_RPI_87` |
| `D10C` | IL gilt index ratios by settlement date | `INSTRUMENT_NAME`, `ISIN_CODE`, `SETTLEMENT_DATE`, `INDEX_RATIO_OR_RPI`, `REFERENCE_RPI` |

**Critical known issue:** `D1D` (IL Gilts in Issue as a separate report) **cannot be exported as XML** — only PDF. D1A already contains both conventional (`INSTRUMENT_TYPE = "Conventional "` with trailing space) and index-linked (`INSTRUMENT_TYPE = "Index-linked 3 months"` or `"Index-linked 8 months"`) gilts in a single feed. Strip and normalise `INSTRUMENT_TYPE` before insertion.

**PDF-only reports of potential interest:**

| Code | Description |
|------|-------------|
| `D5D` | Outright Gilt Issuance Calendar (quarterly refinement) |
| `D5J` | Events Calendar |
| `D2.1E` | Gilt Issuance History |

**PDF reports accessible via:** `https://www.dmo.gov.uk/data/pdfdatareport?reportCode={CODE}`

**Update cadence:** D1A updates on business days. D10C updates daily with RPI reference data. PDF reports update as events occur.

**Known quirks:**
- `INSTRUMENT_TYPE` field has a trailing space on conventional records
- `BASE_RPI_87` is present in D1A for IL gilts (the initial RPI reference, base Jan 1987=100)
- D10C is under-documented but yields live RPI uplift ratios useful for IL gilt dirty price calculation
- No REST API documentation is published; the XML URL pattern is community-discovered

**Verdict: keep as-is.** The DMO XML endpoint is the authoritative free source for gilt reference data. No commercial alternative covers this data at zero cost. D10C could usefully supplement the current implementation for real-time RPI ratios.

---

### 2.2 Bank of England Statistics Database

**Two separate access methods — not interchangeable:**

**Method 1: IADB CSV API** (for individual named series)
```
https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes
  &SeriesCodes=IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY
  &UsingCodes=Y
  &CSVF=TN
  &Datefrom=01/Jan/2024
  &Dateto=now
  &VPD=Y
```
- Up to 250 series codes per request
- Response: CSV with date column and one column per series
- `CSVF=TN` = tabular, no titles (easiest to parse)
- No API key required, no documented rate limit (empirical experience: respectful polling is fine)

**Confirmed IADB series codes:**

| Series | Description |
|--------|-------------|
| `IUDBEDR` | Bank Rate (BoE base rate) — daily |
| `IUDSOIA` | SONIA overnight rate — daily |
| `IUDSNPY` | 5-year nominal par gilt yield |
| `IUDMNPY` | 10-year nominal par gilt yield |
| `IUDLNPY` | 20-year nominal par gilt yield |
| `IUAAMNPY` | 10-year nominal par yield (annual average variant) |

**Critical gap:** 1y, 2y, and 30y par yield series do **not exist** in the IADB. No series codes for these maturities have been found after exhaustive search (confirmed in `2026-05-18-boe-iadb-only-three-par-yield-maturities.md`).

**Method 2: Excel ZIP archives** (for fitted yield curves at all maturities)

The BoE publishes daily Anderson-Sleath fitted yield curves in Excel ZIP files:

| Archive | URL | Curves included |
|---------|-----|-----------------|
| Nominal | `https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?...` (or direct static link) | Spot rates, forward rates (0.5y to 25y) |
| Real (IL) | Similar pattern | Spot, forward (IL gilt-implied real rates) |
| OIS | Similar pattern | Overnight Index Swap nominal curve |
| Implied inflation | Derived | Breakeven inflation term structure |

Known ZIP filename pattern: `glcnominalddata.zip` (nominal); equivalent ZIPs exist for real and OIS curves.

**Key implementation facts** (confirmed in `2026-05-22-boe-spot-curve-zip-structure.md`):
- Each ZIP contains multiple XLSX files split by date range; the current file is the last alphabetically
- Sheet name is `"4. spot curve"` in post-2005 files; `"4. nominal spot curve"` in pre-2005 files
- Rows with `None` at position 0 are phantom rows from openpyxl reading stale XML dimension metadata — skip them
- Publication lag: ZIP archives update with a 3–4 week lag; IADB CSV API updates daily
- Data starts at row 5 after a 4-row preamble (title, blank, "Maturity", maturity headers)

**Relevant ONS/BoE inflation series for IL gilt analysis:**
- BoE IADB does not appear to expose RPI or CPI series directly — use ONS API for these (see 2.3)

**pyscraper (https://github.com/jzuccollo/pyscraper):** Archived March 2025 as explicitly "no longer maintained or needed." Its `from_BoE(series, datefrom, yearsback)` function can serve as reference for the IADB URL pattern but should not be taken as a dependency.

**BOE-API/BOE_API (https://github.com/BOE-API):** GitHub organisation exists but repositories are thin and not widely adopted. Not recommended as a dependency.

**Bank of England GitHub (https://github.com/bank-of-england):** 11 repositories. All are research/ML/visualisation tools (Shapley regressions, crisis prediction, occupationcoder, forecast_evaluation, boeCharts). No Python tooling for statistical data access. The official BoE has not published an API wrapper library.

**Verdict: keep as-is for IADB; add real/OIS curve parsing from ZIP for v2.** The real spot curve from the ZIP archive would unlock IL gilt breakeven analysis (implied RPI vs actual RPI). This is an enhancement, not a correction.

---

### 2.3 ONS API

**Base URL:** `https://api.beta.ons.gov.uk/v1`  
**Authentication:** None required  
**Rate limits:** 120 requests/10 seconds, 200 requests/minute

**Time series endpoint pattern:**
```
GET https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{SERIES_CODE}/mm23/data
```

**Response JSON schema:**
```json
{
  "years": [...],
  "quarters": [...],
  "months": [
    {
      "date": "2026 May",
      "value": "408.7",
      "label": "May 2026",
      "year": "2026",
      "month": "May",
      "quarter": "",
      "sourceDataset": "MM23",
      "updateDate": "2026-05-20T00:00:00"
    }
  ]
}
```

**Key series codes:**

| Series | Description |
|--------|-------------|
| `CHAW` | RPI All Items Index (Jan 1987=100) — this is the raw index level used for IL gilt uplift calculations |
| `CZBH` | RPI All Items: % change over 12 months |
| `CZEQ` | RPI: % change over 1 month |
| `D7BT` | CPI All Items Index (2015=100) |
| `L55O` | CPIH All Items Index |

The CHAW series (monthly, back to Jan 1987) is the most important for IL gilt calculations. The most recent CZBH release was 20 May 2026; next release 17 June 2026.

**Relationship to BoE data:** The ONS is the authoritative source for RPI index levels. The BoE IADB does not expose raw RPI index values — only derived yield series. For IL gilt reference RPI and coupon calculations, the ONS API is the correct source. The BoE fitted real curve is derived from market gilt prices, not directly from ONS RPI series.

**`dcorney/ons_api_demo` (https://github.com/dcorney/ons_api_demo):** A useful reference/demo notebook for the ONS beta API. Not a library; pure illustration.

**Verdict: augment.** The CHAW series via the ONS API is a clean, free, documented source for the RPI monthly index values needed for IL gilt uplift calculations. If the app is currently sourcing RPI values from another route (e.g., BoE), migrate to direct ONS API calls for CHAW. The JSON schema is stable and the rate limits are generous for a local tool.

---

### 2.4 LSE Price Explorer API

The LSE does not publish a documented public API for bulk data access. The full instrument database (including TIDMs and ISINs) is the Daily Tradable Instruments (DTI) report, delivered only via LSEG's commercial Managed File Transfer service.

**What the app uses:** The "price-explorer" URL pattern is a community-discovered endpoint against LSE's web UI infrastructure. It is not contractually stable.

**Coverage for non-gilt instruments:** The LSE price-explorer UI covers equities, ETFs, investment trusts, and other LSE-listed instruments via TIDM lookup. However, scraping individual instrument pages is fragile (HTTP 403 risk, DOM changes, no documented schema). For equities, yfinance with `.L` suffix is more reliable for price history.

**TIDM–ISIN bridge:** The dividenddata.co.uk HTML tables remain the only known free source for gilt TIDM resolution. OpenFIGI returns Bloomberg-style bond descriptors (e.g. `"UKT 0 1/2 10/22/61"`) rather than LSE TIDMs — confirmed non-viable (see `2026-05-19-lse-tidm-bridge-no-public-api.md`).

**Verdict: keep as-is.** The current approach (seeded CSV + monthly dividenddata.co.uk refresh) is the best available free option. Document the fragility and maintain the CSV fallback.

---

### 2.5 dividenddata.co.uk

**URL:** `https://www.dividenddata.co.uk/uk-gilts-prices-yields.py` (conventional gilts)  
`https://www.dividenddata.co.uk/index-linked-gilts-prices-yields.py` (IL gilts)

**What it provides:** HTML tables listing all gilts currently in issue with:
- EPIC (TIDM) — e.g. `TN28`
- Name, coupon, maturity date
- Current clean price, GRY (calculated yield)
- Accrued interest, dirty price (available on individual gilt pages)

**Data provenance:** The site appears to derive prices from market sources (likely LSE or Tradeweb), updated intraday. It is a third-party aggregator with no documented API contract. Last observed update date: 22 May 2026.

**Reliability assessment:** The site has been stable enough to be the basis of the production TIDM bridge. It returns standard HTML tables, parseable with `pandas.read_html()`. The main risks are:
1. Structural HTML changes breaking the table parser
2. The site going offline or adding bot protection (no Cloudflare currently observed)
3. Stale data during market closures or system issues

**As a price cross-check:** dividenddata.co.uk calculates and displays GRY values, but its methodology is undocumented. Using it as a cross-check for the app's GRY engine is useful but not authoritative (DMO/LSE/Tradeweb prices are the ground truth).

**Verdict: keep as-is for TIDM bridge; treat as useful but non-authoritative for price cross-checking.** The bundled CSV fallback is the correct defence against availability failures. Do not make price data directly dependent on this source.

---

## Part 3: Bond Analytics Libraries

### 3.1 QuantLib / QuantLib-Python

**Current version:** 1.42.1 (released April 17, 2026)  
**PyPI:** `pip install QuantLib`  
**Windows:** Pre-built wheels available for x86-64 across Python 3.8–3.14. No compile required; SWIG bindings are pre-generated. `uv add QuantLib` works cleanly.  
**Licence:** BSD-3-Clause, fully open source, commercial use permitted.

**UK conventional gilt support:**
- Day count: `ql.ActualActual(ql.ActualActual.ICMA)` — correct for UK gilts
- Settlement: `settlementDays=1` for T+1
- Ex-dividend: QuantLib's `FixedRateBond` does not natively support the UK ex-dividend period (7 business days before coupon). Modelling this requires either a custom cash-flow schedule that excludes ex-div coupons or a workaround. This is a real gap for computing dirty price and accrued interest precisely during the ex-div window.
- Calendar: `ql.UnitedKingdom()` provides the correct England & Wales bank holiday calendar

**IL gilt support (`CPIBond` + `UKRPI`):**
```python
import QuantLib as ql

index = ql.UKRPI(False)  # False = not interpolated (flat observation)
obs_lag = ql.Period(3, ql.Months)  # UK DMO: 3-month lag
interpolation = ql.CPI.Flat  # UK convention; NOT ql.CPI.Linear

bond = ql.CPIBond(
    1,           # settlementDays (T+1)
    face_amount,
    False,       # growthOnly (deprecated in C++, use False)
    base_cpi,
    obs_lag,
    index,
    interpolation,
    schedule,
    [fixed_rate],
    ql.ActualActual(ql.ActualActual.ICMA),
)
```

**Deprecation note (from QuantLib docs):** The `growthOnly` parameter is already deprecated in the underlying C++ library and will be removed from Python bindings in a future release. Set to `False` and note it for future migration.

**What QuantLib does NOT handle automatically for UK IL gilts:**
- The "floor guarantee" (RPI index ratio never below 1.0) is not built into `CPIBond` by default — must be enforced in the cash flow construction
- The 3-month observation lag uses the RPI published for the month three months prior, not interpolated — this is correctly modelled by `ql.CPI.Flat`
- The accrual of the "running" dirty price between settlement and maturity requires careful handling of the `baseCPI` parameter; it must match the gilt's prospectus base RPI

**Windows install story:** Clean with `pip install QuantLib` or `uv add QuantLib`. Pre-built wheels exist for all Python versions. No MSVC or SWIG install required. Build time: seconds (downloading a ~15MB wheel).

**Using QuantLib as validation layer:** The most practical approach is to keep the hand-rolled engine as primary and add a QuantLib `cross_check_gry(isin, clean_price, settlement_date)` function that runs in tests and flags discrepancies above a tolerance (e.g. 1bp). This requires a one-time setup cost but provides a strong regression safety net.

**Verdict: augment.** Use QuantLib as a validation/regression-test layer for GRY calculations, not as a drop-in replacement. The hand-rolled engine is more transparent about the UK-specific conventions it enforces (ex-div window, RPI floor guarantee). A QuantLib cross-check would catch any drift in the hand-rolled engine. Full replacement would increase dependency weight and reduce convention visibility without material accuracy gain.

---

### 3.2 FinancePy

**Latest version:** 0.360 (May 1, 2024) — over a year without a PyPI release as of May 2026.  
**GitHub:** https://github.com/domokane/FinancePy — 3,000+ stars, 404 forks, but last PyPI release is May 2024. Development continues but releases are infrequent.  
**Maintenance status:** Beta, intermittently maintained. Snyk advisor classifies it as "Inactive" based on release cadence.  
**Windows compatibility:** Pure Python + NumPy/Numba/SciPy stack — no C++ compile, installs cleanly.

**UK gilt convention support:** FinancePy does implement `ActualActual(ICMA)` day count and has UK bond pricing modules, but the documentation and implementation of ex-dividend handling for UK gilts is not clearly documented. IL gilt support with the 3-month RPI lag is not confirmed in published documentation.

**Compared to QuantLib:** FinancePy is lighter (no C++ / SWIG) but less actively maintained for the specific UK government bond conventions this app needs. It lacks the institutional test coverage and community validation that QuantLib provides.

**Verdict: not in the running.** The stale release cadence and unclear IL gilt support make FinancePy a poor choice relative to either QuantLib (for validation) or the existing hand-rolled engine (for production). Skip.

---

### 3.3 rateslib (additional finding — not in original scope)

**PyPI:** `pip install rateslib` — version 2.7.1, released April 4, 2026. Actively maintained.  
**Licence:** Creative Commons BY-NC-ND 4.0 (source-available, non-commercial). **Free for a private investor's local tool; not licenced for commercial use.**  
**Windows:** Pre-built wheels for x86-64, ARM64, and i686.

**UK gilt support:**
- `FixedRateBond(calc_mode="uk_gb")` — explicit UK DMO calculation mode
- Ex-dividend: `bond.ex_div(settlement_date)` returns `True/False` using UK DMO convention (7 business days before coupon)
- `ActActICMA` day count convention is supported
- `IndexFixedRateBond` class for inflation-linked bonds

**IL gilt specifics:** The `IndexFixedRateBond` class exists and is documented, but specific confirmation of the 3-month flat RPI lag for UK DMO IL gilts requires reading the source or running tests. The `"uk_gb"` calc_mode strongly suggests DMO-compliant implementation.

**Why it's interesting:** rateslib's explicit `calc_mode="uk_gb"` and documented ex-dividend support mean it would cross-check the hand-rolled engine more faithfully than QuantLib (which requires manual ex-div handling). For a non-commercial private investor tool, the CC-BY-NC-ND licence is permissive.

**Verdict: worth evaluating as a validation layer alongside or instead of QuantLib.** The UK DMO mode and ex-div support are precisely what the app needs. Licence is clear and permissive for this use case.

---

## Part 4: Portfolio Optimisation Libraries

### 4.1 skfolio

**Current version:** 0.20.1 (April 21, 2026). Rapid release cadence (7 releases in April 2026 alone).  
**Academic paper:** arXiv 2507.04176, "skfolio: Portfolio Optimization in Python" — published July 2025, covered in MarkTechPost May 2026.  
**PyPI:** `pip install skfolio`  
**Dependencies:** numpy, scipy, pandas, scikit-learn ≥1.6.0, cvxpy-base ≥1.5.0, clarabel ≥0.9.0, plotly  
**Windows:** No native extensions; installs cleanly.

**Supported objective functions:**
- Minimize Risk (default)
- Maximize Returns
- Maximize Utility
- Maximize Ratio (Sharpe, Sortino, etc.)

**Constraint API (relevant to this app):**
- Turnover constraints: `TurnoverConstraint(max_turnover=0.2)` 
- Group cardinality constraints (concentration caps per bucket)
- Linear constraints: custom expressions like `"Equity <= 0.5 * Portfolio"`
- Weight min/max per asset
- Transaction costs and management fees

**Handling assets without return history:** The `SelectComplete` transformer handles late inception, delisting, and missing history. For assets like short-dated gilts where GRY is the correct expected return proxy rather than historical returns, skfolio does support custom expected returns via `mu` parameter injection — you can pass a pandas Series of analytical expected returns (e.g. GRY for gilts, statistical mean for equities) into any mean-risk model. This is the key use case: mixed analytical/statistical expected returns in a single optimisation.

**Comparison to `scipy.optimize.linprog`:**
- linprog solves LP (linear objective, linear constraints) — works for a linear attractiveness-score objective
- skfolio wraps CVXPY (clarabel solver), which handles LP, QP, and convex objectives
- For a purely linear attractiveness score objective, linprog is not wrong; skfolio adds: walk-forward cross-validation, CVaR/CDaR risk floors, better constraint debugging, and portfolio comparison tooling
- The scenario-floor constraints planned for v2 (e.g. "portfolio must survive a 200bp yield shock") are more naturally expressed in skfolio/CVXPY than in linprog's A_ub/b_ub matrix formulation

**Migration cost from linprog:** Medium. The current constraint matrices (A_ub, b_ub) would need to be reimplemented as skfolio constraint objects. The LP objective would map to `ObjectiveFunction.MAXIMIZE_RETURN` with a custom expected return vector. Estimated 2–3 days of work for a clean migration.

**Verdict: consider for v2 when scenario-CVaR floors are added.** The current linprog approach is defensible for a linear attractiveness-score LP. The migration to skfolio becomes worthwhile when: (a) non-linear risk objectives are needed (CVaR floor), or (b) the tilt-band joint infeasibility debugging tools are needed (CVXPY gives better infeasibility certificates than HiGHS via linprog). Keep on the watchlist; do not migrate yet without a concrete v2 reason.

---

### 4.2 PyPortfolioOpt

**Current version:** 1.6.0 (February 26, 2026). Actively maintained.  
**Licence:** MIT  
**Dependencies:** cvxpy, pandas, scikit-learn, numpy, scipy  

**Black-Litterman with gilt yield views:** PyPortfolioOpt's Black-Litterman module (`BlackLittermanModel`) accepts absolute or relative views as a dict or Series. Gilt GRY values could be injected as absolute views (`{"TG32": 0.045}` = "we believe TG32 will return 4.5%"). The posterior expected returns can then feed the efficient frontier optimiser.

**Constraint API:** Supports weight constraints, sector constraints, and custom linear constraints. The API is less expressive than skfolio for complex multi-constraint problems (turnover limits, joint infeasibility detection).

**Gap for this use case:** PyPortfolioOpt assumes a covariance matrix is central to the optimisation. Short-dated gilts held to maturity have near-zero return variance — the covariance matrix degeneracy is a practical problem. skfolio's `SelectComplete` and the ability to fix expected returns for specific assets handles this more cleanly.

**Verdict: second choice behind skfolio.** PyPortfolioOpt is well-maintained and the Black-Litterman module is genuinely useful for injecting yield views as priors. However, skfolio is more capable for mixed analytical/statistical return models and has a richer constraint API. If Black-Litterman is the primary v2 upgrade, PyPortfolioOpt is fine; if scenario-risk floors are the priority, use skfolio.

---

### 4.3 Riskfolio-Lib

**Current version:** 7.2.1 (February 18, 2026).  
**Licence:** BSD-3-Clause (commercial use permitted)  
**CVXPY dependency:** cvxpy ≥1.7.2  
**Windows install:** `pip install riskfolio-lib` — Visual Studio Build Tools may be required for CVXPY from source, but pre-built CVXPY wheels are available so in practice `pip install riskfolio-lib` works without a C++ compiler.

**Risk measures:** 24 convex risk measures (MV, MAD, CVaR, CDaR, EVaR, Tail Gini, etc.). CVaR is the most relevant for scenario-floor constraints ("portfolio must survive a 200bp gilt yield shock").

**Constraint support:** Linear constraints, risk-measure constraints, cardinality constraints, and scenario-based constraints. The scenario-based constraints are more native in Riskfolio-Lib than in PyPortfolioOpt.

**Gap for this use case:** Like PyPortfolioOpt, Riskfolio-Lib centres on a historical returns covariance matrix. For gilts where GRY is the expected return, custom return injection is possible but requires more plumbing than in skfolio.

**Verdict: viable but skfolio is preferred.** Riskfolio-Lib is better than skfolio for CVaR-heavy institutional portfolios. For this SIPP tool, skfolio's scikit-learn API and cleaner handling of mixed analytical/statistical returns is a better fit. Both wrap CVXPY, so the solver capability is equivalent.

---

### 4.4 CVXPY directly

**Current version:** ~1.6.x (underlying skfolio and Riskfolio-Lib)  
**Install:** `pip install cvxpy` — pre-built wheels on Windows, no MSVC required  
**Default solver:** Clarabel (open-source, fast LP/QP/SOCP)  
**Also supports:** HiGHS (same LP solver as `scipy.optimize.linprog(method='highs')`)

**Advantage over `scipy.optimize.linprog`:** CVXPY's modelling language is declarative rather than matrix-form:
```python
# linprog formulation (current):
result = linprog(-c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')

# CVXPY equivalent (more readable, better debugging):
w = cp.Variable(n)
objective = cp.Maximize(c @ w)
constraints = [A_ub @ w <= b_ub, w >= 0, cp.sum(w) == 1]
prob = cp.Problem(objective, constraints)
prob.solve(solver=cp.HIGHS)
print(prob.status)  # "optimal", "infeasible", etc. — better diagnostics
```

CVXPY gives infeasibility certificates (dual variables, constraint violations) that make tilt-band joint infeasibility debugging much easier. The `docs/solutions/2026-05-20-lp-turnover-tilt-band-joint-infeasibility.md` solution shows the app has already hit infeasibility debugging problems — CVXPY would have surfaced the cause faster.

**Migration cost from linprog:** Low (1–2 days). The same HiGHS solver is available. The objective and constraint matrices map directly. The return on investment is better infeasibility diagnostics.

**Verdict: worth considering as a direct linprog replacement in v1.5.** Swap `scipy.optimize.linprog` → CVXPY with `solver=cp.HIGHS` for identical solve results plus better diagnostics. This is a lower-risk step than adopting a full portfolio optimisation framework. Serves as a stepping stone to skfolio for v2.

---

## Part 5: Financial Data APIs and MCP Servers

### 5.1 OpenBB Platform + openbb-mcp

**openbb-mcp-server version:** 1.4.0 (April 10, 2026). Actively developed.  
**Licence:** AGPL-3.0 (open source, free for all uses including commercial)  
**Install:** `pip install openbb-mcp-server` then `openbb-mcp` to launch  
**Python:** 3.10+  
**OpenBB Platform licence:** AGPL — same

**What the MCP server exposes:**
- Tool categories: equity, crypto, economy, news, fixed income/bonds, derivatives, ETFs, currencies, commodities, market indices, regulatory data
- Admin tools: `available_categories`, `available_tools`, `activate_tools`, `deactivate_tools`
- Tools are dynamically discovered and session-activated — Claude only loads the tools it needs
- "Skill guides" (markdown documents) are exposed as MCP resources and teach Claude multi-step workflows

**UK data coverage:** Not explicitly documented in the MCP server docs. Coverage depends on which OpenBB provider extensions are installed. The underlying OpenBB platform wraps multiple data providers (yfinance, Alpha Vantage, FMP, EODHD, and others). UK equity data via yfinance (`.L` suffix) is likely available through the equity category. Gilt data is not confirmed.

**LSEG MCP server (separate):** LSEG launched its own MCP server in December 2025, with plans to add FTSE Russell indices data. This is a paid/enterprise service — not relevant for a free tier tool.

**Free vs paid:** OpenBB Platform itself is free (AGPL). Individual data provider API keys may be required for certain datasets (e.g. Alpha Vantage, FMP). yfinance-backed routes require no key.

**Windows install story:** Standard `pip install` — no native extensions in the MCP server itself. OpenBB Platform has some optional C extensions but the core installs cleanly.

**V2 relevance:** For the planned LLM market insight layer, `openbb-mcp-server` is the strongest free unified option. Claude can call it to fetch current gilt prices, equity data, economic indicators, and news in a single tool ecosystem. The skill guide pattern (MCP resources teaching multi-step workflows) is directly analogous to what the app's V2 architecture will need.

**Verdict: adopt for v2.** This is the recommended MCP integration point for the Claude market insight layer. Install `openbb-mcp-server` alongside the app's own MCP server. Data provider coverage should be confirmed empirically by testing gilt-specific queries.

---

### 5.2 EODHD + MCP Server

**MCP server:** 77 tools, includes bond screening via PRAAMS (`get_mp_praams_bond_analyze_by_isin`)  
**GBOND exchange:** 117 active tickers listed (e.g. `UK10Y.GBOND`, `UK1Y.GBOND`) — primarily benchmark yield indices, not individual named gilts  
**Free tier:** 20 API calls/day — effectively unusable for any real-time data use  
**First paid tier:** ~£20/month (EOD historical, all world, 100,000 calls/day)  
**IL gilt data:** Not documented; individual named gilts (e.g. "4% Treasury Gilt 2038") appear to be accessible via ISIN but coverage depth is unclear

**Assessment:** The GBOND exchange offers benchmark yields rather than individual gilt prices. The PRAAMS bond analytics tools are interesting (risk/return analysis by ISIN) but at 20 free calls/day the tier is unusable. At £20/month, it could supplement the app's gilt pricing data but dividenddata.co.uk + LSE price explorer provide equivalent data for free.

**Verdict: skip.** Free tier is too thin. Paid tier is unnecessary given existing free sources. The 77-tool MCP server is impressive but gilt-specific coverage is not clearly better than OpenBB.

---

### 5.3 Alpha Vantage + MCP

**Official MCP:** `mcp.alphavantage.co` — 150+ tools across 9 categories  
**UK equity coverage:** London Stock Exchange listed in "20+ global exchanges"; standard equity time series available for `.L` suffix symbols  
**Free tier:** 25 requests/day, 5 requests/minute — marginally above useless for automated tasks  
**No gilt data:** Fixed income coverage is limited to US Treasury yields; UK gilts are not documented  

**Verdict: skip for this use case.** The free tier is too restrictive and there is no gilt data. UK equity prices via `.L` are already handled by yfinance at no cost.

---

### 5.4 Financial Modeling Prep + MCP

**MCP server:** Available, wraps FMP API  
**Free tier:** 250 calls/day, EOD data only, ~5-year history  
**UK equity coverage:** LSE listed (GMT timezone)  
**Bond data:** FMP explicitly does not offer bond data  
**Gilt data:** Not available  

**Verdict: skip.** No gilt data. UK equity data available from yfinance at no cost with higher call limits.

---

### 5.5 yfinance (current usage and gaps)

**Current version:** 1.4.0 (May 23, 2026). Actively maintained.  
**Recent releases:** 1.3.0 (April 2026), 1.2.x (February–April 2026) — significant version velocity  
**Licence:** Apache 2.0

**Current usage in the app:**
- `.L` suffix for LSE-listed equities (confirmed working)
- `yf.Ticker('SWRD.L').info['trailingPE']` for benchmark PE (known to be unreliable for ETFs — see `2026-05-19-yfinance-trailing-pe-lse-etf-reliability.md`)
- `yf.download()` for price history

**Known limitations as of 2026:**
- `trailingPE` is absent or `None` for most LSE ETFs — treat as first-class unavailable state, not an error
- Rate limiting (429 errors) from Yahoo Finance is a real operational risk, especially with repeated automated runs; yfinance 1.x added exponential backoff but the underlying Yahoo rate limit is not publicly documented
- `.info` dict shape varies by instrument type (ETFs get a reduced subset vs equities)
- `multi_level_index=False` is the correct pattern for batch `yf.download()` to get a flat DataFrame; this API is confirmed stable in 1.x
- Investment trusts (e.g. Monks Investment Trust) have `quoteType == "EQUITY"` in yfinance despite being investment trusts — confirmed in `2026-05-22-yfinance-investment-trust-quoteType-is-equity.md`
- Intraday quotes require `period="1d"` or similar parameters for current-day prices — `yf.download()` returns previous close by default

**Is there a better free alternative for UK equity prices?**
- Not at zero cost with comparable coverage. Twelve Data lists LSE as a supported exchange but the free tier is 8 requests/minute / 800 requests/day — adequate for a local tool but requires an API key.
- EODHD covers LSE equities at £20/month but not justified given yfinance coverage.
- For benchmark PE (the main unreliable field), there is no clean free alternative. The app should use the "unavailable" state when `trailingPE` is absent rather than blocking.

**Verdict: keep as-is.** yfinance 1.4.0 is actively maintained and provides adequate UK equity coverage for a local tool. The known gaps (ETF PE, rate limiting) are documented and handled. No free alternative is materially better.

---

### 5.6 LSEG Data Library for Python

**Requires:** LSEG Workspace subscription (institutional, ~£20,000+/year equivalent)  
**Covers:** Real-time and historical prices for all LSE instruments, full gilt data, corporate actions, fundamentals

**Out of scope** for this tool. Documented for completeness. If Interactive Investor ever exposes a customer data API (they do not as of May 2026), that would be a more relevant LSEG-adjacent data source.

---

### 5.7 investpy / investiny

**investpy:** Permanently broken (Cloudflare v2 protection on Investing.com since 2022–2023). Archived. Do not use.

**investiny (https://github.com/alvarobartt/investiny):**  
- Last PyPI release: v0.1.0 (October 2022). No releases since.  
- Status: Effectively abandoned. Open issues include 403 errors against Investing.com (same Cloudflare issue that killed investpy).
- The project was created as a temporary bridge while investpy was fixed; that fix never materialised.

**Verdict: skip both.** Neither covers functionality not already available from yfinance + DMO + BoE + ONS. Do not take a dependency on either.

---

## Part 6: Open Source Trackers (brief — context only)

### 6.1 Ghostfolio

**GitHub:** https://github.com/ghostfolio/ghostfolio  
**Self-hosted, open source (AGPL)**  
**Primary asset classes:** Stocks, ETFs, cryptocurrencies — these are the explicitly documented types  
**UK specifics:** Generic GBP currency support; no documented ISA, SIPP, or tax wrapper modelling; no gilt or government bond support  
**Why it's not relevant:** Ghostfolio tracks and visualises portfolios; it does not optimise allocations, calculate gilt GRY, or model IL gilt cash flows. It is a portfolio tracker, not a decision-support tool.

---

### 6.2 Wealthfolio

**Website:** https://wealthfolio.app/  
**Desktop app (Tauri/Rust), open source**  
**Primary asset classes:** Stocks, ETFs; CSV import from brokers  
**UK specifics:** Mentions IRA, 401k, TFSA contribution limits — clearly US/Canada focused; no documented SIPP or ISA support; no gilt support  
**Why it's not relevant:** Same category as Ghostfolio — portfolio tracking, not optimisation. No UK gilt or SIPP context.

---

## Part 7: Claude / Anthropic Integrations

### 7.1 anthropics/financial-services

**Repository:** https://github.com/anthropics/financial-services  
**Plugin format version:** 0.1.2 (from wealth-management `.claude-plugin/plugin.json`)

**Plugin manifest format (`plugin.json`):**
```json
{
  "name": "wealth-management",
  "version": "0.1.2",
  "description": "...",
  "author": { "name": "Anthropic FSI" }
}
```

**Skill file format (`skills/{skill-name}/SKILL.md`):**
```yaml
---
name: portfolio-rebalance
description: >-
  Analyze portfolio allocation drift and generate rebalancing trade
  recommendations across accounts. Considers tax implications, transaction
  costs, and wash sale rules. Triggers on "rebalance", "portfolio drift",
  "allocation check", "rebalancing trades", or "my portfolio is out of balance".
---

# {Skill Name}

## Workflow
### Step 1: ...
[Markdown workflow steps, tables, decision rules]
```

**Command file format (`commands/{command}.md`):**
```yaml
---
description: Analyze drift and generate rebalancing trades
argument-hint: "[client name or account]"
---

Load the `portfolio-rebalance` skill to analyze allocation drift and recommend
tax-aware rebalancing trades.
```

**Available wealth-management skills:**

| Skill | Trigger phrases | Description |
|-------|----------------|-------------|
| `portfolio-rebalance` | "rebalance", "portfolio drift", "allocation check" | Drift analysis against IPS targets, tax-aware trade list generation |
| `tax-loss-harvesting` | "TLH", "harvest losses", "unrealized losses" | Identifies candidates, suggests replacement securities, tracks wash-sale windows |
| `financial-plan` | (unknown) | Financial planning workflow |
| `investment-proposal` | (unknown) | Investment proposal generation |
| `client-review` | (unknown) | Client meeting preparation |
| `client-report` | (unknown) | Client reporting |

**Portability to UK SIPP context:**

The `portfolio-rebalance` skill's workflow is partially portable. The drift analysis table, trade sizing, and transaction cost logic are directly applicable. **However, the skill is deeply US-market-centric:**
- Asset class categories: "US Large Cap Equity", "US Small/Mid Cap", "International Developed", "Emerging Markets", "Investment Grade Bonds", "High Yield / Credit", "TIPS / Inflation Protected" — no gilts, no MMF, no SIPP/ISA wrapper logic
- Tax rules: wash-sale rules (US), short-term vs long-term capital gains (US), RMDs (US IRA), 401k — none apply in a SIPP
- Replacement security suggestions are US ETFs (SPY → IVV, VXUS → ACWX)

The `tax-loss-harvesting` skill is **not portable**: the wash-sale rule does not apply in a UK SIPP (gains are sheltered). The $3,000 loss deduction is a US concept.

**What IS reusable from the skill format:**
- The SKILL.md + commands/ file structure is exactly the right format to create SIPP-specific skills
- The trigger phrase pattern (natural language → skill activation) works identically for UK workflows
- The markdown workflow step structure (Step 1, Step 2 tables) is the right idiom

**SIPP-specific skills to create in this format:**
- `gilt-ladder-optimise`: Given current gilt holdings, recommend additions/sales to smooth the maturity ladder
- `il-gilt-breakeven`: Given current IL gilt prices, calculate breakeven RPI vs current BoE implied inflation curve
- `sipp-rebalance`: UK-specific version of portfolio-rebalance, aware of SIPP tax treatment (no CGT, no income tax on sheltered gains), Interactive Investor £3.99/trade friction, and strategic baseline targets

**Verdict: adopt the skill format; rewrite the skills for UK SIPP context.** The wealth-management plugin's US-centric skills cannot be used as-is. But the authoring format (SKILL.md + commands/) is exactly right and should be replicated for SIPP-specific Claude skills.

---

### 7.2 OpenBB Claude Code Plugin

OpenBB's `openbb-docs-mcp` (https://github.com/OpenBB-finance/openbb-docs-mcp) provides MCP access to OpenBB's documentation, not financial data. The financial data MCP is `openbb-mcp-server` (covered in 5.1).

There is no dedicated Claude Code plugin for OpenBB in the Claude Code marketplace as of May 2026. The integration point is the MCP server, configured in Claude's `mcp_servers` settings.

**Recommended MCP configuration for v2:**
```json
{
  "mcpServers": {
    "openbb": {
      "command": "openbb-mcp",
      "args": [],
      "env": {
        "OPENBB_PAT": "${OPENBB_PAT}"
      }
    }
  }
}
```

---

## Part 8: Additional Findings

### 8.1 rateslib — UK gilt-specific fixed income library

(Covered in depth as 3.3 above.) This is the strongest finding outside the original scope. Version 2.7.1, actively maintained, explicit `calc_mode="uk_gb"`, ex-dividend support, `IndexFixedRateBond` for IL gilts. CC-BY-NC-ND licence — permissive for private non-commercial use. Recommended as validation layer.

### 8.2 awesome-quant (https://github.com/wilsonfreitas/awesome-quant)

Scanned for UK fixed income and gilt-specific entries. The list is broad but UK gilt-specific Python tooling is sparse:
- **rateslib** is listed under fixed income
- **FinancePy** is listed
- **QuantLib** is listed
- No UK gilt-specific reference implementations or test vector libraries are listed

No additional libraries beyond those already researched were identified.

### 8.3 Bank of England GitHub — no data access tooling

The BoE GitHub organisation (https://github.com/bank-of-england) has 11 repositories, all focused on research applications:
- `Shapley_regressions`, `MachineLearningCrisisPrediction`, `occupationcoder`, `forecast_evaluation`, `InterpretableMLWorkflow`
- R packages: `boeCharts`, `FanChartsInR`
- Regulatory: `PRArulebook`

**No Python data access tooling for BoE statistics has been published by the BoE.** The IADB URL pattern is community-documented, not officially supported. This is not expected to change: the 2019 BoE API engagement paper proposed a more structured API but no production REST API has been delivered as of May 2026.

### 8.4 UK gilt pricing reference test vectors

No published test vector dataset was found for UK gilt clean/dirty price, accrued interest, or GRY calculation. The closest is:
- LSEG/Tradeweb Insite: publishes end-of-day prices (delayed, behind login)
- DMO Annual Review: discusses gilt pricing conventions but contains no numerical test vectors
- The FTSE Actuaries UK Gilts Index Series Guide to Calculation (LSEG, April 2026) is the authoritative convention document for the index but does not include numerical test vectors

**Practical alternative:** Use the Hargreaves Lansdown gilt page (`hl.co.uk`) or Interactive Investor's gilt page as manual cross-check sources. Both display clean price, accrued interest, and yield. The `GiltYieldExtractor` GitHub project (https://github.com/avibe948/GiltYieldExtractor) scrapes HL gilt data and could serve as a test data source.

### 8.5 pandas-datareader — effectively deprecated for UK data

Version 0.10.0, last released July 13, 2021. No significant updates in nearly 5 years. Does not support BoE or ONS as built-in data sources. Primary use case was FRED (US Federal Reserve data). **Do not add as a dependency.**

### 8.6 D10C DMO report — untapped IL gilt uplift data

The DMO's `D10C` XML endpoint returns real-time RPI uplift ratios for individual IL gilts by ISIN and settlement date. Fields: `INSTRUMENT_NAME`, `ISIN_CODE`, `SETTLEMENT_DATE`, `INDEX_RATIO_OR_RPI`, `REFERENCE_RPI`. This is more convenient than computing the uplift from CHAW series data directly, and should be considered for the IL gilt pricing pipeline.

### 8.7 ONS API — CHAW is the authoritative source for RPI index levels

The ONS API returns the full RPI index level series (CHAW, base Jan 1987=100) via a simple unauthenticated GET with no API key required. Monthly data, published ~3 weeks after month end. Rate limit: 120 requests/10 seconds. This is the cleanest free source for the RPI monthly index values needed for IL gilt 3-month lag calculations. URL: `https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23/data`

### 8.8 giltsyield.com — emerging UK gilt tool

`giltsyield.com` is a newer UK retail gilt analysis site with features including yield ladder, post-tax yield calculator, and natural language query. It has no documented public API. Its NLP query feature (powered by an unspecified AI) is interesting as validation but not useful programmatically. Not a dependency candidate.

---

## Part 9: Prioritised Recommendations

### Immediate (now / v1.x)

1. **Add D10C XML fetch for IL gilt real-time RPI uplift ratios.** Low effort, fills a data gap, removes a calculation step. The `INDEX_RATIO_OR_RPI` field provides the current index ratio for each IL gilt by ISIN.

2. **Add ONS API fetch for CHAW RPI monthly index levels.** Replace any current RPI data source with `GET https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23/data`. No API key, clean JSON, authoritative source. The 3-month observation lag lookup becomes `months[-4]['value']` (most recent available minus 3).

3. **Verify IL gilt observation interpolation is flat (not linear).** UK DMO IL gilts use flat RPI interpolation between monthly fixings. This should be confirmed in the hand-rolled engine. Linear interpolation is subtly wrong and will cause small pricing errors that compound at long maturities.

4. **Switch to CVXPY as the LP solver backend.** Low-risk drop-in replacement for `scipy.optimize.linprog(method='highs')`. Same HiGHS solver, same results, materially better infeasibility diagnostics. Estimated effort: 1–2 days. Addresses the joint infeasibility debugging pain documented in `2026-05-20-lp-turnover-tilt-band-joint-infeasibility.md`.

5. **Add rateslib cross-check tests for GRY and modified duration.** Install `rateslib` (CC-BY-NC-ND, free for private use). Write a parametric test that for each gilt in the test suite, compares hand-rolled GRY to `rateslib FixedRateBond(calc_mode="uk_gb").ytm()` within 0.5bp. Run in CI. This provides a strong regression net without replacing the production engine.

### V2 (LLM layer and enhanced analytics)

6. **Add openbb-mcp-server for the Claude market insight layer.** `pip install openbb-mcp-server` (v1.4.0, AGPL, free). Configure as an MCP server in Claude's settings. Use it as the data retrieval backbone for Claude's market analysis tools. Confirm UK equity and macro data coverage empirically before committing to it as the primary data layer.

7. **Author SIPP-specific Claude skills in the `anthropics/financial-services` SKILL.md format.** Create at minimum: `gilt-ladder-optimise` and `sipp-rebalance` skills. The format is simple (YAML front matter + markdown workflow steps in SKILL.md; brief command file in commands/). The US-market wealth-management skills from the anthropics repo are not portable but the format is exactly right.

8. **Parse the BoE real spot curve ZIP for IL gilt breakeven analysis.** The same ZIP-parsing approach already in use for the nominal curve applies. The real spot curve provides the market-implied real yield at each maturity — the gap between this and the app's calculated real GRY for each IL gilt is the breakeven RPI. Useful signal for IL gilt valuation.

9. **Consider skfolio for portfolio optimisation when scenario-CVaR floors are added.** At v2, if the optimiser needs CVaR risk floors (e.g. "portfolio must survive a 200bp shock") or richer non-LP objectives, migrate from CVXPY + custom constraints to skfolio. skfolio's `ObjectiveFunction.MAXIMIZE_RATIO` and turnover/cardinality constraint API are the right end state for a more sophisticated optimiser.

### Skip (not recommended)

| Item | Reason |
|------|--------|
| FinancePy | Stale (last release May 2024), unclear UK gilt convention support |
| investpy / investiny | Both broken against Investing.com |
| EODHD paid tier | Free tier (20 calls/day) unusable; paid tier not justified given free alternatives |
| Alpha Vantage MCP | Free tier (25 calls/day) unusable; no gilt data |
| FMP MCP | No gilt data at all |
| pandas-datareader | Last release 2021; no BoE/ONS support |
| pyscraper | Archived March 2025 |
| Ghostfolio / Wealthfolio | Portfolio trackers, not optimisers; no UK gilt or SIPP context |
| anthropics/financial-services skills (as-is) | US-market-centric; not portable to SIPP without full rewrite |

### Hand-rolled component verdicts

| Component | Verdict | Justification |
|-----------|---------|---------------|
| GRY calculation (Newton/brentq, ICMA, T+1) | **Keep** + rateslib validation | Correct and transparent; add rateslib cross-check in tests |
| IL gilt real GRY (RPI-uplifted, Fisher, 3-month lag) | **Keep** + verify flat interpolation | Likely correct; flat interpolation must be confirmed |
| Modified duration (same cash-flow solve) | **Keep** | Derived correctly from the same price/cash-flow model |
| Yield curve fetch (BoE IADB CSV) | **Augment** | Add ONS CHAW for RPI; add BoE real spot curve ZIP for breakeven |
| DMO data ingestion (D1A XML) | **Augment** | Add D10C for IL gilt RPI ratios; D1D XML does not exist |
| TIDM–ISIN bridge (dividenddata.co.uk) | **Keep** | No viable free alternative; maintain CSV fallback |
| Portfolio allocator (scipy.optimize.linprog HiGHS) | **Augment** | Replace linprog with CVXPY (same solver, better diagnostics) |
| Data persistence (SQLite WAL, hand-written migrations) | **Keep** | Appropriate for local single-user tool |
| Dashboard (Streamlit) | **Keep** | No reason to change |
