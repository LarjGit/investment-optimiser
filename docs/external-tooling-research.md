# External Tooling Research
## Investment Optimiser — UK SIPP Portfolio Allocation Tool

*Consolidated: 2026-05-26. Synthesised from three independent AI research passes (Claude, ChatGPT, Gemini) plus codebase inspection and live web research. Where sources disagreed, the codebase and live search are authoritative.*

---

## Research Integrity Note

One of the three research passes (Gemini) contained several fabricated or incorrect claims that have been explicitly corrected in this document:

| Gemini claim | Verdict | Evidence |
|---|---|---|
| `D1D` is fetchable as XML via `XmlDataReport?reportCode=D1D` | **Wrong** | `docs/solutions/2026-05-19-dmo-d1a-only-xml-feed.md` + live DMO test |
| `D2A` endpoint returns EOD gilt prices | **Fabricated** | Not found on DMO website; DMO's own page states EOD prices are provided by Tradeweb/Insite, not DMO |
| BoE IADB series `IUDMNYY`/`IUDMRYY` expose fitted spot curves | **Fabricated** | App code uses `IUDBEDR/IUDSNPY/IUDMNPY/IUDLNPY`; fitted curves only available via ZIP archives |
| BoE Bank Rate series code is `IUMABEDR` | **Misleading** | `IUMABEDR` exists but is a *monthly average*; `IUDBEDR` is the daily series (what the app correctly uses) |
| QuantLib IL gilt interpolation uses `ql.CPI.AsIndex` | **Wrong** | UK DMO convention is flat interpolation; correct is `ql.CPI.Flat` |

---

## Executive Summary

- **The most urgent production gap is IL gilt RPI data.** Older IL gilts (1980s–90s issuances, e.g. GB0008932666) are quoted by LSE in nominal (uplift-applied) prices. The app cannot solve their real GRY without the current RPI index ratio — confirmed in `docs/solutions/2026-05-22-il-gilt-price-types-and-negative-yields.md`. The fix requires either the DMO D10C XML feed (index ratios by ISIN) or the ONS CHAW series (raw RPI monthly values). Both are free and straightforward.

- **The 2030 RPI→CPIH transition is real, confirmed, and architecturally material.** From February 2030, RPI methodology will be aligned with CPIH, reducing RPI by approximately 1% per annum. No compensation for IL gilt holders. All IL gilts maturing after February 2030 are affected. The app currently uses a single `rpi_assumption_pct` for all IL gilts; this must eventually be split into a pre-2030 and post-2030 regime assumption.

- **rateslib 2.7.1 (April 2026) is the strongest validation layer for the GRY engine.** It has explicit `calc_mode="uk_gb"` for UK DMO conventions, ex-dividend support matching the 7-business-day rule, and an `IndexFixedRateBond` class for IL gilts. Licence is CC-BY-NC-ND — permissive for a private non-commercial tool. Prefer over QuantLib for validation because the UK-specific conventions are explicit rather than requiring manual configuration.

- **The LP solver (`scipy.optimize.linprog`) is clean and already extracts marginals — CVXPY is a worthwhile but non-urgent upgrade.** The LP operates at bucket level (not asset level), is well-structured in `lp_solver.py`, and already surfaces binding constraints and dual values. CVXPY would improve constraint readability and infeasibility diagnostics (the joint tilt-band/turnover infeasibility problem documented in `docs/solutions/2026-05-20-lp-turnover-tilt-band-joint-infeasibility.md` is the primary motivator). Migrate when the constraint set next grows, not before.

- **For the V2 LLM layer, the right architecture is a local read-only MCP server over the app's own SQLite state, plus openbb-mcp-server for external market context.** No paid data subscription is required for the core use case. The `anthropics/financial-services` SKILL.md format is directly replicable for SIPP-specific Claude skills, but the US wealth-management skills themselves are not portable.

---

## Part 1: Architectural Flags

### 1.1 Older IL gilts require RPI index ratio to price — currently unresolvable

**Severity: production gap.** Gilts issued in the 1980s–90s (e.g. GB0008932666 4⅛% IL 2030, GB0031790826 2% IL 2035) are quoted by LSE as nominal (index-uplifted) prices. The app detects these via the heuristic `clean_price > undiscounted_real_sum * 1.5` and skips them with a warning. They are excluded from the gilt ranking and cannot be compared against conventional gilts for switch opportunities.

**Fix:** Integrate either D10C (DMO XML, index ratios per ISIN) or ONS CHAW (raw RPI monthly values). D10C is the more direct route: it gives `INDEX_RATIO_OR_RPI` per ISIN per settlement date, which is exactly what `compute_real_gry` needs as a multiplier. See Part 2.1 and Part 2.3.

### 1.2 The 2030 RPI→CPIH transition is not modelled

**Severity: analytical gap, not yet a bug.** From February 2030, UKSA will align RPI with CPIH, reducing RPI by approximately 1 percentage point per annum relative to current methodology. No compensation for IL gilt holders. The government confirmed this in November 2020; it has been legally upheld. IL gilts maturing after February 2030 will have terminal cash flows lower than a constant `rpi_assumption_pct` projection would imply.

