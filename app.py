from __future__ import annotations

from datetime import date
import os
from typing import Any

import streamlit as st

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import (
    IngestionError,
    import_ii_portfolio_snapshot,
)


st.set_page_config(
    page_title="Investment Optimiser",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)


REFRESH_SOURCES = [
    "boe",
    "dmo_reference",
    "blackrock_ftse_pe",
    "lse_tidm_bridge",
    "lse_gilt_prices",
    "yfinance_equities",
]
DEFAULT_DATABASE_URL = "sqlite:///data/investment_optimiser.db"
PORTFOLIO_IMPORT_ERROR_KEY = "portfolio_import_error"
PORTFOLIO_IMPORT_FEEDBACK_KEY = "portfolio_import_feedback"


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

        .panel-card {
            padding: 1.15rem 1.2rem;
            border-radius: 18px;
            background: rgba(18, 24, 33, 0.72);
            border: 1px solid rgba(255, 255, 255, 0.06);
            margin-bottom: 1rem;
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
        )
        SELECT
            latest_snapshot.snapshot_date AS latest_snapshot_date,
            portfolio.holding_count,
            portfolio.total_value,
            active_signals.active_signal_count,
            decisions.decision_count,
            allocations.allocation_run_count
        FROM latest_snapshot, portfolio, active_signals, decisions, allocations
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
        LIMIT 10
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


def render_hero(schema_version: int, summary: dict[str, Any]) -> None:
    snapshot_date = summary["latest_snapshot_date"] or "No snapshot loaded"
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="hero-kicker">Local Decision Support</div>
            <h1 class="hero-title">Investment Optimiser Control Room</h1>
            <div class="hero-copy">
                Schema v{schema_version} is live. This shell is already reading
                persisted SQLite state, so each tab can grow from the same durable
                local record instead of disposable demo text.
                Latest portfolio snapshot: {snapshot_date}.
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


def render_portfolio_tab(state: dict[str, Any]) -> None:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.subheader("Portfolio State")
    summary = state["summary"]
    latest_snapshot = summary["latest_snapshot_date"] or "No snapshot loaded"
    st.write(
        f"Latest persisted snapshot: `{latest_snapshot}`. "
        "This tab is ready to surface holdings, allocation, and duration metrics "
        "as soon as imports begin writing to SQLite."
    )
    if state["holdings"].empty:
        st.info("`portfolio_snapshots` is empty. Import and refresh flows will populate this view.")
    else:
        st.dataframe(state["holdings"], use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_import_panel(database_url: str) -> None:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.subheader("Portfolio Import")
    st.write(
        "Upload an Interactive Investor CSV to persist today's authoritative "
        "portfolio snapshot into SQLite."
    )

    uploaded_file = st.file_uploader(
        "Interactive Investor CSV",
        type="csv",
        key="ii_csv_upload",
    )
    if st.button("Import Interactive Investor CSV", type="primary"):
        if uploaded_file is None:
            st.session_state[PORTFOLIO_IMPORT_ERROR_KEY] = "Choose a CSV file to import."
        else:
            try:
                result = import_ii_portfolio_snapshot(
                    database_url,
                    uploaded_file,
                    snapshot_date=date.today().isoformat(),
                )
            except IngestionError as exc:
                st.session_state[PORTFOLIO_IMPORT_ERROR_KEY] = str(exc)
                st.session_state.pop(PORTFOLIO_IMPORT_FEEDBACK_KEY, None)
            else:
                st.session_state[PORTFOLIO_IMPORT_FEEDBACK_KEY] = {
                    "snapshot_date": result.snapshot_date,
                    "imported_count": result.imported_count,
                    "warning_messages": result.warning_messages,
                }
                st.session_state.pop(PORTFOLIO_IMPORT_ERROR_KEY, None)
                st.cache_data.clear()
                st.rerun()

    import_error = st.session_state.get(PORTFOLIO_IMPORT_ERROR_KEY)
    if import_error:
        st.error(import_error)

    import_feedback = st.session_state.get(PORTFOLIO_IMPORT_FEEDBACK_KEY)
    if import_feedback:
        st.success(
            "Imported "
            f"{import_feedback['imported_count']} holdings for "
            f"{import_feedback['snapshot_date']}."
        )
        for warning_message in import_feedback["warning_messages"]:
            st.warning(warning_message)

    st.markdown("</div>", unsafe_allow_html=True)


def render_signals_tab(state: dict[str, Any]) -> None:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
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
        st.dataframe(state["active_signals"], use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_scenarios_tab(state: dict[str, Any]) -> None:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.subheader("Scenarios")
    allocation_run_count = int(state["summary"]["allocation_run_count"] or 0)
    st.write(
        f"The database currently holds `{allocation_run_count}` allocation runs. "
        "Scenario comparisons and recommended-state summaries will attach to those "
        "persisted optimisation records."
    )
    refresh_frame = state["refresh_state"]
    st.dataframe(refresh_frame, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_decision_log_tab(state: dict[str, Any]) -> None:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.subheader("Decision Log")
    decision_count = int(state["summary"]["decision_count"] or 0)
    st.write(
        f"There are `{decision_count}` decision-log entries persisted so far. "
        "This append-only tab is already pointed at the real `decision_log` table."
    )
    if state["decisions"].empty:
        st.info("No decisions have been logged yet.")
    else:
        st.dataframe(state["decisions"], use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    database_url = get_database_url()
    schema_version = initialize_database(database_url)
    apply_shell_styles()
    render_import_panel(database_url)
    connection = st.connection("db", type="sql", url=database_url)
    state = read_shell_state(connection)
    summary = state["summary"]

    render_hero(schema_version, summary)
    render_signal_banners(state["active_signals"])

    summary_columns = st.columns(4)
    with summary_columns[0]:
        render_summary_card(
            "Portfolio Snapshot",
            str(int(summary["holding_count"] or 0)),
            metric_note(summary["latest_snapshot_date"]),
        )
    with summary_columns[1]:
        render_summary_card(
            "Tracked Value",
            f"GBP {float(summary['total_value'] or 0):,.0f}",
            "Aggregated from the latest persisted holdings snapshot",
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
        render_portfolio_tab(state)
    with signals_tab:
        render_signals_tab(state)
    with scenarios_tab:
        render_scenarios_tab(state)
    with decision_log_tab:
        render_decision_log_tab(state)


if __name__ == "__main__":
    main()
