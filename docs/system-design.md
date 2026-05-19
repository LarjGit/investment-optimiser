# Investment Optimiser Design

## Summary

The investment-optimiser is a local decision-support tool for a UK SIPP portfolio of roughly GBP100k or more. It recommends how capital should be allocated across any SIPP-eligible asset class, including cash, MMFs, conventional gilts, index-linked gilts, ETFs, investment trusts, REITs, equities, funds, and other supported instruments. The engine is whole-portfolio, hierarchical, and anchored to a user-authored strategic baseline rather than current holdings. Current holdings are implementation state, not policy truth, so the system may recommend substantial reshaping when the evidence supports it.

The application runs locally on Windows with Python, Streamlit, and SQLite. It ingests a manually updated Interactive Investor CSV, refreshes free public market data from the Bank of England, the DMO, the London Stock Exchange price-explorer API, Yahoo Finance, and the BlackRock UK ISF page, then persists portfolio, market, signal, and allocation state in SQLite. The dashboard is an on-demand read layer over persisted data, with scenario controls, friction assumptions, signal diagnostics, explanation tooling, change-attribution reporting, and an append-only decision log.

The tool is recommendation-only. It does not automate trading. Signals surface opportunities and risk states; the friction model and final risk gate decide whether a trade is executable on realistic and policy-acceptable terms; the allocation engine produces an executable recommended portfolio rather than a frictionless paper target.

Explainability is a first-class product requirement. The system must be able to say what changed, why it changed, what blocked a suggested trade, and which assumptions or constraints drove the final recommendation.

## Key Constraints

- Decision-support only. The user executes trades manually.
- Scope is open across SIPP-eligible asset classes; the tool must not be artificially narrowed to gilts only.
- The allocator is whole-portfolio and baseline-anchored, with strong sleeves modelled directly and weak sleeves bounded rather than fake-optimised.
- The investment objective is flexibility and optionality, with possible drawdown within about five years and no desire to lock the entire portfolio into very long duration.
- The tax wrapper is a SIPP, so recommendations optimise gross yield and portfolio behaviour rather than tax-adjusted outcomes.
- The default platform is Interactive Investor with a parameterised friction model that defaults to GBP3.99 per trade.
- Data sources remain free public sources only.
- Scenario modelling is deterministic and named; Monte Carlo is out of scope for v1.
- Alerts are in-app first. Windows Task Scheduler plus toast notifications may be added later.

## Data Ingestion

The ingestion layer normalises an Interactive Investor CSV into a canonical holdings schema and persists the result as the authoritative local portfolio snapshot for the day. It is an adapter-based normalisation path rather than a hard-coded one-off parser, so additional broker formats can be added later without changing downstream storage or analytics contracts.

The canonical holding shape is:

```python
@dataclass
class Holding:
    symbol: str
    name: str
    asset_type: str
    qty: float
    clean_price_gbp: float
    market_value_gbp: float
    book_cost_gbp: float
    import_warning: str | None = None
```

`market_value_gbp` is taken directly from the CSV rather than recomputed, because the broker export is authoritative for current portfolio value.

### Portfolio CSV Normalisation

The CSV is read with `encoding='utf-8-sig'` so the Interactive Investor BOM is stripped automatically. Totals rows are removed after load by filtering rows where `Symbol` is null or `Name` contains `totals` case-insensitively; this is preferred over `skipfooter` because it is more robust to blank trailing lines and broker footer changes.

A module-level `II_COLUMN_MAP` maps broker column names to canonical internal names, and `II_REQUIRED_COLUMNS` defines the hard-required input fields. If required columns are missing, import fails immediately with a specific `IngestionError` listing expected, missing, and observed columns.

Price parsing is deliberately self-contained and does not branch on asset type. A single `parse_price()` function strips leading `GBP` markers for gilt clean prices, strips trailing `p` and divides by 100 for pence-quoted holdings, removes commas, and returns `None` on parse failure. Per-row parse failures do not abort the import. Instead, the row is retained with an `import_warning` so the rest of the portfolio remains usable.

