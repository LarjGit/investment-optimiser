---
section: dashboard-ux
phase: level2
status: complete
date: 2026-05-16
---

## What We Established

The dashboard is a single-file Streamlit app using `layout="wide"`, dark theme via `.streamlit/config.toml`, and `initial_sidebar_state="expanded"`. Top-level navigation is four `st.tabs` (Portfolio, Signals, Scenarios, Decision Log). Firing signals render as `st.warning` or `st.error` banners above the tabs so they are always visible regardless of active tab.

### Sidebar Knobs (session-scoped unless later promoted to saved presets)
The sidebar must expose every user-controlled input used by the allocation, signal, friction, and scenario views. The knobs are grouped, not limited to five controls:

- **Scenario controls** - active scenario selector plus scenario shift magnitude
- **Signal controls** - GRY improvement threshold, duration floor, duration ceiling, and 10y+ liquidity concentration threshold
- **Fixed-income sleeve controls** - max maturity, max single-position concentration, minimum MMF or cash floor, minimum short-duration floor, expected RPI assumption for index-linked comparability
- **Friction controls** - ii trade fee, expected hold period, and asset-class spread assumptions

These values are wired through `st.session_state` with explicit keys so all tabs read the same active assumptions.

Also in the sidebar: a `Refresh now` button that triggers the refresh coordinator, then clears cached query results and reruns the app when the refresh succeeds.

### Portfolio Tab
- KPI row using `st.columns(...)` plus `st.metric` for total portfolio value, weighted average duration, and weighted average GRY where available
- Side-by-side Plotly horizontal bar charts for current allocation versus recommended allocation by asset bucket
- Below: `st.dataframe` of individual holdings with core analytics, warnings, and percent-of-portfolio context

### Signals Tab
- 2x2 grid of bordered cards, one per signal
- Each card shows the signal name, status badge, plain-English trigger summary, key driving metrics, and top supporting data points
- All four signals always show; quiet or blocked signals explain why they are quiet

### Scenarios Tab
- Summary metrics above the main table for the active scenario and recommended state
- Read-only comparison table derived from long-form scenario records
- Active scenario column highlighted in the presentation layer only
- Coverage disclosure for exact-modelled, held-flat, and `unmodelled_held_flat` portions of the portfolio

### Decision Log Tab
- Read-only `st.dataframe` of decision history, newest first
- `Log decision` form above the table using an explicit `action` control (`acted`, `passed`, `deferred`), optional instrument selection, and `st.text_area` for notes plus `st.button("Save entry")`
- Append-only; no editing or deletion of historical entries

### Data Loading
The dashboard reads persisted tables only. It does not fetch raw market data directly.

- Database access uses `st.connection("db", type="sql")`
- Reads come from persisted snapshot, cache, signal, and log tables with explicit short TTLs
- Freshness is derived from the latest successful `refresh_log` row per source
- The UI shows a compact top-level source status summary plus local warnings in only the affected sections
- Manual refresh delegates to the refresh coordinator; after a successful refresh the dashboard clears its cached query results and reruns

## Decisions Made

- Single-file Streamlit app, `layout="wide"`, dark theme, sidebar always expanded
- Four tabs: Portfolio, Signals, Scenarios, Decision Log
- Firing signal banners above tabs so they are always visible
- Sidebar exposes the full active assumption set required by allocation, signals, friction, and scenarios
- Refresh button triggers the refresh coordinator, then clears cached query results and reruns
- Portfolio tab: KPI metrics plus dual horizontal bar charts and holdings dataframe
- Signals tab: 2x2 card grid, all four signals always shown
- Scenarios tab: read-only comparison table with active scenario highlighted
- Decision Log tab: append-only log plus structured action entry form with optional notes
- Dashboard is read-only for market and signal data: all reads go through persisted SQLite tables via `st.connection`
- Freshness UX is per source with graceful degradation; partial data issues never crash the whole page

## Remaining Open Questions

None
