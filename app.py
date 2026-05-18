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
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(209, 162, 76, 0.16), transparent 34%),
                radial-gradient(circle at top right, rgba(72, 164, 196, 0.12), transparent 28%),
                linear-gradient(180deg, #0d1117 0%, #121821 100%);
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        .hero-shell {
            padding: 1.4rem 1.6rem;
            border: 1px solid rgba(209, 162, 76, 0.35);
            background: linear-gradient(135deg, rgba(24, 29, 37, 0.95), rgba(14, 18, 24, 0.88));
            border-radius: 20px;
            box-shadow: 0 18px 40px rgba(0, 0, 0, 0.28);
            margin-bottom: 1rem;
        }

        .hero-kicker {
            letter-spacing: 0.24em;
            text-transform: uppercase;
            color: #d1a24c;
            font-size: 0.75rem;
            margin-bottom: 0.4rem;
        }

        .hero-title {
            font-family: Georgia, "Times New Roman", serif;
            font-size: 2.5rem;
            line-height: 1.05;
            margin: 0;
            color: #f6ecd1;
        }

        .hero-copy {
            margin-top: 0.8rem;
            color: #bac4d1;
            max-width: 48rem;
            font-size: 1rem;
        }

        .summary-card {
            min-height: 9rem;
            padding: 1.1rem 1.2rem;
            border-radius: 18px;
            border: 1px solid rgba(72, 164, 196, 0.18);
            background: rgba(18, 24, 33, 0.84);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        }

        .summary-label {
            color: #8ea2bb;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.72rem;
            margin-bottom: 0.45rem;
        }

        .summary-value {
            font-size: 1.9rem;
            color: #f6ecd1;
            font-weight: 600;
            line-height: 1.1;
        }

        .summary-note {
            margin-top: 0.55rem;
            color: #a9b3bf;
            font-size: 0.92rem;
        }

        .market-shell {
            padding: 1rem 1.15rem 1.1rem;
            border-radius: 18px;
            border: 1px solid rgba(72, 164, 196, 0.22);
            background: linear-gradient(145deg, rgba(16, 22, 31, 0.96), rgba(22, 30, 41, 0.9));
            margin: 0.75rem 0 1rem;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }

        .market-kicker {
            color: #d1a24c;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            font-size: 0.7rem;
            margin-bottom: 0.35rem;
        }

        .market-title {
            color: #f6ecd1;
            font-family: Georgia, "Times New Roman", serif;
            font-size: 1.18rem;
            margin-bottom: 0.3rem;
        }

        .market-copy {
            color: #a9b3bf;
            font-size: 0.92rem;
            line-height: 1.45;
            max-width: 42rem;
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


def render_summary_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">{label}</div>
            <div class="summary-value">{value}</div>
            <div class="summary-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def render_hero(schema_version: int, summary: dict[str, Any]) -> None:
    snapshot_date = summary["latest_snapshot_date"] or "No snapshot loaded"
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="hero-kicker">Local Decision Support</div>
            <h1 class="hero-title">Investment Optimiser Control Room</h1>
            <div class="hero-copy">
                Schema v{schema_version}. Latest portfolio snapshot: {snapshot_date}.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_signal_banners(active_signals: Any) -> None:
    if active_signals.empty:
        st.caption("No active persisted alerts yet.")
        return

    for _, row in active_signals.iterrows():
        message = f"{row['alert_type']}: {row['message']}"
        if row["severity"] == "error":
            st.error(message)
        else:
            st.warning(message)


def render_portfolio_tab(
    state: dict[str, Any],
    database_url: str,
    portfolio_csv_path: Path,
) -> None:
    st.subheader("Portfolio State")
    summary = state["summary"]
    latest_snapshot = summary["latest_snapshot_date"] or "No snapshot loaded"
    holdings_frame = state["holdings"]
    portfolio_kpis = build_portfolio_kpis(
        holdings_frame.to_dict("records"),
        summary["latest_snapshot_date"],
    )
    st.write(
        f"Latest snapshot: `{latest_snapshot}`."
    )
    render_refresh_controls(
        state=state,
        database_url=database_url,
        portfolio_csv_path=portfolio_csv_path,
    )
    if holdings_frame.empty:
        st.info("`portfolio_snapshots` is empty. Import and refresh flows will populate this view.")
    else:
        metric_columns = st.columns(3)
        metric_columns[0].metric(
            "Total Portfolio Value",
            f"GBP {portfolio_kpis.total_value_gbp:,.0f}",
            border=True,
        )
        metric_columns[1].metric(
            "Holdings",
            str(portfolio_kpis.holding_count),
            border=True,
        )
        metric_columns[2].metric(
            "Cash & MMF Share",
            f"{portfolio_kpis.mmf_weight_pct:.1f}%",
            border=True,
        )
        st.dataframe(holdings_frame, width="stretch", hide_index=True)


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
    st.markdown(
        """
        <div class="market-shell">
            <div class="market-kicker">Market Data</div>
            <div class="market-title">Refresh pricing and reference sources</div>
            <div class="market-copy">
                Refresh live market and reference sources. This is separate from uploading
                your broker portfolio CSV.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    latest_successful_refresh = format_refresh_timestamp(
        state["summary"].get("latest_successful_market_refresh_at")
    )
    details_column, button_column = st.columns([2.6, 1])

    with details_column:
        if latest_successful_refresh:
            st.markdown(
                f"Last successful market refresh: `{latest_successful_refresh}`."
            )
        else:
            st.info("No successful market refresh has been recorded yet.")

    with button_column:
        refresh_clicked = st.button("Refresh market data", use_container_width=True)

    if refresh_clicked:
        with st.spinner("Refreshing market data...", show_time=True):
            coordinator = RefreshCoordinator(portfolio_csv_path=portfolio_csv_path)
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
    expander_label = "Import or replace portfolio snapshot"
    with st.expander(expander_label, expanded=not has_snapshot):
        st.write(
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

    render_hero(schema_version, summary)
    render_signal_banners(state["active_signals"])

    summary_columns = st.columns(4)
    with summary_columns[0]:
        render_summary_card(
            "Latest Snapshot",
            metric_note(summary["latest_snapshot_date"]),
            f"{int(summary['holding_count'] or 0)} holdings loaded",
        )
    with summary_columns[1]:
        render_summary_card(
            "Allocation Runs",
            str(int(summary["allocation_run_count"] or 0)),
            "Persisted optimiser records available for replay",
        )
    with summary_columns[2]:
        render_summary_card(
            "Active Alerts",
            str(int(summary["active_signal_count"] or 0)),
            "Live episodes stored in `signal_events`",
        )
    with summary_columns[3]:
        render_summary_card(
            "Logged Decisions",
            str(int(summary["decision_count"] or 0)),
            "Append-only entries already backed by SQLite",
        )

    portfolio_tab, signals_tab, scenarios_tab, decision_log_tab = st.tabs(
        ["Portfolio", "Signals", "Scenarios", "Decision Log"]
    )

    with portfolio_tab:
        render_portfolio_tab(state, database_url, portfolio_csv_path)
        render_import_panel(
            database_url,
            portfolio_csv_path,
            has_snapshot=bool(summary["latest_snapshot_date"]),
        )
    with signals_tab:
        render_signals_tab(state)
    with scenarios_tab:
        render_scenarios_tab(state)
    with decision_log_tab:
        render_decision_log_tab(state)


if __name__ == "__main__":
    main()