**Current state:** The app uses a single user-entered `rpi_assumption_pct` (default 3.0%) for all IL gilts. For gilts maturing before February 2030, this is fine. For gilts maturing after, the nominal-equivalent yield comparison is overstated.

**Recommended approach:** Add a second user input `rpi_assumption_post_2030_pct` (defaulting perhaps 0.5–1.0% below `rpi_assumption_pct`). Apply it in `compute_real_gry` based on maturity date. This is a one-line change to the Fisher equation call but requires UI work and documentation. Flag in the app when a gilt matures post-2030 that a different RPI assumption applies.

### 1.3 BoE fitted yield curve data is untapped

The IADB CSV API returns only three par yield maturities (5y, 10y, 20y — confirmed in `docs/solutions/2026-05-18-boe-iadb-only-three-par-yield-maturities.md`). The BoE's daily Anderson-Sleath fitted spot curves (nominal, real, OIS, implied inflation at all maturities from 0.5y to 25y) are available as Excel ZIP archives. The real spot curve is directly useful for IL gilt breakeven analysis. The app currently derives benchmark yields from individual gilt GRYs (`_derive_benchmark_yields` in `gilt_analytics.py`) rather than from the authoritative fitted curve. This is a data-richness gap, not a correctness bug.

### 1.4 TIDM–ISIN bridge fragility is a known accepted risk

The only free source for gilt TIDM resolution is dividenddata.co.uk HTML scraping. This is documented in `docs/solutions/2026-05-19-lse-tidm-bridge-no-public-api.md`. No alternative exists at zero cost — OpenFIGI returns Bloomberg-style bond descriptors, not LSE TIDMs. The seeded CSV fallback is the correct defence. No action required.

---

## Part 2: UK Public Data Sources

### 2.1 DMO XML API

**Endpoint pattern:**
```
https://www.dmo.gov.uk/data/XmlDataReport?reportCode={CODE}
```

**Working XML report codes:**

| Code | Description | Key fields |
|------|-------------|------------|
| `D1A` | All gilts in issue (conventional + IL) | `ISIN_CODE`, `INSTRUMENT_TYPE`, `INSTRUMENT_NAME`, `REDEMPTION_DATE`, `DIVIDEND_DATES`, `CURRENT_EX_DIV_DATE`, `BASE_RPI_87` |
| `D10C` | IL gilt index ratios by settlement date | `INSTRUMENT_NAME`, `ISIN_CODE`, `SETTLEMENT_DATE`, `INDEX_RATIO_OR_RPI`, `REFERENCE_RPI` |

**Critical confirmed facts:**
- `D1D` **has no XML export**. Requesting `XmlDataReport?reportCode=D1D` returns: *"Report code 'D1D' cannot be exported as an XML file."* This is confirmed in the codebase solutions file and live-tested. D1A already contains both conventional and index-linked gilts.
- `INSTRUMENT_TYPE` has a trailing space on conventional records (`"Conventional "` → strip to `"Conventional"`). IL records: `"Index-linked 3 months"` or `"Index-linked 8 months"`.
- **`D2A` does not exist as a data source.** The DMO's own website states that end-of-day reference prices are administered by FTSE-Tradeweb and available via Tradeweb Insite (free for non-commercial use, next-day, behind login). DMO stopped producing its own daily reference prices in July 2017. Any reference to `XmlDataReport?reportCode=D2A` is incorrect.
- `BASE_RPI_87` in D1A is the prospectus base RPI for each IL gilt (base January 1987=100). This is the denominator for the index ratio calculation.

**D10C — the missing piece for IL gilt RPI pricing:**

The `D10C` endpoint returns the current index ratio for each IL gilt by ISIN and settlement date:
```
GET https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D10C
```
Response fields: `INSTRUMENT_NAME`, `ISIN_CODE`, `SETTLEMENT_DATE`, `INDEX_RATIO_OR_RPI`, `REFERENCE_RPI`.

This is exactly what `gilt_analytics_handler` needs to price older IL gilts that LSE quotes in nominal terms. The `INDEX_RATIO_OR_RPI` value directly converts the nominal quoted price back to the real price: `real_price = nominal_price / index_ratio`.

**Update cadence:** D1A updates on business days. D10C updates daily.

**Verdict: augment D1A with D10C.** D10C is the highest-priority DMO addition — it unblocks the IL gilt pricing production gap (Arch Flag 1.1). Add a `dmo_d10c_handler` that fetches index ratios and stores them in a new `gilt_index_ratios` table. The `gilt_analytics_handler` should use these ratios before falling back to the skip-with-warning path.

---

### 2.2 Bank of England Statistics Database

**Two access methods — not interchangeable:**

**Method 1: IADB CSV API** (individual named series, daily-updating)
```
https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes
  &SeriesCodes=IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY
  &UsingCodes=Y&CSVF=TN&Datefrom=01/Jan/2024&Dateto=now&VPD=Y
```

**Confirmed IADB series codes (live-verified against BoE website):**

| Series | Description |
|--------|-------------|
| `IUDBEDR` | Bank Rate — daily. This is the correct code; `IUMABEDR` is a monthly average variant |
| `IUDSNPY` | 5-year nominal par gilt yield — daily |
| `IUDMNPY` | 10-year nominal par gilt yield — daily |
| `IUDLNPY` | 20-year nominal par gilt yield — daily |