Asset classification follows a strict cascade:

1. `ASSET_TYPE_OVERRIDES` by symbol
2. MMF detection from name
3. DMO-backed gilt resolution via the TIDM to ISIN bridge
4. Maintained non-gilt symbol-to-class map
5. Lightweight metadata or name heuristics
6. Safe fallback to `other` with an explicit warning

The persisted `asset_type` taxonomy is fixed to `gilt_conventional`, `gilt_index_linked`, `mmf`, `equity`, `etf`, `investment_trust`, `reit`, `fund`, and `other`. Friction-only distinctions such as `gilt_etf` and `corporate_bond` are derived later from metadata and overrides rather than added to the stored enum.

### Gilt Reference Data

The DMO XML feeds are the authoritative source for coupon, maturity, dividend calendar, ex-dividend date, and instrument type:

- `https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1A` for conventional gilts
- `https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1D` for index-linked gilts

The DMO feed does not include LSE TIDMs, so the system maintains a separate TIDM to ISIN bridge. A seeded `data/tidm_cache.csv` provides a bootstrap mapping, and the live bridge is refreshed monthly from the LSE bulk price-explorer endpoint. The DMO refresh and bridge refresh run in the same monthly cycle but are logged as separate sources in `refresh_log`, so a bridge failure can stay visible without invalidating the entire DMO reference refresh when the seeded or prior bridge still produces usable mappings.

Coupon parsing is derived from `INSTRUMENT_NAME` and supports ASCII fractions, Unicode fraction variants, decimal formats, and whole numbers. If no trustworthy coupon parse is possible, the instrument is skipped with a warning rather than guessed.

Parsed reference rows are stored in `gilt_reference` with `isin`, `tidm`, `instrument_name`, `coupon_pct`, `maturity_date`, `dividend_months`, `dividend_day`, `ex_div_date`, `instrument_type`, `maturity_bracket`, and `last_updated`. Monthly refresh uses full replacement inside a short transaction.

If no reference data exists on first run and no local XML cache is available, gilt analytics halt with a visible error, while unrelated app sections may continue rendering.

### Market Data Sources

The data-source contract is:

- Individual UK gilts: LSE price-explorer API
- Non-gilt exchange-traded holdings: Yahoo Finance
- FTSE 100 valuation input for the equity macro signal: BlackRock UK ISF HTML page
- MMF running yield proxy: Bank of England base rate
- Yield curve and base rate: Bank of England CSV API
- Gilt metadata and coupon calendar: DMO XML plus LSE bridge

Yahoo Finance is explicitly not used for individual UK gilt pricing.

### Yahoo Finance Refresh

Yahoo Finance covers equities, ETFs, investment trusts, REITs, listed funds, and other non-gilt exchange-traded symbols. The batch pattern is:

```python
df = yf.download(
    equity_tickers,
    period="2d",
    interval="1d",
    multi_level_index=False,
    actions=False,
    progress=False,
)
latest = df["Close"].iloc[-1]
```

`period="2d"` is used to tolerate delayed exchange updates. After the batch, `yfinance.shared._ERRORS` is inspected so symbol-not-found cases, transient server failures, and silent all-null cases can be handled differently. Ticker-level failures do not create extra `refresh_log.status` values. A source run is `completed` if it still yields a usable daily snapshot, even when some symbols fall back to cached prices with warnings.

### Refresh Entry Points and Staleness

Refresh runs at startup when today's data is missing and can also be triggered manually from the dashboard. The coordinator first normalises `data/portfolio_latest.csv` into today's `portfolio_snapshots`, then refreshes remote sources independently, then evaluates and persists signal state. Per-source freshness is derived from the latest successful `refresh_log` row for that source. More than two trading days stale is warning-level; more than five is error-level. Signals remain visible even when data is stale.

The dashboard upload flow stores the imported CSV to `data/portfolio_latest.csv`. The dashboard never treats the uploaded file as live analysis state directly; it always goes through the persistence-layer import step first.

