from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import os
from pathlib import Path
from typing import Any

import streamlit as st

from investment_optimiser.db import initialize_database, sqlite_path_from_url
from investment_optimiser.portfolio_kpis import build_portfolio_kpis
from investment_optimiser.portfolio_import import (
    IngestionError,
    import_ii_portfolio_snapshot,
)
from investment_optimiser.boe import boe_handler
from investment_optimiser.dmo import dmo_handler
from investment_optimiser.refresh import REFRESH_SOURCE_ORDER, RefreshCoordinator


st.set_page_config(
    page_title="Investment Optimiser",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)


REFRESH_SOURCES = list(REFRESH_SOURCE_ORDER)
DEFAULT_DATABASE_URL = "sqlite:///data/investment_optimiser.db"
PORTFOLIO_UPLOAD_ERROR_KEY = "portfolio_upload_error"
PORTFOLIO_UPLOAD_FEEDBACK_KEY = "portfolio_upload_feedback"
REFRESH_FEEDBACK_KEY = "refresh_feedback"
REFRESH_WARNING_MESSAGES_KEY = "refresh_warning_messages"
PORTFOLIO_UPLOAD_WIDGET_KEY = "ii_csv_upload"


def get_database_url() -> str:
    configured_url = os.getenv("INVESTMENT_OPTIMISER_DB_URL")
    if configured_url:
        return configured_url

    try:
        return str(st.secrets["connections"]["db"]["url"])
    except Exception:
        return DEFAULT_DATABASE_URL