1-year, 2-year, and 30-year par yield series **do not exist** in the IADB (confirmed in `docs/solutions/2026-05-18-boe-iadb-only-three-par-yield-maturities.md`). The app derives these benchmark points from individual gilt GRYs.

**Method 2: Excel ZIP archives** (fitted curves, 3–4 week publication lag)

The BoE publishes daily Anderson-Sleath fitted yield curves in ZIP archives:
- Nominal: `glcnominalddata.zip`
- Real (IL gilt-derived): equivalent ZIP
- OIS: equivalent ZIP
- Implied inflation: derived breakeven curve

Implementation details confirmed in `docs/solutions/2026-05-22-boe-spot-curve-zip-structure.md`:
- Each ZIP contains multiple XLSX files; current file is last alphabetically
- Sheet `"4. spot curve"` (post-2005 files)
- Skip rows where position 0 is `None` (openpyxl phantom rows from stale XML dimension metadata)
- Publication lag: 3–4 weeks vs IADB which is daily

**Third-party wrappers:** `pyscraper` (archived March 2025) and `BOE-API/BOE_API` (thin, unmaintained) are not recommended as dependencies. The Bank of England itself has published no Python data access tooling (confirmed by searching the BoE GitHub: 11 repos, all research/ML/visualisation tools).

**Verdict: keep IADB fetch as-is; add real/OIS spot curve parsing from ZIP for v2.** The real spot curve would enable IL gilt breakeven analysis (market-implied real yield vs calculated real GRY). Enhancement, not correction.

---

### 2.3 ONS API

**Base URL:** `https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{SERIES_CODE}/mm23/data`  
**Authentication:** None required  
**Rate limits:** 120 requests/10 seconds  

**Response JSON schema (months array):**
```json
{
  "months": [
    {
      "date": "2026 Apr",
      "value": "410.3",
      "label": "April 2026",
      "year": "2026",
      "month": "April",
      "sourceDataset": "MM23",
      "updateDate": "2026-05-20T00:00:00"
    }
  ]
}
```

**Key series codes:**

| Series | Description |
|--------|-------------|
| `CHAW` | **RPI All Items Index (Jan 1987=100)** — this is the authoritative RPI level for IL gilt uplift calculations |
| `CZBH` | RPI: % change over 12 months |
| `D7BT` | CPI All Items Index (2015=100) |
| `L55O` | CPIH All Items Index |

**Why CHAW is urgent:** The app currently takes `rpi_assumption_pct` as a user-entered number. For the IL gilt index ratio calculation (converting nominal-quoted prices to real prices), the app needs the actual published monthly RPI values, not a forward assumption. The 3-month observation lag lookup becomes `months[-4]['value']` from a CHAW fetch (most recently published month minus 3). This is a clean, free, unauthenticated fetch with generous rate limits.

**Complement to BoE:** ONS is the authoritative source for published RPI index levels. The BoE's fitted real spot curve is derived from market gilt prices, not from ONS series — they answer different questions and are not substitutes.

**Verdict: add immediately.** Integrate ONS CHAW as a refresh source (`ons_rpi` in `REFRESH_SOURCE_ORDER`). Store the monthly RPI series in a `rpi_monthly_index` table. This unblocks D10C-independent computation of index ratios for any settlement date and provides the actual current RPI for the post-2030 regime split.

---

### 2.4 LSE Price Explorer API

The LSE does not publish a documented public API. The price-explorer URL pattern is a community-discovered endpoint against LSE's web UI infrastructure. The app uses it for gilt prices (via `lse_gilt_prices.py`) and TIDM bridge refreshes.

**Coverage for non-gilt instruments:** The LSE price-explorer UI covers equities, ETFs, investment trusts, and other LSE-listed instruments, but scraping individual instrument pages carries HTTP 403 risk and no schema guarantee. For equities, yfinance with `.L` suffix is more reliable for price history.

**Verdict: keep as-is.** The current approach (LSE gilt price fetch + seeded CSV TIDM bridge + dividenddata.co.uk monthly refresh) is the best available free option. The endpoint has been stable enough for production use. Maintain the fallback CSV.

---

### 2.5 dividenddata.co.uk

**Conventional gilts:** `https://www.dividenddata.co.uk/uk-gilts-prices-yields.py`  
**IL gilts:** `https://www.dividenddata.co.uk/index-linked-gilts-prices-yields.py`

Fields: EPIC (TIDM), name, coupon, maturity date, clean price, GRY, accrued interest.

**Reliability:** Third-party aggregator with no API contract. Stable enough to serve as the TIDM bridge source. Main risks: structural HTML changes, bot protection, stale data. No Cloudflare observed as of research date.

**For price cross-checking:** The displayed GRY values are useful sanity-checks but methodology is undocumented. Not authoritative (DMO/LSE/Tradeweb prices are ground truth).

**Verdict: keep as-is for TIDM bridge; treat as non-authoritative for price cross-checking.** Do not make price calculations directly dependent on this source.

---

## Part 3: Bond Analytics Libraries

### 3.1 rateslib