## Allocation Engine

The allocation engine is a whole-portfolio, hierarchical allocator anchored to a user-authored strategic baseline. It is explicitly not a narrow bond optimiser with a separate equity sleeve bolted on. A top layer allocates across active sleeves or asset buckets; lower-level sleeve modules implement their assigned budget with sleeve-specific logic and diagnostics. Weakly modelled sleeves remain bounded and confidence-limited instead of being pushed through a fake expected-return model.

### Portfolio-Level Policy

The top layer works in portfolio weights:

- `w_base`: versioned strategic baseline
- `w_cur`: current live holdings weights
- `w`: target post-trade weights

The frozen v1 policy pack lives in `src/investment_optimiser/policy_pack_v1.json` and is described in `docs/policy-pack-v1.md`. Later slices should treat that artifact as the source of truth for the bucket taxonomy, named scenarios, default constraints, and shared assumption keys.

Hard policy constraints include full investment, long-only positioning in v1, baseline tilt bands, regime-aware turnover limits, and adverse-scenario acceptability floors. Sleeve-local constraints include maturity caps, concentration caps, MMF or cash floors, and liquidity floors for the fixed-income sleeve.

The objective is a deterministic attractiveness score rather than a claim to precise cross-asset expected returns. Confidence acts primarily by tightening tilt bands around baseline and secondarily by scaling sleeve scores. Current holdings matter for turnover, friction, and migration pacing, but they are not treated as the policy anchor.

### Solver Design

The v1 top-layer optimiser uses `scipy.optimize.linprog(method='highs')` with a continuous LP core. Presolve remains enabled, and if an unbounded result appears where infeasibility is plausible, the solver is re-run once with `presolve=False` to disambiguate. SLSQP and MILP are intentionally excluded from the v1 core.

This fits the required problem shape:

- linear attractiveness objective
- linear budget constraints
- linear concentration and tilt bounds
- linear turnover limits
- linear adverse-scenario floors

The design preserves useful diagnostics such as slacks, marginals, and explicit infeasible or unbounded solver states.

### Robustness and Regime Handling

The allocator supports staged convergence rather than one-shot portfolio reshaping. It imposes a hard turnover budget against current holdings, tighter in constructive or normal regimes and wider in more defensive regimes. Cash flows such as contributions, withdrawals, coupons, dividends, maturities, and existing cash or MMF balances are deployed first before discretionary sells.

Scenario robustness is hybrid:

1. a weighted multi-scenario attractiveness objective
2. explicit hard floors for a small set of adverse scenarios

If scenario floors conflict with policy bounds or turnover limits, the solve fails visibly. No hidden constraint relaxation is allowed.

### Fixed-Income Candidate Universe and GRY Calculation

The fixed-income sleeve searches the full live gilt universe, not just current holdings. Conventional gilts are always in scope. Index-linked gilts join ranking and optimisation only when the user supplies an expected RPI assumption that permits real-to-nominal comparison. MMF yield is proxied by the Bank of England base rate.

The shared gilt yield engine uses the LSE price-explorer API as the live price source for both held and candidate gilts, with prices normalised to `per GBP100 nominal`. Interactive Investor CSV prices remain fallback-only for held gilts temporarily missing from the LSE snapshot.

Settlement is `T+1` using England and Wales bank holidays. Coupon schedules are generated backwards from maturity using DMO coupon calendar fields. Ex-dividend handling uses seven business days before coupon date, with a calendar fallback beyond the loaded holiday horizon. Accrued interest follows ICMA actual/actual logic.

`compute_gry(clean_price_per_100, coupon_pct, maturity_date, settlement_date)` returns both annual GRY and modified duration. The primary solve path uses Newton; `brentq` is the fallback. Failed solves are omitted from `gilt_price_cache` and surfaced as warnings rather than persisted as null analytics.

