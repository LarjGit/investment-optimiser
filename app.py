from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import os
from pathlib import Path
from typing import Any

import streamlit as st

from investment_optimiser.boe import boe_handler
from investment_optimiser.db import initialize_database, sqlite_path_from_url
from investment_optimiser.dmo import dmo_handler
from investment_optimiser.lse_gilt_prices import lse_gilt_prices_handler
from investment_optimiser.non_gilt_reference import non_gilt_reference_handler
from investment_optimiser.tidm import tidm_handler
from investment_optimiser.portfolio_import import (
    IngestionError,
    import_ii_portfolio_snapshot,
)
from investment_optimiser.portfolio_kpis import build_portfolio_kpis
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
    st.html(
        """
        <style>
        .stApp {
            background:
                radial-gradient(ellipse at 0% 0%, rgba(209, 162, 76, 0.09) 0%, transparent 55%),
                radial-gradient(ellipse at 100% 0%, rgba(72, 164, 196, 0.07) 0%, transparent 50%),
                #0d1117;
        }

        .block-container {
            padding-top: 3rem !important;
            padding-bottom: 2rem !important;
        }

        div[data-testid="stMetric"] {
            padding: 0.55rem 0.75rem !important;
        }

        div[data-testid="stMetricLabel"] p {
            font-size: 0.8rem !important;
        }

        div[data-testid="stMetricValue"] {
            font-size: 1.95rem !important;
            line-height: 1.1 !important;
        }

        div[data-testid="stMetricDelta"] {
            font-size: 0.8rem !important;
            line-height: 1.1 !important;
        }
        </style>
        """
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
    st.title("Investment Optimiser")
    st.caption(f"Schema v{schema_version} | Snapshot {snapshot_date}")


def render_kpi_strip(summary: dict[str, Any]) -> None:
    summary_columns = st.columns(4)

    with summary_columns[0]:
        st.metric(
            "Latest Snapshot",
            metric_note(summary["latest_snapshot_date"]),
            f"{int(summary['holding_count'] or 0)} holdings loaded",
            border=True,
        )
    with summary_columns[1]:
        st.metric(
            "Allocation Runs",
            str(int(summary["allocation_run_count"] or 0)),
            "Persisted optimiser records",
            border=True,
        )
    with summary_columns[2]:
        st.metric(
            "Active Alerts",
            str(int(summary["active_signal_count"] or 0)),
            "Live signal episodes",
            border=True,
        )
    with summary_columns[3]:
        st.metric(
            "Logged Decisions",
            str(int(summary["decision_count"] or 0)),
            "Append-only decision log",
            border=True,
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

    refresh_clicked = st.button("Refresh market data", width="stretch")

    if refresh_clicked:
        with st.spinner("Refreshing market data...", show_time=True):
            coordinator = RefreshCoordinator(
                portfolio_csv_path=portfolio_csv_path,
                source_handlers={
                    "boe": boe_handler,
                    "dmo_reference": dmo_handler,
                    "lse_tidm_bridge": tidm_handler,
                    "non_gilt_reference": non_gilt_reference_handler,
                    "lse_gilt_prices": lse_gilt_prices_handler,
                },
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
        st.subheader("Investment Optimiser")
        st.caption("SIPP decision support")
        st.divider()
        st.caption("Portfolio Import")
        render_import_panel(
            database_url,
            portfolio_csv_path,
            has_snapshot=bool(state["summary"]["latest_snapshot_date"]),
        )
        st.divider()
        st.caption("Market Data")
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

    latest_snapshot = summary["latest_snapshot_date"] or "No snapshot loaded"
    header_column, snapshot_column = st.columns([1.4, 1])
    with header_column:
        st.subheader("Portfolio State")
    with snapshot_column:
        st.caption(f"Latest snapshot: {latest_snapshot}")

    portfolio_kpis = build_portfolio_kpis(
        holdings_frame.to_dict("records"),
        summary["latest_snapshot_date"],
    )
    metric_columns = st.columns(3)
    metric_columns[0].metric(
        "Total Portfolio Value",
        f"GBP {portfolio_kpis.total_value_gbp:,.0f}",
        border=False,
    )
    metric_columns[1].metric(
        "Holdings",
        str(portfolio_kpis.holding_count),
        border=False,
    )
    metric_columns[2].metric(
        "Cash & MMF Share",
        f"{portfolio_kpis.mmf_weight_pct:.1f}%",
        border=False,
    )

    display_frame = holdings_frame.drop(columns=["snapshot_date"], errors="ignore")
    st.dataframe(
        display_frame,
        width="stretch",
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

    snapshot_date = summary["latest_snapshot_date"] or "No snapshot loaded"
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