**Version:** 2.7.1 (April 4, 2026). v2.7.0 released March 30, 2026.  
**PyPI:** `pip install rateslib` / `uv add rateslib`  
**Licence:** Creative Commons BY-NC-ND 4.0 — source-available, **non-commercial only**. For a private investor's local tool this is fully permissive. For any future commercial distribution, reassess.  
**Windows:** Pre-built wheels for x86-64, ARM64, i686. No MSVC or C++ compile required.  
**GitHub:** `attack68/rateslib` — actively maintained.

**UK conventional gilt support:**
- `FixedRateBond(spec="uk_gb")` — explicit UK DMO calculation mode
- Ex-dividend: `bond.ex_div(settlement_date)` returns `True/False` using UK DMO convention (7 business days before coupon). This is built-in, not a workaround.
- `ActActICMA` day count convention
- UK calendar with England & Wales bank holidays

**IL gilt support:**
- `IndexFixedRateBond` class for inflation-linked bonds
- The `"uk_gb"` calc_mode strongly implies DMO-compliant 3-month flat-lag implementation — requires verification against DMO published vectors before relying on for IL validation

**Why rateslib over QuantLib for this use case:**
1. The `spec="uk_gb"` parameter is explicit — UK conventions are not manually configured, they're declared
2. Ex-div support is built-in and named — no workaround needed
3. Pure Python (no SWIG/C++ opacity) — if a result is wrong, the source is readable
4. Actively maintained as of April 2026

**Verdict: adopt as primary validation layer.** Add `rateslib` as an optional/dev dependency. Write parametric tests comparing hand-rolled `compute_gry` against `rateslib.FixedRateBond(spec="uk_gb").ytm()` for each gilt in a test fixture. Tolerance: 0.5bp. Equivalent test for modified duration. Run in CI.

---

### 3.2 QuantLib / QuantLib-Python

**Version:** 1.42.1 (April 17, 2026)  
**PyPI:** `pip install QuantLib`  
**Windows:** Pre-built wheels for Python 3.8–3.14, x86-64. No MSVC or SWIG install required. `uv add QuantLib` works cleanly.  
**Licence:** BSD-3-Clause (commercial use permitted).

**UK conventional gilt support:**
- Day count: `ql.ActualActual(ql.ActualActual.ICMA)` — correct for UK gilts
- Settlement: `settlementDays=1` for T+1
- Calendar: `ql.UnitedKingdom()` provides England & Wales bank holidays
- Ex-dividend: QuantLib's `FixedRateBond` does **not** natively support the UK 7-business-day ex-dividend window. Requires a custom cash-flow workaround. This is rateslib's key advantage.

**IL gilt support (`CPIBond` + `UKRPI`):**
```python
import QuantLib as ql

index = ql.UKRPI(False)          # False = not interpolated
obs_lag = ql.Period(3, ql.Months)
interpolation = ql.CPI.Flat      # UK DMO convention — NOT CPI.Linear, NOT CPI.AsIndex

bond = ql.CPIBond(
    1,                           # settlementDays (T+1)
    face_amount,
    False,                       # growthOnly (deprecated, use False)
    base_cpi,                    # from D1A BASE_RPI_87 field
    obs_lag,
    index,
    interpolation,
    schedule,
    [fixed_rate],
    ql.ActualActual(ql.ActualActual.ICMA),
)
```

**Key conventions:** `ql.CPI.Flat` is the correct interpolation for UK DMO IL gilts. `CPI.Linear` is subtly wrong; `CPI.AsIndex` is incorrect. The `growthOnly` parameter is deprecated in the underlying C++ library — use `False`.

**Deprecation note (v1.38/v1.39):** The `PiecewiseZeroInflationCurve` constructor changed. Any QuantLib inflation curve code predating v1.38 will fail; use current constructor signatures from the v1.40+ docs.

**Verdict: use as secondary cross-check alongside rateslib.** The BSD licence is more permissive than rateslib's CC-BY-NC-ND for any future commercial use. The ex-div gap makes it less clean as a primary validator for the app's main GRY engine, but useful as an independent institutional-grade sanity check.

---

### 3.3 FinancePy

**Latest PyPI release:** 0.360 (May 1, 2024). Over a year without a release as of May 2026.  
**Maintenance status:** Inactive by release cadence; development continues on GitHub but sporadically.

**UK gilt convention support:** IL gilt support with 3-month RPI lag is not confirmed in published documentation. No evidence of `calc_mode`-style explicit UK DMO support.

**Verdict: skip.** Stale release cadence plus unclear UK convention support makes FinancePy a poor choice relative to either rateslib (for validation) or the hand-rolled engine (for production). Do not add as a dependency.

---

## Part 4: Portfolio Optimisation Libraries

### 4.1 CVXPY directly

**Current version:** ~1.6.x. Pre-built wheels on Windows (no MSVC required). `pip install cvxpy` / `uv add cvxpy`.  
**Default solver:** Clarabel (fast LP/QP/SOCP).  
**HiGHS support:** `prob.solve(solver=cp.HIGHS)` — same LP solver as `scipy.optimize.linprog(method='highs')`, so results are numerically identical for LP problems.

**The case for migration — grounded in actual code:**

`lp_solver.py` constructs constraint matrices as `A_ub_rows` / `b_ub_rows` numpy arrays with string labels, then passes them to `linprog`. The code is already well-structured and already extracts marginals via `res.ineqlin.marginals`. The LP operates at **bucket level** (8–10 buckets), not asset level, so the problem is small.