Index-linked gilt real GRY is a separate calculation built in a dedicated slice after the shared GRY engine. The real yield solve uses the same Newton/brentq path but with the redemption cash flow uplifted by the projected index ratio derived from the user-supplied RPI assumption. The nominal-equivalent yield is then computed from the real yield using the Fisher equation. The RPI assumption is a sidebar input that is added to the session state and frozen as a named field in `policy_pack_v1.json` in the same slice. Until that slice is built, IL gilts are priced and held in the portfolio but excluded from yield ranking, switch logic, and the LP candidate universe.

### Sleeve Contract and Fallbacks

Each sleeve must return:

- target sleeve weights and or trades
- local confidence
- scenario pass or fail summary
- binding constraints
- degraded-mode flags
- turnover used
- unallocated cash
- a short explanation payload

The top layer is authoritative. Sleeves cannot silently force upstream relaxation of portfolio-wide scenario floors, pacing limits, or budget rules. If a sleeve cannot satisfy its local envelope, it returns a named degraded fallback such as `feasible-conservative`, `hold-current`, or `cash-remainder`.

### Post-Solve Trade Construction

Trade construction occurs after the LP solve:

1. solve continuous target weights
2. translate to sleeve-level holdings targets
3. build trades against current holdings
4. round gilt trades to the nearest GBP100 nominal
5. leave residual cash in MMF or cash
6. apply the friction gate
7. apply the risk gate to the friction-feasible trade set
8. keep acceptable trades, flag marginal trades, and remove blocked trades with explicit reasons
9. rebuild the executable holdings state conservatively

The executable recommendation is therefore authoritative for the headline recommended portfolio. Downstream scenarios and dashboard outputs use the executable recommended state, not the frictionless raw optimiser target.

### Risk Gate

The risk gate is a named final veto layer between post-solve trade construction and the headline executable recommendation. It exists to separate attractive trades from acceptable trades. The optimiser may identify a direction that improves the objective, and the friction gate may show that it is cheap enough to execute, but the final recommendation still fails if hard portfolio guardrails are breached.

Typical risk-gate checks include post-trade concentration jumps, scenario-loss ceilings, liquidity floors, maturity-policy breaches, and other hard policy rules that should never be silently relaxed. The risk gate can block or downgrade trades, but it cannot force hidden constraint relaxation upstream. Every blocked or downgraded trade must retain a plain-English reason so the user can see why an idea was rejected.

### Scenario Engine

The scenario engine compares two portfolio states:

- current portfolio
- post-friction-and-risk executable recommended portfolio

The main question is: if a named deterministic scenario happens, how does the current portfolio compare with the realistic portfolio that could actually be implemented today after friction and hard risk vetoes?

Repricing rules are asset-specific:

- Conventional gilts: exact repricing by shocking yield and re-solving clean price from the cash-flow engine
- Index-linked gilts: same real-yield path when inflation assumptions are credible; otherwise carried as `unmodelled_held_flat`
- MMF and cash: capital value flat, income changes only
- Holdings without a credible scenario model: retained in totals at unchanged spot value and labelled `unmodelled_held_flat`

Canonical engine output is long-form scenario records with fields including `portfolio_state`, `scenario_name`, `holding_id`, `holding_name`, `asset_type`, `bucket_name`, `current_value_gbp`, `scenario_value_gbp`, `pnl_gbp`, `model_status`, and `notes`. Dashboard tables are derived from this structure at render time.

Every scenario summary must disclose how much of the portfolio is exact-modelled, held flat, or unmodelled-and-held-flat.

### Audit and Replay

Every solve writes a replayable snapshot to `allocation_runs`. The stored payload includes policy version, baseline allocation, current holdings, sleeve confidence values, cash-flow inputs, active constraints, score coefficients, scenario floors and results, solver status, binding constraints or marginals where available, fallback paths, and sleeve explanation payloads. Auditability is a first-class requirement.

### Explanation and Research Layer

An optional explanation layer sits on top of persisted system state and produces readable memos, short recommendation summaries, decision-support notes, and question-answering for the local user. It is read-only with respect to authoritative portfolio, market, signal, and allocation tables. It does not create prices, override signals, or write recommendation state.