def apply_shell_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=JetBrains+Mono:wght@400;500&family=Outfit:wght@300;400;500;600&display=swap');

        /* ── Base ── */
        .stApp {
            background:
                radial-gradient(ellipse at 0% 0%, rgba(209, 162, 76, 0.09) 0%, transparent 55%),
                radial-gradient(ellipse at 100% 0%, rgba(72, 164, 196, 0.07) 0%, transparent 50%),
                #0d1117;
            font-family: 'Outfit', sans-serif;
        }

        .block-container {
            padding-top: 0.75rem !important;
            padding-bottom: 2rem !important;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #090e15 0%, #0b1219 100%) !important;
            border-right: 1px solid rgba(209, 162, 76, 0.14) !important;
        }

        .sidebar-brand {
            padding-bottom: 1.1rem;
            margin-bottom: 1.1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
        }

        .sidebar-brand-kicker {
            font-size: 0.62rem;
            letter-spacing: 0.24em;
            text-transform: uppercase;
            color: #d1a24c;
            margin-bottom: 0.25rem;
        }

        .sidebar-brand-title {
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 1.15rem;
            color: #f0e4c8;
            line-height: 1.1;
        }

        .sidebar-brand-meta {
            color: #384858;
            font-size: 0.72rem;
            margin-top: 0.2rem;
        }

        .sidebar-section-heading {
            text-transform: uppercase;
            letter-spacing: 0.2em;
            font-size: 0.62rem;
            color: #d1a24c;
            margin: 1.4rem 0 0.55rem;
            font-weight: 500;
            padding-top: 1rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* ── App header bar ── */
        .app-header {
            display: flex;
            align-items: baseline;
            gap: 0.9rem;
            padding-bottom: 0.4rem;
            margin-bottom: 0.25rem;
            border-bottom: 1px solid rgba(209, 162, 76, 0.18);
        }

        .app-header-kicker {
            font-size: 0.64rem;
            letter-spacing: 0.26em;
            text-transform: uppercase;
            color: #d1a24c;
            font-weight: 500;
            flex-shrink: 0;
            align-self: center;
        }

        .app-header-title {
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 1.9rem;
            color: #f6ecd1;
            margin: 0;
            line-height: 1;
        }

        .app-header-meta {
            margin-left: auto;
            color: #3d4f62;
            font-size: 0.75rem;
            white-space: nowrap;
            align-self: center;
            font-family: 'JetBrains Mono', monospace;
        }

        /* ── KPI strip ── */
        .kpi-strip {
            display: flex;
            align-items: stretch;
            background: rgba(11, 17, 27, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.055);
            border-radius: 10px;
            margin: 0.3rem 0 0.6rem;
            overflow: hidden;
        }

        .kpi-item {
            flex: 1;
            padding: 0.5rem 1rem;
            position: relative;
        }

        .kpi-item + .kpi-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 16%;
            height: 68%;
            width: 1px;
            background: rgba(255, 255, 255, 0.055);
        }

        .kpi-label {
            font-size: 0.62rem;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            color: #4e6175;
            margin-bottom: 0.2rem;
            font-weight: 500;
        }

        .kpi-value {
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 1.3rem;
            color: #f6ecd1;
            line-height: 1.05;
        }

        .kpi-note {
            font-size: 0.72rem;
            color: #3d4f62;
            margin-top: 0.04rem;
        }

        /* ── Portfolio inline KPIs ── */
        .portfolio-kpis {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.3rem 0 0.55rem;
        }

        .p-kpi-label {
            color: #4e6175;
            text-transform: uppercase;
            font-size: 0.62rem;
            letter-spacing: 0.15em;
            font-weight: 500;
        }

        .p-kpi-value {
            font-family: 'DM Serif Display', Georgia, serif;
            font-size: 1.1rem;
            color: #f6ecd1;
        }

        .p-kpi-sep {
            color: #2a3a4a;
            margin: 0 0.4rem;
            font-size: 1rem;
        }

        .kpi-value--muted {
            color: #2a3a4a !important;
            font-size: 1.2rem !important;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def read_shell_state(connection: Any) -> dict[str, Any]:
    summary = connection.query(
        """
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM portfolio_snapshots
        ),
        portfolio AS (
            SELECT
                COUNT(*) AS holding_count,
                COALESCE(SUM(market_value_gbp), 0) AS total_value
            FROM portfolio_snapshots
            WHERE snapshot_date = (SELECT snapshot_date FROM latest_snapshot)
        ),
        active_signals AS (
            SELECT COUNT(*) AS active_signal_count
            FROM signal_events
            WHERE cleared_at IS NULL
        ),
        decisions AS (
            SELECT COUNT(*) AS decision_count
            FROM decision_log
        ),
        allocations AS (
            SELECT COUNT(*) AS allocation_run_count
            FROM allocation_runs
        ),
        refresh_summary AS (
            SELECT MAX(finished_at) AS latest_successful_market_refresh_at
            FROM refresh_log
            WHERE status = 'completed'
        )
        SELECT
            latest_snapshot.snapshot_date AS latest_snapshot_date,
            portfolio.holding_count,
            portfolio.total_value,
            active_signals.active_signal_count,
            decisions.decision_count,
            allocations.allocation_run_count,
            refresh_summary.latest_successful_market_refresh_at
        FROM latest_snapshot, portfolio, active_signals, decisions, allocations, refresh_summary
        """,
        ttl=60,
    )
    summary_row = summary.iloc[0].to_dict()

    active_signal_rows = connection.query(
        """
        SELECT alert_type, severity, message, started_at
        FROM signal_events
        WHERE cleared_at IS NULL
        ORDER BY started_at DESC
        LIMIT 3
        """,
        ttl=60,
    )
    holdings_rows = connection.query(
        """
        SELECT
            symbol,
            instrument_name,
            asset_type,
            quantity,
            market_value_gbp,
            weight_pct,
            snapshot_date
        FROM portfolio_snapshots
        WHERE snapshot_date = (
            SELECT MAX(snapshot_date)
            FROM portfolio_snapshots
        )
        ORDER BY market_value_gbp DESC, symbol ASC
        """,
        ttl=60,
    )
    decision_rows = connection.query(
        """
        SELECT decision_date, action, notes, created_at
        FROM decision_log
        ORDER BY created_at DESC
        LIMIT 8
        """,
        ttl=60,
    )
    refresh_rows = connection.query(
        """
        SELECT source, status, finished_at
        FROM refresh_log
        WHERE id IN (
            SELECT MAX(id)
            FROM refresh_log
            GROUP BY source
        )
        """,
        ttl=60,
    )

    refresh_state: list[dict[str, str]] = []
    refresh_map = {
        row["source"]: {
            "source": row["source"],
            "status": row["status"],
            "finished_at": row["finished_at"],
        }
        for _, row in refresh_rows.iterrows()
    }
    for source in REFRESH_SOURCES:
        refresh_state.append(
            refresh_map.get(
                source,
                {
                    "source": source,
                    "status": "unavailable",
                    "finished_at": "No successful refresh yet",
                },
            )
        )

    return {
        "summary": summary_row,
        "active_signals": active_signal_rows,
        "holdings": holdings_rows,
        "decisions": decision_rows,
        "refresh_state": refresh_state,
    }


def metric_note(value: Any) -> str:
    if value in (None, "", 0, 0.0):
        return "Waiting for the first persisted run"
    return str(value)


def get_portfolio_csv_path(database_url: str) -> Path:
    database_path = sqlite_path_from_url(database_url)
    return database_path.parent / "portfolio_latest.csv"


def store_and_import_portfolio_csv(
    database_url: str,
    portfolio_csv_path: Path,
    uploaded_file: Any,
) -> dict[str, Any]:
    file_bytes = uploaded_file.getvalue()
    portfolio_csv_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio_csv_path.write_bytes(file_bytes)

    result = import_ii_portfolio_snapshot(
        database_url,
        BytesIO(file_bytes),
        snapshot_date=date.today().isoformat(),
    )
    return {
        "imported_count": result.imported_count,
        "snapshot_date": result.snapshot_date,
        "warning_messages": result.warning_messages,
    }


def import_uploaded_portfolio_csv(
    database_url: str,
    portfolio_csv_path: Path,
) -> None:
    uploaded_file = st.session_state.get(PORTFOLIO_UPLOAD_WIDGET_KEY)
    if uploaded_file is None:
        return

    try:
        import_feedback = store_and_import_portfolio_csv(
            database_url=database_url,
            portfolio_csv_path=portfolio_csv_path,
            uploaded_file=uploaded_file,
        )
    except IngestionError as exc:
        st.session_state[PORTFOLIO_UPLOAD_ERROR_KEY] = str(exc)
        st.session_state.pop(PORTFOLIO_UPLOAD_FEEDBACK_KEY, None)
    except OSError as exc:
        st.session_state[PORTFOLIO_UPLOAD_ERROR_KEY] = (
            f"Could not store the uploaded CSV: {exc}"
        )
        st.session_state.pop(PORTFOLIO_UPLOAD_FEEDBACK_KEY, None)
    else:
        st.session_state[PORTFOLIO_UPLOAD_FEEDBACK_KEY] = import_feedback
        st.session_state.pop(PORTFOLIO_UPLOAD_ERROR_KEY, None)
        st.cache_data.clear()


def render_hero(schema_version: int, snapshot_date: str) -> None:
    st.markdown(
        f"""
        <div class="app-header">
            <h1 class="app-header-title">Investment Optimiser</h1>
            <span class="app-header-meta">schema v{schema_version} &nbsp;·&nbsp; snapshot {snapshot_date}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _kpi_val_html(raw: int, label: str) -> tuple[str, str, str]:
    """Return (display_value, css_class, note) for a KPI tile."""
    if raw == 0:
        return "—", "kpi-value kpi-value--muted", "None yet"
    return str(raw), "kpi-value", label


def render_kpi_strip(summary: dict[str, Any]) -> None:
    snapshot_val = metric_note(summary["latest_snapshot_date"])
    holding_note = f"{int(summary['holding_count'] or 0)} holdings loaded"

    alloc_raw = int(summary["allocation_run_count"] or 0)
    alerts_raw = int(summary["active_signal_count"] or 0)
    decisions_raw = int(summary["decision_count"] or 0)

    alloc_val, alloc_cls, alloc_note = _kpi_val_html(alloc_raw, "Persisted optimiser records")
    alerts_val, alerts_cls, alerts_note = _kpi_val_html(alerts_raw, "Live signal episodes")
    decisions_val, decisions_cls, decisions_note = _kpi_val_html(decisions_raw, "Append-only decision log")

    st.markdown(
        f"""
        <div class="kpi-strip">
            <div class="kpi-item">
                <div class="kpi-label">Latest Snapshot</div>
                <div class="kpi-value">{snapshot_val}</div>
                <div class="kpi-note">{holding_note}</div>
            </div>
            <div class="kpi-item">
                <div class="kpi-label">Allocation Runs</div>
                <div class="{alloc_cls}">{alloc_val}</div>
                <div class="kpi-note">{alloc_note}</div>
            </div>
            <div class="kpi-item">
                <div class="kpi-label">Active Alerts</div>
                <div class="{alerts_cls}">{alerts_val}</div>
                <div class="kpi-note">{alerts_note}</div>
            </div>
            <div class="kpi-item">
                <div class="kpi-label">Logged Decisions</div>
                <div class="{decisions_cls}">{decisions_val}</div>
                <div class="kpi-note">{decisions_note}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_signal_banners(active_signals: Any) -> None:
    if active_signals.empty:
        return

    for _, row in active_signals.iterrows():
        message = f"{row['alert_type']}: {row['message']}"
        if row["severity"] == "error":
            st.error(message)
        else:
            st.warning(message)


def format_refresh_timestamp(timestamp: str | None) -> str | None:
    if not timestamp:
        return None

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def render_refresh_controls(
    *,
    state: dict[str, Any],
    database_url: str,
    portfolio_csv_path: Path,
) -> None:
    latest_successful_refresh = format_refresh_timestamp(
        state["summary"].get("latest_successful_market_refresh_at")
    )

    if latest_successful_refresh:
        st.caption(f"Last refresh: {latest_successful_refresh}")
    else:
        st.caption("Market data not yet refreshed")

    refresh_clicked = st.button("Refresh market data", use_container_width=True)

    if refresh_clicked:
        with st.spinner("Refreshing market data...", show_time=True):
            coordinator = RefreshCoordinator(
                portfolio_csv_path=portfolio_csv_path,
                source_handlers={"boe": boe_handler, "dmo_reference": dmo_handler},
            )
            result = coordinator.run_refresh(
                database_url,
                snapshot_date=date.today().isoformat(),
                include_portfolio_import=False,
            )
        st.session_state[REFRESH_FEEDBACK_KEY] = {
            "status": result.status,
            "message": result.message,
        }
        st.session_state[REFRESH_WARNING_MESSAGES_KEY] = result.warning_messages
        if result.status == "completed":
            st.cache_data.clear()
            st.rerun()

    refresh_feedback = st.session_state.get(REFRESH_FEEDBACK_KEY)
    if refresh_feedback:
        if refresh_feedback["status"] == "failed":
            st.error(refresh_feedback["message"])
        elif refresh_feedback["status"] == "already_running":
            st.warning(refresh_feedback["message"])
        else:
            st.success(refresh_feedback["message"])

    for warning_message in st.session_state.get(REFRESH_WARNING_MESSAGES_KEY, []):
        st.warning(warning_message)


def render_import_panel(
    database_url: str,
    portfolio_csv_path: Path,
    has_snapshot: bool,
) -> None:
    with st.expander("Import or replace snapshot", expanded=not has_snapshot):
        st.caption(
            "Upload an Interactive Investor CSV to replace the app's current portfolio snapshot."
        )

        st.file_uploader(
            "Interactive Investor CSV",
            type="csv",
            key=PORTFOLIO_UPLOAD_WIDGET_KEY,
            help="Upload the latest holdings export from Interactive Investor.",
            on_change=import_uploaded_portfolio_csv,
            args=(database_url, portfolio_csv_path),
        )

        import_error = st.session_state.get(PORTFOLIO_UPLOAD_ERROR_KEY)
        if import_error:
            st.error(import_error)

        import_feedback = st.session_state.get(PORTFOLIO_UPLOAD_FEEDBACK_KEY)
        if import_feedback:
            st.success(
                "Imported "
                f"{import_feedback['imported_count']} holdings for "
                f"{import_feedback['snapshot_date']}."
            )
            for warning_message in import_feedback["warning_messages"]:
                st.warning(warning_message)


def render_sidebar(
    state: dict[str, Any],
    database_url: str,
    portfolio_csv_path: Path,
) -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-kicker">SIPP Decision Support</div>
                <div class="sidebar-brand-title">Investment Optimiser</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="sidebar-section-heading">Portfolio Import</div>',
            unsafe_allow_html=True,
        )
        render_import_panel(
            database_url,
            portfolio_csv_path,
            has_snapshot=bool(state["summary"]["latest_snapshot_date"]),
        )

        st.markdown(
            '<div class="sidebar-section-heading">Market Data</div>',
            unsafe_allow_html=True,
        )
        render_refresh_controls(
            state=state,
            database_url=database_url,
            portfolio_csv_path=portfolio_csv_path,
        )


def render_portfolio_tab(state: dict[str, Any]) -> None:
    summary = state["summary"]
    holdings_frame = state["holdings"]

    if holdings_frame.empty:
        st.info(
            "`portfolio_snapshots` is empty. Upload a portfolio CSV via the sidebar to get started."
        )
        return

    portfolio_kpis = build_portfolio_kpis(
        holdings_frame.to_dict("records"),
        summary["latest_snapshot_date"],
    )
    st.markdown(
        f"""
        <div class="portfolio-kpis">
            <span class="p-kpi-label">Total Value</span>
            <span class="p-kpi-value">GBP&nbsp;{portfolio_kpis.total_value_gbp:,.0f}</span>
            <span class="p-kpi-sep">·</span>
            <span class="p-kpi-label">Holdings</span>
            <span class="p-kpi-value">{portfolio_kpis.holding_count}</span>
            <span class="p-kpi-sep">·</span>
            <span class="p-kpi-label">Cash &amp; MMF</span>
            <span class="p-kpi-value">{portfolio_kpis.mmf_weight_pct:.1f}%</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    display_frame = holdings_frame.drop(columns=["snapshot_date"], errors="ignore")
    st.dataframe(
        display_frame,
        use_container_width=True,
        hide_index=True,
        height=600,
        column_config={
            "symbol": st.column_config.TextColumn("Symbol"),
            "instrument_name": st.column_config.TextColumn("Name"),
            "asset_type": st.column_config.TextColumn("Type"),
            "quantity": st.column_config.NumberColumn("Quantity", format="%,.2f"),
            "market_value_gbp": st.column_config.NumberColumn("Market Value", format="£%,.2f"),
            "weight_pct": st.column_config.NumberColumn("Weight %", format="%.2f%%"),
        },
    )


def render_signals_tab(state: dict[str, Any]) -> None:
    st.subheader("Signals")
    active_signal_count = int(state["summary"]["active_signal_count"] or 0)
    st.write(
        f"There are currently `{active_signal_count}` active persisted alert episodes. "
        "Signal cards and diagnostics will build on the same `signal_readings` and "
        "`signal_events` tables created at startup."
    )
    if state["active_signals"].empty:
        st.info("No active signal episodes are stored yet.")
    else:
        st.dataframe(state["active_signals"], width="stretch", hide_index=True)


def render_scenarios_tab(state: dict[str, Any]) -> None:
    st.subheader("Scenarios")
    allocation_run_count = int(state["summary"]["allocation_run_count"] or 0)
    st.write(
        f"The database currently holds `{allocation_run_count}` allocation runs. "
        "Scenario comparisons and recommended-state summaries will attach to those "
        "persisted optimisation records."
    )
    refresh_frame = state["refresh_state"]
    st.dataframe(refresh_frame, width="stretch", hide_index=True)


def render_decision_log_tab(state: dict[str, Any]) -> None:
    st.subheader("Decision Log")
    decision_count = int(state["summary"]["decision_count"] or 0)
    st.write(
        f"There are `{decision_count}` decision-log entries persisted so far. "
        "This append-only tab is already pointed at the real `decision_log` table."
    )
    if state["decisions"].empty:
        st.info("No decisions have been logged yet.")
    else:
        st.dataframe(state["decisions"], width="stretch", hide_index=True)


def main() -> None:
    database_url = get_database_url()
    portfolio_csv_path = get_portfolio_csv_path(database_url)
    schema_version = initialize_database(database_url)
    apply_shell_styles()
    connection = st.connection("db", type="sql", url=database_url)
    state = read_shell_state(connection)
    summary = state["summary"]

    render_sidebar(state, database_url, portfolio_csv_path)

    snapshot_date = summary["latest_snapshot_date"] or "no snapshot"
    render_hero(schema_version, snapshot_date)
    render_signal_banners(state["active_signals"])
    render_kpi_strip(summary)

    portfolio_tab, signals_tab, scenarios_tab, decision_log_tab = st.tabs(
        ["Portfolio", "Signals", "Scenarios", "Decision Log"]
    )

    with portfolio_tab:
        render_portfolio_tab(state)
    with signals_tab:
        render_signals_tab(state)
    with scenarios_tab:
        render_scenarios_tab(state)
    with decision_log_tab:
        render_decision_log_tab(state)


if __name__ == "__main__":
    main()