The primary benefit of CVXPY is **constraint readability and infeasibility diagnostics**, not solver power. Compare:
```python
# Current (linprog): add turnover constraint for bucket i
row_pos = np.zeros(2 * n)
row_pos[i] = 1.0; row_pos[n + i] = -1.0
A_ub_rows.append(row_pos)
b_ub_rows.append(float(cur[i]))
```
```python
# CVXPY equivalent:
constraints.append(w[i] - d[i] <= cur[i])   # turnover_upper
```

CVXPY gives named infeasibility certificates. The joint tilt-band/turnover infeasibility documented in `docs/solutions/2026-05-20-lp-turnover-tilt-band-joint-infeasibility.md` was diagnosed manually; CVXPY would surface which constraint pair conflicts via dual variables.

**Migration cost:** Low (1–2 days). The HiGHS solver is available. Objective, constraints, and variable bounds map directly. The `LPSolveResult` dataclass interface does not change.

**Verdict: recommended for v1.x when constraint set next grows.** The current linprog code is functional and already has marginals. Don't migrate for its own sake, but the next time a new constraint type is added (e.g. a per-asset concentration cap or soft tilt penalty), migrate to CVXPY simultaneously. It's the right stepping stone for any v2 non-LP objective.

---

### 4.2 skfolio

**Version:** 0.20.1 (April 21, 2026). Rapidly maintained.  
**Dependencies:** numpy, scipy, pandas, scikit-learn ≥1.6.0, cvxpy-base ≥1.5.0, clarabel  
**Academic paper:** arXiv 2507.04176 (July 2025)

**Fit for this app:**

The app's LP operates on *buckets*, not individual assets. It uses a linear attractiveness score (baseline deviation), not statistical expected returns. skfolio is designed around historical return matrices `X` and covariance-aware risk objectives — a different paradigm.

skfolio's strengths (walk-forward validation, CVaR risk measures, HRP/NCO allocation methods) are genuinely useful for the *equity sleeve* of the SIPP (where statistical return modelling makes sense) but do not improve the gilt-ladder or LP optimiser.

Custom expected return injection via `mu` parameter is supported, which would allow GRY values for gilts to be used instead of statistical means. This is the integration path if skfolio is ever adopted for the full portfolio.

**Verdict: watch for v2.** Use skfolio to compare current LP recommendations against mean-risk/HRP baselines in a research tab. Do not migrate the production LP. Becomes relevant when scenario-CVaR floors are added.

---

### 4.3 PyPortfolioOpt

**Version:** 1.6.0 (February 2026). MIT licence.

Black-Litterman with gilt GRY values as priors is genuinely useful for expressing analytical views alongside statistical equity returns. However, the covariance matrix degeneracy from short-dated gilts (near-zero historical variance) is a practical problem. skfolio handles mixed return sources more cleanly.

**Verdict: second choice behind skfolio for v2 research work.** Not for production LP.

---

### 4.4 Riskfolio-Lib

**Version:** 7.2.1 (February 2026). BSD-3-Clause.  
24 convex risk measures (CVaR, CDaR, EVaR, etc.). CVXPY-based.

Best fit for CVaR-heavy institutional portfolios. For this SIPP tool, skfolio's scikit-learn API is a better fit. If scenario-CVaR floors become the primary requirement, consider Riskfolio-Lib over skfolio.

**Verdict: viable but skfolio preferred; both are v2 concerns.**

---

## Part 5: Financial Data APIs and MCP Servers

### 5.1 OpenBB Platform + openbb-mcp-server

**openbb-mcp-server version:** 1.4.0 (April 10, 2026)  
**Licence:** AGPL-3.0 (open source, free for all uses)  
**Install:** `pip install openbb-mcp-server` then `openbb-mcp` to launch (default: `http://127.0.0.1:8001`)  
**Python:** 3.10+

**What the MCP server exposes:**
- Tool categories: equity, economy, fixed income/bonds, ETFs, currencies, commodities, news, derivatives
- Admin tools: `available_categories`, `available_tools`, `activate_tools`, `deactivate_tools` — dynamic discovery, Claude only loads the tools it needs
- "Skill guides" (MCP resources): markdown documents teaching multi-step workflows

**UK data coverage:** Not explicitly documented. Depends on which OpenBB provider extensions are installed. yfinance-backed routes (no API key needed) cover UK equities via `.L` suffix. Gilt-specific data is not confirmed from free providers.

**Recommended MCP configuration for v2:**
```json
{
  "mcpServers": {
    "openbb": {
      "command": "openbb-mcp",
      "args": [],
      "env": { "OPENBB_PAT": "${OPENBB_PAT}" }
    }
  }
}
```

**V2 architecture pattern (synthesised from all three research passes):** For the Claude market insight layer, the right structure is two MCP servers:
1. **App-owned local MCP** — read-only tools over the app's own SQLite state (`get_portfolio_state`, `get_solver_recommendation`, `get_scenario_results`, `get_signal_cards`, `get_data_staleness_report`). Claude should never write to the optimiser database.
2. **openbb-mcp-server** — for live market context, news, and macro data.