Its inputs are existing persisted artefacts such as `allocation_runs`, `signal_readings`, `signal_events`, scenario outputs, friction results, and the append-only `decision_log`. Its job is to translate those records into concise explanations such as what changed since the prior run, why the recommended portfolio became more defensive or more aggressive, which constraints bound the solve, and which trades were blocked by friction or risk.

## Signal Layer

The signal layer provides four high-level user-visible signal areas:

1. GRY ranking and switch opportunity
2. Equity macro valuation versus gilts
3. Yield-curve shape
4. Duration and liquidity alerts

The dashboard is organised into four signal cards or areas, while the persisted alert catalogue may contain multiple underlying alert episodes within a single area, especially for the duration and liquidity area, which groups two distinct alerts in one UI area.

### GRY Ranking and Switch Signal

The GRY signal reuses the same shared gilt yield engine as the allocation engine. There is no second yield-calculation path inside the signal layer. Held and candidate conventional gilts are compared from the same LSE market snapshot so the signal answers a same-timestamp market question rather than mixing fresh candidate prices with stale imported holdings prices.

The headline ranking is conventional-gilt only by default. Owned index-linked gilts remain visible in holdings and risk views, but without an RPI assumption they are treated as monitored but manual and are excluded from yield-gap comparison and switch logic. If an expected RPI assumption is supplied later, index-linked gilts may join comparison after real-to-nominal conversion.

The ranked conventional-gilt table is always visible. The switch banner fires only when there is at least one comparable held conventional gilt and the best market conventional gilt beats the relevant held comparison by more than the configured threshold. If there are no comparable held conventional gilts, the ranking remains visible and the switch banner is suppressed with a plain-English note.

Missing prices or failed GRY solves degrade gracefully with warnings instead of disabling the full feature.

### Equity Macro Signal

The equity macro signal compares trailing FTSE 100 earnings yield with the best conventional-gilt GRY. Its canonical valuation source is the BlackRock UK ISF product page:

- `https://www.blackrock.com/uk/individual/products/251795/ishares-core-ftse-100-ucits-etf`

The parser extracts the dated `P/E Ratio` field from the public HTML and records both `pe_ratio` and `pe_as_of`. Earnings yield is then computed mechanically as `100 / pe_ratio`. The banner fires when the derived earnings yield is below the best conventional-gilt GRY.

Freshness is governed by the field's own `pe_as_of` date rather than only by fetch time. On live parse failure, a cached value may be reused for up to five trading days with a degraded-state warning. Beyond that, the equity macro banner is suppressed and the card remains visible with a stale or unavailable explanation.

### Yield-Curve Shape Signal

The yield-curve signal uses the Bank of England six-point curve at `1y`, `2y`, `5y`, `10y`, `20y`, and `30y`. It classifies each day into one of four states:

- Normal: `10y - 2y > +10bps`
- Inverted: `10y - 2y < -10bps`
- Flat: `|10y - 2y| <= 10bps`
- Humped: `5y > both 2y and 10y by >10bps`

The signal fires only after a classification has persisted for at least five consecutive business days.

### Duration and Liquidity Alerts

Two independent alerts share one user-visible area:

- Duration alert when weighted-average modified duration is outside configured floor or ceiling
- Liquidity concentration alert when too much value sits in the `10y+` maturity band

Both are user-configurable from the dashboard sidebar. Bond duration is derived from the same shared cash-flow engine used for GRY; there is no separate QuantLib path.

### Signal Episode Persistence

Signal state is persisted as a small explicit event-log system. Alert types are fixed in Python code, not created dynamically from market data. Each alert definition owns:

- stable `alert_type`
- default severity
- evaluator function
- message builder
- details payload builder

The `signal_events` table stores one row per real alert episode from first fire until clear. Logical identity is `(alert_type, scope_key)`, and a partial unique index enforces at most one active row per logical alert where `cleared_at IS NULL`.

Transition rules are:

- firing now with no active row: insert
- firing now with active row: update `last_seen_at`
- not firing now with active row: set `cleared_at` and update `last_seen_at`
- not firing and no active row: no-op

`message` and `details_json` store the opening snapshot and are not rewritten while the alert remains active. This preserves the answer to why the alert first fired.

### Authoritative Evaluation Timing

There are two evaluation modes:

- Daily refresh job: authoritative, writes `signal_readings` and `signal_events`
- Dashboard what-if evaluation: in-memory only, read-only with respect to persisted signal history

The dashboard may re-evaluate current conditions under changed knobs, but it must not create or clear persisted signal history rows.

## Friction Model

The friction model is strictly separate from the signal layer. Signals identify opportunities or risks based on market conditions. Friction determines whether a proposed trade is worth executing. The dashboard must always surface both the opportunity and the friction cost; signals are never silently suppressed by friction.

### Cost Components

A round-trip switch includes:

1. commission on both legs
2. bid-offer spread by derived friction class
3. stamp duty on the buy leg for equities and investment trusts only

The default formula is:

```text
total_friction = (2 * commission) + (spread_bps / 10000 * position_size) + stamp_duty
```

Default spread assumptions are parameterised in the dashboard knobs panel:

- Conventional gilts: 5 bps
- Index-linked gilts: 8 bps
- Gilt ETFs: 3 bps
- Corporate bonds: 15 bps
- Equities and investment trusts: 10 bps
- Cash and MMF: 0 bps

### Friction Routing

The friction layer derives routing classes from persisted `asset_type` plus maintained metadata and overrides. It does not widen the stored asset-type enum. For example, a persisted `etf` with explicit gilt-ETF metadata routes to the gilt-ETF spread bucket, while an ordinary `etf` without that override falls into the equities or investment-trust bucket.

### Break-Even and Trade Gate

The model computes break-even time in months from yield improvement and total friction:

```text
break_even_years = total_friction / (yield_improvement_decimal * position_size)
break_even_months = break_even_years * 12
```

The expected hold period defaults to two years and is user-editable. Break-even output is colour-coded:

- Green: break-even below 12 months
- Amber: break-even 12 to 24 months
- Red: break-even above 24 months

Thresholds derive mechanically from the chosen hold period:

- green: under 50 percent of hold period
- amber: 50 to 100 percent
- red: over 100 percent

For executable recommendations:

- green trades are included
- amber trades are included and marked marginal
- red trades are excluded

If a blocked red trade was a switch out of an existing position, the existing holding stays unchanged. If it was a deployment of free cash, the blocked amount remains in MMF or cash.

### Near-Maturity Behaviour

No special branch is required for near-maturity holdings. The break-even formula already handles them correctly because the time available to earn back friction is short. The dashboard adds a plain-English note when a holding matures within twelve months so the upcoming redemption is visible without changing the friction logic.

## Dashboard UX

The dashboard is a single-file Streamlit app with `layout="wide"` and an expanded sidebar. It reads persisted tables only. It does not fetch raw market data directly. Market refresh, signal history, and cache writes remain owned by the refresh coordinator.

### Layout

Top-level navigation uses four tabs:

1. Portfolio
2. Signals
3. Scenarios
4. Decision Log

Firing signals render as banners above the tabs so they remain visible regardless of the active tab.

### Sidebar Controls

The sidebar exposes the full active assumption set required by the system:

- Scenario selector and scenario magnitude
- GRY improvement threshold
- Duration floor and ceiling
- `10y+` liquidity concentration threshold
- Max maturity
- Max single-position concentration
- Minimum MMF or cash floor
- Minimum short-duration floor
- Expected RPI assumption
- Interactive Investor trade fee
- Expected hold period
- Asset-class spread assumptions

Values live in `st.session_state` with explicit keys so all tabs read the same current assumptions.

The canonical v1 field names and defaults for those sidebar assumptions are frozen in `src/investment_optimiser/policy_pack_v1.json` so allocator, scenario, and recommendation slices can consume the same schema.