Claude explains and narrates trusted persisted data; it does not silently create calculation inputs.

**Verdict: adopt for v2.** Confirm UK equity and macro data coverage empirically before making it a primary data layer.

---

### 5.2 EODHD + MCP Server

77-tool MCP server. GBOND exchange covers benchmark yields (e.g. `UK10Y.GBOND`) — primarily yield indices, not individual named gilts. Individual gilt ISIN lookup is possible but coverage depth is unclear.

**Free tier:** 20 API calls/day — unusable for any real-time use.  
**Paid tier:** ~£20/month.

**Verdict: skip.** Free tier is too thin. Paid tier not justified given free alternatives. The MCP server is impressive but gilt-specific coverage is not clearly better than OpenBB.

---

### 5.3 Alpha Vantage + MCP

Official MCP server at `mcp.alphavantage.co`. UK equities via `.L` suffix.  
**Free tier:** 25 requests/day, 5 requests/minute — marginally above useless.  
**No gilt data.**

**Verdict: skip for this use case.**

---

### 5.4 Financial Modeling Prep + MCP

MCP server available. UK equity coverage. **Bond data explicitly not offered.**  
**Free tier:** 250 calls/day, EOD data only.

**Verdict: skip.** No gilt data. UK equity data available from yfinance at higher limits.

---

### 5.5 yfinance (current usage and gaps)

**Version:** 1.4.0 (May 23, 2026). Actively maintained. Apache 2.0.

**Confirmed current usage in the app:**
- `.L` suffix for LSE equities
- `yf.Ticker('SWRD.L').info['trailingPE']` for benchmark PE — known unreliable for ETFs
- `yf.download(tickers, multi_level_index=False)` — confirmed stable batch pattern

**Known limitations (2026):**
- `trailingPE` absent or `None` for most LSE ETFs — treat as first-class unavailable, not error. Confirmed in `docs/solutions/2026-05-19-yfinance-trailing-pe-lse-etf-reliability.md`
- Investment trusts have `quoteType == "EQUITY"` — confirmed in `docs/solutions/2026-05-22-yfinance-investment-trust-quoteType-is-equity.md`
- Rate limiting (429 errors) is a real operational risk; yfinance 1.x has exponential backoff but underlying Yahoo rate limits are undocumented
- UK MMFs (Royal London Short Term Fixed Income, Aberdeen Cash Funds) are not resolvable via yfinance — price MMFs manually or via seed tables

**Verdict: keep as-is.** No free alternative is materially better. The known gaps are documented and handled.

---

### 5.6 LSEG Data Library for Python

Requires LSEG Workspace subscription (~£20,000+/year equivalent). Out of scope. Documented for completeness as the "paid institutional ideal."

---

### 5.7 investpy / investiny

`investpy`: permanently broken (Cloudflare since 2022–2023). Archived.  
`investiny`: last PyPI release October 2022. Effectively abandoned; open issues include 403 errors against same Cloudflare block.

**Verdict: skip both.**

---

## Part 6: Open Source Trackers (context only)

### 6.1 Ghostfolio

Self-hosted, AGPL. Portfolio tracker for stocks/ETFs/crypto. No IL gilt cash-flow analytics, no SIPP tax wrapper logic, no optimiser. Useful for UX reference only.

### 6.2 Wealthfolio

Local-first desktop app (Tauri/Rust). US/Canada-focused (IRA, 401k, TFSA). No UK gilt or SIPP support. Useful for UX/data-model ideas only.

---

## Part 7: Claude / Anthropic Integrations

### 7.1 anthropics/financial-services — skill format

**Plugin manifest (`plugin.json`):**
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
  Triggers on "rebalance", "portfolio drift", "allocation check".
---

# Skill Name
## Workflow
### Step 1: ...
```

**Command file format (`commands/{command}.md`):**
```yaml
---
description: Analyze drift and generate rebalancing trades
argument-hint: "[account or context]"
---

Load the `portfolio-rebalance` skill...
```

**Portability of existing wealth-management skills:**

| Skill | Portable? | Reason |
|-------|-----------|--------|
| `portfolio-rebalance` | **Partially** | Drift analysis and trade sizing logic is portable; asset categories and tax rules are US-centric |
| `tax-loss-harvesting` | **No** | Wash-sale rule does not apply in a UK SIPP; $3k loss deduction is a US concept |
| `financial-plan`, `investment-proposal`, `client-review`, `client-report` | **Format only** | Workflow discipline is reusable; all content must be rewritten for UK SIPP context |

**SIPP-specific skills to create (recommended directory structure):**
```
plugins/sipp-investment-optimiser/
  plugin.json
  skills/
    gilt-ladder-optimise/SKILL.md
    il-gilt-breakeven/SKILL.md
    sipp-rebalance/SKILL.md
    scenario-explainer/SKILL.md
    gilt-switch-analysis/SKILL.md
    decision-audit-review/SKILL.md
  commands/
    rebalance.md
    switch.md
    explain.md