The Portfolio tab includes a `Refresh market data` control near the holdings KPIs and table. It refreshes market and reference sources only, remains separate from portfolio CSV import, surfaces a visible last-successful refresh timestamp, clears cached query results on success, and reruns the app immediately.

### Portfolio Tab

The Portfolio tab shows:

- KPI metrics for total portfolio value, weighted-average duration, and weighted-average GRY where available
- side-by-side horizontal bar charts for current versus recommended allocation by bucket
- a holdings dataframe with core analytics, warnings, and portfolio-weight context

### Signals Tab

The Signals tab presents a `2x2` grid of bordered cards, one for each of the four high-level signal areas. Each card shows signal name, status, plain-English trigger summary, key metrics, and supporting data points. Quiet or blocked signals remain visible and explain why they are quiet. The card layout is a presentation grouping over the persisted alert system rather than a one-row-per-card persistence model.

### Scenarios Tab

The Scenarios tab surfaces summary metrics for the active scenario and the recommended state above a read-only comparison table derived from long-form scenario records. The active scenario column is highlighted in the presentation layer only. Coverage disclosure for exact-modelled, held-flat, and `unmodelled_held_flat` portions of the portfolio is mandatory.

### Decision Log Tab

The Decision Log tab is append-only. It shows a newest-first dataframe of historical entries and a `Log decision` form with:

- structured `action`: `acted`, `passed`, or `deferred`
- optional instrument references
- free-text notes

No historical editing or deletion is supported.

### Explanation and Change Reporting

The dashboard should make recommendation changes legible, not just visible. In addition to current-state tables and charts, it should surface a compact change report that answers:

- what changed since the previous authoritative run
- which signals, prices, or assumptions drove the change
- which constraints became binding
- which trades were blocked by friction
- which trades were blocked or downgraded by the risk gate
- how duration, liquidity, and adverse-scenario outcomes changed

This report can be generated on demand from persisted state in v1 rather than requiring a dedicated new write path. If a narrative explanation is shown, it must be traceable back to stored metrics and audit payloads rather than free-form unsupported commentary.

### Freshness UX

Freshness is computed from the latest successful `refresh_log` row per source, not the latest row overall. The dashboard uses two layers:

1. a compact top summary for all sources
2. local warnings or errors only in affected sections

Partial source failures never crash the entire page.

## Persistence Layer

The persistence layer is a single SQLite database owned by one local Streamlit app process. The dashboard is read-mostly and uses `st.connection("db", type="sql")` through `.streamlit/secrets.toml`. Refresh and import paths use raw `sqlite3`. WAL mode is enabled, and schema evolution uses `PRAGMA user_version` plus numbered startup migrations rather than Alembic.

Nothing is pruned. Data volume is small enough that a decade of history remains operationally trivial.

### Global Schema Policy

The schema follows these rules:

- all app-owned tables are `STRICT`
- `PRAGMA foreign_keys = ON`
- day-level dates are stored as `TEXT` in `YYYY-MM-DD`
- timestamps are stored as UTC ISO-8601 `TEXT`
- composite-key daily cache and snapshot tables use `WITHOUT ROWID`
- daily reruns use `ON CONFLICT DO UPDATE`
- no generic instrument master table is introduced

### Core Tables

The system persists eleven tables:

1. `portfolio_snapshots`
2. `signal_readings`
3. `signal_events`
4. `decision_log`
5. `yield_curve_cache`
6. `gilt_price_cache`
7. `equity_price_cache`
8. `equity_valuation_cache`
9. `refresh_log`
10. `gilt_reference`
11. `allocation_runs`

`portfolio_snapshots` stores one row per `(snapshot_date, symbol)`. `signal_readings` stores one row per `(reading_date, signal_name, metric_name)`. `signal_events` stores one row per alert episode, not one row per daily evaluation. `decision_log` is append-only with a required structured `action` and optional `signal_event_id` link plus JSON `instruments_affected`.