```

Each skill should: cite persisted source data; separate deterministic calculations from market commentary; flag stale or missing prices; never recommend a trade without showing the friction gate output.

**Verdict: adopt the format; rewrite all content for UK SIPP context.** The US skills are not portable but the authoring format is exactly right.

---

### 7.2 OpenBB Claude Code Integration

There is no dedicated Claude Code plugin for OpenBB in the Claude Code marketplace as of May 2026. The integration point is the MCP server (see Part 5.1). `openbb-docs-mcp` provides documentation access only, not financial data.

---

## Part 8: Additional Findings

### 8.1 2030 RPI→CPIH — confirmed, material, not yet modelled

Confirmed by multiple authoritative sources (UKSA, LCP, Lexology). Key facts:
- From **February 2030**, ONS will align RPI methodology with CPIH
- In practice: CPIH monthly growth rates applied to RPI index from February 2030; full annual rate alignment from February 2031
- RPI will be approximately **1 percentage point per annum lower** than under current methodology
- **No compensation** for IL gilt holders confirmed by UK Government (November 2020)
- **February 2030** chosen specifically as the last IL gilt with early-redemption clauses matures before then
- Markets have partially priced this into long-dated IL gilt prices already

**App impact:** Any IL gilt maturing after February 2030 (currently: 2030, 2031, 2034, 2035, 2037, 2040, 2044, 2047, 2051, 2055, 2058, 2062, 2073) has a lower real cash-flow expectation than a constant `rpi_assumption_pct` projection implies. The switch-opportunity signal card and the GRY ranking for IL gilts will overstate the attractiveness of long-dated IL gilts relative to conventional gilts unless the post-2030 RPI step-down is modelled.

**Immediate action:** Add a UI note to the IL gilt section flagging this for gilts with maturity > 2030. Add `rpi_assumption_post_2030_pct` as a second policy parameter with a lower default (e.g. `rpi_assumption_pct - 1.0`).

### 8.2 DMO yield formulae document — the authoritative test oracle

The DMO publishes "Formulae for Calculating Gilt Prices from Yields" (4th edition, 18 December 2024):
`https://www.dmo.gov.uk/media/334d05fo/yldeqns_v4.pdf`

This is the canonical reference for conventional gilts, 8-month IL gilts, 3-month IL gilts, strips, and accrued interest. Any discrepancy between the hand-rolled engine, rateslib, and QuantLib should be resolved by reference to this document. It should be the source of test fixtures for `tests/analytics/`.

### 8.3 awesome-quant scan — nothing new for UK fixed income

Scanned `wilsonfreitas/awesome-quant` for UK gilt-specific entries. rateslib and FinancePy are listed under fixed income; QuantLib is listed. No UK gilt-specific reference implementations, test vectors, or index ratio tools were found beyond those already researched.

### 8.4 GiltYieldExtractor — manual cross-check source

`https://github.com/avibe948/GiltYieldExtractor` scrapes Hargreaves Lansdown gilt pages (clean price, accrued interest, yield). Not a dependency candidate but useful for generating manual test vectors to validate the hand-rolled engine. HL and Interactive Investor gilt pages display prices and yields that can serve as spot cross-checks.

### 8.5 pandas-datareader — deprecated for this use case

Last PyPI release: July 2021. No BoE or ONS support. Do not add.

### 8.6 Data provenance pattern (from ChatGPT research pass)

For the v2 data layer, a `DataProvenance` annotation on all fetched data is recommended. This is the right abstraction for the planned MCP server and for debugging stale data issues:

```python
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

@dataclass
class DataProvenance:
    provider: str
    source_url: str
    fetched_at: datetime
    as_of_date: date | None
    confidence: Literal["authoritative", "official", "unofficial", "fallback"]
```

Source hierarchy for this app:
- `authoritative`: DMO XML, ONS API
- `official`: BoE IADB, BoE ZIP archives
- `unofficial`: LSE price-explorer, dividenddata.co.uk
- `fallback`: seeded CSV, hardcoded defaults

---

## Part 9: Prioritised Recommendations

### Tier 1 — Immediate (unblock production gaps)

**1. Integrate DMO D10C for IL gilt index ratios.**  
Fetch `https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D10C`. Store `(isin, settlement_date, index_ratio)` in a new `gilt_index_ratios` table. In `gilt_analytics_handler`, use the index ratio to convert nominal-quoted IL gilt prices to real prices before calling `compute_real_gry`. This unblocks the older IL gilts (GB0008932666, GB0031790826, etc.) that are currently skipped with a warning.

**2. Integrate ONS CHAW for published RPI monthly index levels.**  
`GET https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/chaw/mm23/data` — no API key, generous rate limits. Add an `ons_rpi` handler to `REFRESH_SOURCE_ORDER`. Store monthly values in an `rpi_monthly_index` table. Use `months[-4]['value']` for the 3-month observation lag. This provides the actual current RPI for D10C-independent index ratio computation.

**3. Add rateslib cross-check tests.**  
`uv add --optional rateslib`. Write `tests/analytics/test_rateslib_crosscheck.py` with parametric tests comparing `compute_gry` against `rateslib.FixedRateBond(spec="uk_gb").ytm()` within 0.5bp. Equivalent test for modified duration. Run in CI. This provides a regression safety net for the hand-rolled engine without replacing it.