`yield_curve_cache` stores both named yield-curve points and the base rate. `gilt_price_cache` stores daily clean price, GRY, modified duration, coupon, maturity, and fetch timestamp for each successfully solved gilt. `equity_valuation_cache` stores dated FTSE 100 valuation inputs separately from trade-price caches because the equity signal depends on both `pe_ratio` and `pe_as_of`. `allocation_runs` stores the replayable optimiser audit payload as JSON-backed solve records with indexed scalar metadata columns for quick lookup.

The only required foreign key in v1 is `decision_log.signal_event_id -> signal_events.id ON DELETE SET NULL`. Historical cache and snapshot tables do not point back to `gilt_reference`.

No dedicated explanation or attribution table is required in v1. Change reports and human-readable recommendation summaries can be reconstructed on demand from existing persisted state, with optional caching later if needed for performance.

### Refresh Coordinator

The refresh job is a single-process writer coordinator with a process-global shared Python lock. If a refresh is already running, a second trigger returns a plain-English `refresh already running` status rather than waiting indefinitely or letting SQLite contention decide behaviour.

Each writer connection sets:

- `foreign_keys = ON`
- `journal_mode = WAL`
- `synchronous = NORMAL`
- `busy_timeout` to a small fixed value

Remote HTTP fetches stay outside write transactions. Each source gets its own short write transaction, and each source attempt writes exactly one terminal `refresh_log` row with either `completed` or `failed`. No `running` status exists in v1.

The refresh flow is:

1. local portfolio import
2. remote source refreshes in fixed order
3. authoritative signal persistence

Remote sources are processed independently in this order:

1. `boe`
2. `dmo_reference`
3. `lse_tidm_bridge` when needed by the reference refresh
4. `lse_gilt_prices`
5. `yfinance_equities`
6. `blackrock_ftse_pe`

Successful source writes and their `refresh_log(status='completed')` row commit atomically. Failed source writes roll back, then persist one standalone `refresh_log(status='failed')` row, and the coordinator continues to later sources. This preserves graceful degradation and same-day retry safety.

After cache and reference writes are complete, the coordinator computes and upserts today's `signal_readings`, reconciles `signal_events`, and commits the signal write in its own transaction.

### Dashboard Database Access

The dashboard connection is configured in `.streamlit/secrets.toml`:

```toml
[connections.db]
url = "sqlite:///data/investment_optimiser.db"
```

All reads use explicit TTLs:

- `ttl=60` for freshness-sensitive current-state reads
- `ttl=300` for heavier historical reads

The dashboard writes only through the Decision Log form using a short SQLAlchemy session. After a successful note save or manual refresh, `st.cache_data.clear()` is called and the app reruns so freshness indicators and tables update immediately.

### Operational Guarantees

The persistence design provides:

- idempotent same-day reruns through upserts
- append-only operational history through `refresh_log`
- append-only human decision history through `decision_log`
- replayable solver history through `allocation_runs`
- explicit signal episode history through `signal_events`
- reconstructable explanation and change-attribution outputs from existing audit state
- graceful partial-data operation through source-level freshness tracking

## Canonical Behaviour Summary

The final system behaviour is:

- import a saved Interactive Investor CSV into a canonical holdings model
- refresh free public data sources independently with per-source logging and graceful fallback
- compute shared fixed-income analytics once and reuse them across allocation and signalling
- persist both daily readings and alert episodes
- optimise the whole portfolio around a strategic baseline with explicit confidence, turnover, and scenario controls
- apply a realistic friction gate and final risk gate so executable recommendations differ from frictionless paper targets when necessary
- compare current versus executable recommended portfolios under named deterministic scenarios
- explain what changed, why it changed, and what blocked implementation using persisted audit state
- surface the result through a read-mostly Streamlit dashboard with clear freshness warnings, change reporting, and an append-only decision log

The stitched design assumes one coherent local product: a whole-portfolio SIPP allocation decision tool with honest modelling boundaries, durable audit history, explainable recommendations, and clear separation between market signals, friction filters, risk vetoes, optimisation policy, persistence, and presentation.