**4. Add 2030 RPI regime split.**  
In the app sidebar: add `rpi_assumption_post_2030_pct` with default = `rpi_assumption_pct - 1.0`. Pass both values through `gilt_analytics_handler`. In `compute_real_gry`, select `rpi_assumption_pct` for gilts with `maturity_date < 2030-02-01`, `rpi_assumption_post_2030_pct` for later maturities. Add a UI annotation on the IL gilt ranking table flagging post-2030 gilts.

### Tier 2 — Near-term improvements (data quality and diagnostics)

**5. Migrate LP solver to CVXPY.**  
Low-risk drop-in: replace `scipy.optimize.linprog` with `cp.Problem` using `solver=cp.HIGHS`. Identical results for the current LP. Better constraint readability and infeasibility diagnostics. Do this the next time a new constraint type is added to `lp_solver.py` rather than as a standalone migration.

**6. Add DMO yield formulae test fixtures.**  
Source test vectors from the DMO 4th edition formulae PDF (December 2024). Add `tests/analytics/test_dmo_reference_vectors.py`. If rateslib and the hand-rolled engine disagree with a DMO reference case, DMO wins.

**7. Parse BoE real spot curve ZIP for breakeven analysis.**  
Extend the existing ZIP-parsing approach (confirmed in `docs/solutions/2026-05-22-boe-spot-curve-zip-structure.md`) to fetch the real gilt spot curve alongside the nominal. The gap between market-implied real yield (BoE curve) and calculated real GRY (app engine) is the breakeven RPI — directly useful for IL gilt switch signals.

### Tier 3 — V2 (LLM layer and enhanced analytics)

**8. Build local read-only MCP server over SQLite state.**  
Tools: `get_portfolio_state`, `get_solver_recommendation`, `get_scenario_results`, `get_signal_cards`, `get_trade_friction_breakdown`, `get_data_staleness_report`. Claude reads; Claude never writes to the optimiser database. Use the `anthropics/financial-services` SKILL.md format for the skill definitions.

**9. Add openbb-mcp-server for live market context.**  
`pip install openbb-mcp-server` (v1.4.0, AGPL, free). Configure as a second MCP server. Empirically confirm UK equity and macro data coverage before committing to it as a primary context layer.

**10. Author SIPP-specific Claude skills.**  
Priority order: `gilt-switch-analysis`, `sipp-rebalance`, `il-gilt-breakeven`, `scenario-explainer`. Use the SKILL.md + commands/ format from `anthropics/financial-services`. The US wealth-management skills are not portable but the format is exactly right.

**11. Consider skfolio for the portfolio optimiser when scenario-CVaR floors are added.**  
At v2, if the optimiser needs CVaR risk floors or walk-forward validation, migrate from CVXPY + custom constraints to skfolio. skfolio's mixed analytical/statistical return injection (GRY for gilts, statistical mean for equities) is the right end-state for a more sophisticated optimiser.

### Skip

| Item | Reason |
|------|--------|
| FinancePy | Stale (last release May 2024), unclear UK gilt convention support |
| investpy / investiny | Both broken against Investing.com |
| EODHD paid tier | Free tier (20/day) unusable; paid tier not justified |
| Alpha Vantage MCP | Free tier (25/day) unusable; no gilt data |
| FMP MCP | No gilt data at all |
| pandas-datareader | Last release 2021; no BoE/ONS support |
| pyscraper | Archived March 2025 |
| Ghostfolio / Wealthfolio | Portfolio trackers; no UK gilt or SIPP context |
| DMO D2A endpoint | Does not exist; Gemini fabrication |
| BoE IADB fitted curve series | `IUDMNYY`/`IUDMRYY` do not exist; fitted curves only via ZIP archives |
| anthropics/financial-services skills (as-is) | US-market-centric; not portable to SIPP without full rewrite |

### Hand-rolled component verdicts

| Component | Verdict | Justification |
|-----------|---------|---------------|
| GRY calculation (Newton/brentq, ICMA, T+1, ex-div) | **Keep** + rateslib validation | Correct and transparent; add rateslib cross-check in CI |
| IL gilt real GRY (real-price solve + Fisher) | **Keep** + D10C/CHAW data | Engine is correct for real-priced gilts; add index ratio data to unblock nominal-priced older gilts |
| Modified duration (same cash-flow solve) | **Keep** | Derived correctly from the same price/cash-flow model |
| IL gilt RPI assumption | **Augment** | Add 2030 split: `rpi_assumption_pct` pre-2030, `rpi_assumption_post_2030_pct` post-2030 |
| Yield curve fetch (BoE IADB CSV) | **Augment** | Keep IADB for daily base rate + par yields; add ONS CHAW for RPI; add BoE real spot ZIP for breakeven (v2) |
| DMO data ingestion (D1A XML) | **Augment** | Add D10C for IL gilt index ratios — production priority |
| TIDM–ISIN bridge (dividenddata.co.uk) | **Keep** | No viable free alternative; maintain CSV fallback |
| Portfolio allocator (scipy linprog HiGHS) | **Augment** | Migrate to CVXPY on next constraint addition — same solver, better diagnostics |
| Data persistence (SQLite WAL, hand-written migrations) | **Keep** | Appropriate for local single-user tool |
| Dashboard (Streamlit) | **Keep** | No reason to change |
| RPI data source | **Replace** | Currently user-entered assumption only; replace with ONS CHAW auto-fetch for published RPI values |
