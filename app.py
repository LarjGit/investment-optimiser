from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from investment_optimiser.boe import boe_handler
from investment_optimiser.db import initialize_database, sqlite_path_from_url
from investment_optimiser.dmo import dmo_handler
from investment_optimiser.gilt_analytics import gilt_analytics_handler
from investment_optimiser.lse_gilt_prices import lse_gilt_prices_handler
from investment_optimiser.non_gilt_reference import non_gilt_reference_handler
from investment_optimiser.tidm import tidm_handler
from investment_optimiser.portfolio_import import (
    IngestionError,
    import_ii_portfolio_snapshot,
)
from investment_optimiser.equity_signals import (
    DurationLiquiditySignal,
    ErpSignal,
    YieldCurveSignal,
    classify_curve_state,
    evaluate_duration_liquidity_signal,
    evaluate_erp_signal,
    evaluate_yield_curve_shape_signal,
)
from investment_optimiser.policy_pack import load_policy_pack
from investment_optimiser.portfolio_kpis import build_portfolio_kpis
from investment_optimiser.refresh import REFRESH_SOURCE_ORDER, RefreshCoordinator
from investment_optimiser.yfinance_equities import (
    NON_GILT_PRICE_ASSET_TYPES,
    to_yahoo_ticker,
    yfinance_equities_handler,
)


st.set_page_config(
    page_title="Investment Optimiser",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)


REFRESH_SOURCES = [
    source for source in REFRESH_SOURCE_ORDER if source != "blackrock_ftse_pe"
]
DEFAULT_DATABASE_URL = "sqlite:///data/investment_optimiser.db"
PORTFOLIO_UPLOAD_ERROR_KEY = "portfolio_upload_error"
PORTFOLIO_UPLOAD_FEEDBACK_KEY = "portfolio_upload_feedback"
REFRESH_FEEDBACK_KEY = "refresh_feedback"
REFRESH_WARNING_MESSAGES_KEY = "refresh_warning_messages"
PORTFOLIO_UPLOAD_WIDGET_KEY = "ii_csv_upload"
ERP_THRESHOLD_KEY = "erp_threshold_pct"
DURATION_FLOOR_KEY = "duration_floor_years"
DURATION_CEILING_KEY = "duration_ceiling_years"
LIQUIDITY_THRESHOLD_KEY = "liquidity_concentration_10y_plus_pct"


def _policy_field_default(key: str) -> object:
    pack = load_policy_pack()
    for field in pack.get("shared_assumption_schema", {}).get("fields", []):
        if field.get("key") == key:
            return field["default"]
    return None


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
    holdings_rows = enrich_holdings_with_latest_non_gilt_prices(
        connection,
        holdings_rows,
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
    gilt_ranking_rows = connection.query(
        """
        SELECT
            p.isin,
            r.instrument_name,
            p.maturity_date,
            p.coupon_pct,
            p.clean_price_gbp,
            p.gry_pct,
            p.modified_duration_years
        FROM gilt_price_cache p
        JOIN gilt_reference r ON r.isin = p.isin
        WHERE r.instrument_type = 'Conventional'
          AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
        ORDER BY p.gry_pct DESC NULLS LAST, p.maturity_date ASC
        """,
        ttl=60,
    )
    equity_valuation_rows = connection.query(
        """
        SELECT cache_date, pe_ratio
        FROM equity_valuation_cache
        WHERE source_name = 'yfinance_equities'
        ORDER BY cache_date DESC
        LIMIT 1
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

    equity_valuation: dict | None = None
    if not equity_valuation_rows.empty:
        row = equity_valuation_rows.iloc[0]
        equity_valuation = {
            "cache_date": row["cache_date"],
            "pe_ratio": row["pe_ratio"],
        }

    yield_curve_rows = connection.query(
        """
        SELECT
            MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) AS ten_year_pct,
            MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) AS twenty_year_pct,
            cache_date
        FROM yield_curve_cache
        WHERE cache_date = (
            SELECT MAX(cache_date) FROM yield_curve_cache WHERE curve_key = 'boe_10y'
        )
        GROUP BY cache_date
        """,
        ttl=60,
    )
    yield_curve_history_rows = connection.query(
        """
        SELECT
            cache_date,
            MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) AS ten_year_pct,
            MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) AS twenty_year_pct
        FROM yield_curve_cache
        WHERE curve_key IN ('boe_5y', 'boe_10y', 'boe_20y')
          AND cache_date >= date('now', '-40 days')
        GROUP BY cache_date
        HAVING MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) IS NOT NULL
        ORDER BY cache_date DESC
        """,
        ttl=60,
    )

    yield_curve: dict | None = None
    if not yield_curve_rows.empty:
        row = yield_curve_rows.iloc[0]
        if pd.notna(row["five_year_pct"]) and pd.notna(row["ten_year_pct"]) and pd.notna(row["twenty_year_pct"]):
            yield_curve = {
                "cache_date": row["cache_date"],
                "five_year_pct": float(row["five_year_pct"]),
                "ten_year_pct": float(row["ten_year_pct"]),
                "twenty_year_pct": float(row["twenty_year_pct"]),
            }

    yield_curve_history: list[tuple[str, str]] = []
    for _, row in yield_curve_history_rows.iterrows():
        if pd.notna(row["five_year_pct"]) and pd.notna(row["ten_year_pct"]) and pd.notna(row["twenty_year_pct"]):
            curve_state = classify_curve_state(
                float(row["five_year_pct"]),
                float(row["ten_year_pct"]),
                float(row["twenty_year_pct"]),
            )
            yield_curve_history.append((row["cache_date"], curve_state))

    duration_liquidity_rows = connection.query(
        """
        SELECT
            ps.isin,
            ps.market_value_gbp,
            gpc.modified_duration_years,
            gpc.maturity_date
        FROM portfolio_snapshots ps
        LEFT JOIN gilt_price_cache gpc
            ON gpc.isin = ps.isin
            AND gpc.cache_date = (
                SELECT MAX(cache_date) FROM gilt_price_cache WHERE isin = ps.isin
            )
        WHERE ps.snapshot_date = (SELECT MAX(snapshot_date) FROM portfolio_snapshots)
          AND ps.asset_type IN ('gilt_conventional', 'gilt_index_linked')
          AND ps.isin IS NOT NULL
        """,
        ttl=60,
    )

    return {
        "summary": summary_row,
        "active_signals": active_signal_rows,
        "holdings": holdings_rows,
        "decisions": decision_rows,
        "refresh_state": refresh_state,
        "gilt_ranking": gilt_ranking_rows,
        "equity_valuation": equity_valuation,
        "yield_curve": yield_curve,
        "yield_curve_history": yield_curve_history,
        "duration_liquidity_rows": duration_liquidity_rows,
    }


def enrich_holdings_with_latest_non_gilt_prices(
    connection: Any,
    holdings_rows: pd.DataFrame,
) -> pd.DataFrame:
    if holdings_rows.empty:
        return holdings_rows

    holdings_frame = holdings_rows.copy()

    non_gilt_mask = holdings_frame["asset_type"].isin(NON_GILT_PRICE_ASSET_TYPES)
    if not non_gilt_mask.any():
        return _add_empty_refreshed_price_columns(holdings_frame)

    latest_price_rows = connection.query(
        """
        WITH ranked_prices AS (
            SELECT
                ticker,
                cache_date,
                close_price_gbp,
                ROW_NUMBER() OVER (
                    PARTITION BY ticker
                    ORDER BY cache_date DESC, fetched_at DESC
                ) AS row_number
            FROM equity_price_cache
        )
        SELECT ticker, cache_date, close_price_gbp
        FROM ranked_prices
        WHERE row_number = 1
        """,
        ttl=60,
    )
    if latest_price_rows.empty:
        return _add_empty_refreshed_price_columns(holdings_frame)

    holdings_frame["yahoo_ticker"] = None
    holdings_frame.loc[non_gilt_mask, "yahoo_ticker"] = holdings_frame.loc[
        non_gilt_mask, "symbol"
    ].map(to_yahoo_ticker)

    enriched_frame = holdings_frame.merge(
        latest_price_rows.rename(
            columns={
                "ticker": "yahoo_ticker",
                "cache_date": "refreshed_price_date",
                "close_price_gbp": "refreshed_price_gbp",
            }
        ),
        on="yahoo_ticker",
        how="left",
    )
    enriched_frame["refreshed_market_value_gbp"] = (
        enriched_frame["refreshed_price_gbp"] * enriched_frame["quantity"]
    )
    for column_name in (
        "refreshed_price_gbp",
        "refreshed_market_value_gbp",
        "refreshed_price_date",
    ):
        enriched_frame[column_name] = enriched_frame[column_name].where(
            pd.notna(enriched_frame[column_name]),
            None,
        )

    return enriched_frame.drop(columns=["yahoo_ticker"], errors="ignore")


def _add_empty_refreshed_price_columns(holdings_frame: pd.DataFrame) -> pd.DataFrame:
    holdings_frame["refreshed_price_gbp"] = None
    holdings_frame["refreshed_market_value_gbp"] = None
    holdings_frame["refreshed_price_date"] = None
    return holdings_frame


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
                    "gilt_analytics": gilt_analytics_handler,
                    "yfinance_equities": yfinance_equities_handler,
                },
            )
            result = coordinator.run_refresh(
                database_url,
                snapshot_date=date.today().isoformat(),
                sources=REFRESH_SOURCES,
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
        st.divider()
        st.caption("Equity Signal")
        benchmark_ticker = _policy_field_default("benchmark_ticker") or "SWRD.L"
        st.caption(f"Benchmark: {benchmark_ticker}")
        if ERP_THRESHOLD_KEY not in st.session_state:
            st.session_state[ERP_THRESHOLD_KEY] = float(
                _policy_field_default("erp_threshold_pct") or 0.0
            )
        st.number_input(
            "ERP warning threshold (%)",
            min_value=-5.0,
            max_value=5.0,
            step=0.25,
            key=ERP_THRESHOLD_KEY,
            help="ERP below this level triggers the warning banner.",
        )
        st.divider()
        st.caption("Duration & Liquidity")
        if DURATION_FLOOR_KEY not in st.session_state:
            st.session_state[DURATION_FLOOR_KEY] = float(
                _policy_field_default("duration_floor_years") or 2.0
            )
        if DURATION_CEILING_KEY not in st.session_state:
            st.session_state[DURATION_CEILING_KEY] = float(
                _policy_field_default("duration_ceiling_years") or 8.0
            )
        if LIQUIDITY_THRESHOLD_KEY not in st.session_state:
            st.session_state[LIQUIDITY_THRESHOLD_KEY] = float(
                _policy_field_default("liquidity_concentration_10y_plus_pct") or 35.0
            )
        st.number_input(
            "Duration floor (years)",
            min_value=0.0,
            max_value=30.0,
            step=0.5,
            key=DURATION_FLOOR_KEY,
            help="Alert if weighted-average gilt duration falls below this.",
        )
        st.number_input(
            "Duration ceiling (years)",
            min_value=0.0,
            max_value=30.0,
            step=0.5,
            key=DURATION_CEILING_KEY,
            help="Alert if weighted-average gilt duration exceeds this.",
        )
        st.number_input(
            "10y+ concentration limit (%)",
            min_value=0.0,
            max_value=100.0,
            step=5.0,
            key=LIQUIDITY_THRESHOLD_KEY,
            help="Alert if gilt value maturing beyond 10 years exceeds this share.",
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
    st.caption(
        "Snapshot values come from the imported broker CSV. Refreshed non-gilt prices "
        "and values are overlaid from the persisted Yahoo cache when available."
    )

    portfolio_kpis = build_portfolio_kpis(
        holdings_frame.to_dict("records"),
        summary["latest_snapshot_date"],
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Current Portfolio Value",
        f"GBP {portfolio_kpis.current_total_value_gbp:,.0f}",
        border=False,
    )
    metric_columns[1].metric(
        "Snapshot Portfolio Value",
        f"GBP {portfolio_kpis.snapshot_total_value_gbp:,.0f}",
        border=False,
    )
    metric_columns[2].metric(
        "Holdings",
        str(portfolio_kpis.holding_count),
        border=False,
    )
    metric_columns[3].metric(
        "Cash & MMF Share",
        f"{portfolio_kpis.mmf_weight_pct:.1f}%",
        border=False,
    )

    display_frame = holdings_frame.drop(
        columns=["snapshot_date", "refreshed_price_gbp"], errors="ignore"
    )
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
            "market_value_gbp": st.column_config.NumberColumn("Snapshot Value", format="£%,.2f"),
            "weight_pct": st.column_config.NumberColumn("Weight %", format="%.2f%%"),
            "refreshed_price_date": st.column_config.TextColumn("Refresh Date"),
            "refreshed_market_value_gbp": st.column_config.NumberColumn("Current Value", format="£%,.2f"),
        },
    )


def render_gilt_ranking_card(df: pd.DataFrame) -> None:
    st.subheader("Conventional Gilt Ranking")
    if df.empty:
        st.info(
            "No conventional gilt prices available yet. "
            "Run a market data refresh to populate the ranking."
        )
        return

    if df["gry_pct"].isna().all():
        st.warning(
            "Gilt prices are loaded but analytics (GRY and modified duration) "
            "have not been computed yet. Run a market data refresh to complete the ranking."
        )
        st.dataframe(
            df[["isin", "instrument_name", "maturity_date", "coupon_pct", "clean_price_gbp"]],
            width="stretch",
            hide_index=True,
            column_config={
                "isin": st.column_config.TextColumn("ISIN"),
                "instrument_name": st.column_config.TextColumn("Name"),
                "maturity_date": st.column_config.TextColumn("Maturity"),
                "coupon_pct": st.column_config.NumberColumn("Coupon %", format="%.2f%%"),
                "clean_price_gbp": st.column_config.NumberColumn("Clean Price", format="%.4f"),
            },
        )
        return

    best_gry = df["gry_pct"].max()
    lowest_duration = df["modified_duration_years"].min()
    gilt_count = len(df)

    col1, col2, col3 = st.columns(3)
    col1.metric("Best GRY", f"{best_gry * 100:.2f}%")
    col2.metric("Lowest Duration", f"{lowest_duration:.2f} yrs" if pd.notna(lowest_duration) else "—")
    col3.metric("Gilts in Snapshot", str(gilt_count))

    display_df = df.assign(gry_pct=df["gry_pct"] * 100)
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "isin": st.column_config.TextColumn("ISIN"),
            "instrument_name": st.column_config.TextColumn("Name"),
            "maturity_date": st.column_config.TextColumn("Maturity"),
            "coupon_pct": st.column_config.NumberColumn("Coupon %", format="%.2f%%"),
            "clean_price_gbp": st.column_config.NumberColumn("Clean Price", format="%.4f"),
            "gry_pct": st.column_config.NumberColumn("GRY %", format="%.2f%%"),
            "modified_duration_years": st.column_config.NumberColumn("Mod. Duration", format="%.2f"),
        },
    )
    st.caption("Ranked by GRY descending. Interactive re-sorting may reorder rows with missing analytics.")


def render_equity_macro_signal_card(
    equity_valuation: dict | None,
    gilt_ranking: pd.DataFrame,
    erp_threshold_pct: float,
) -> None:
    st.subheader("Equity Risk Premium Signal")

    pe_ratio: float | None = None
    cache_date: str | None = None
    if equity_valuation is not None:
        pe_ratio = equity_valuation.get("pe_ratio")
        cache_date = equity_valuation.get("cache_date")

    best_gry: float | None = None
    if not gilt_ranking.empty and "gry_pct" in gilt_ranking.columns:
        gry_series = gilt_ranking["gry_pct"].dropna()
        if not gry_series.empty:
            best_gry = float(gry_series.max())

    signal = evaluate_erp_signal(
        pe_ratio=pe_ratio,
        best_gry=best_gry,
        cache_date=cache_date,
        erp_threshold_pct=erp_threshold_pct,
    )

    col1, col2, col3 = st.columns(3)
    if signal.state == "unavailable":
        col1.metric("ERP", "—")
        col2.metric("Earnings yield", "—")
        col3.metric("Best gilt GRY", f"{best_gry * 100:.2f}%" if best_gry is not None else "—")
        st.error(signal.explanation)
        return

    col1.metric(
        "ERP",
        f"{signal.erp_pct:+.2f}%",
        delta=f"{signal.erp_pct - erp_threshold_pct:+.2f}% vs threshold",
        delta_color="normal",
    )
    col2.metric("Earnings yield", f"{signal.earnings_yield_pct:.2f}%")
    col3.metric("Best gilt GRY", f"{signal.best_gilt_gry_pct:.2f}%")

    if signal.state in ("stale", "warning"):
        st.warning(signal.explanation)
    else:
        st.info(signal.explanation)


def render_yield_curve_shape_signal_card(
    yield_curve: dict | None,
    yield_curve_history: list[tuple[str, str]],
) -> None:
    st.subheader("Yield Curve Shape Signal")

    five_y: float | None = yield_curve.get("five_year_pct") if yield_curve else None
    ten_y: float | None = yield_curve.get("ten_year_pct") if yield_curve else None
    twenty_y: float | None = yield_curve.get("twenty_year_pct") if yield_curve else None
    cache_date: str | None = yield_curve.get("cache_date") if yield_curve else None

    signal = evaluate_yield_curve_shape_signal(
        five_y=five_y,
        ten_y=ten_y,
        twenty_y=twenty_y,
        cache_date=cache_date,
        history=yield_curve_history,
    )

    col1, col2, col3, col4 = st.columns(4)

    if signal.state == "unavailable":
        col1.metric("5y yield", "—")
        col2.metric("10y yield", "—")
        col3.metric("20y yield", "—")
        col4.metric("10y−5y spread", "—")
        st.error(signal.explanation)
        return

    col1.metric("5y yield", f"{signal.five_year_pct:.2f}%")
    col2.metric("10y yield", f"{signal.ten_year_pct:.2f}%")
    col3.metric("20y yield", f"{signal.twenty_year_pct:.2f}%")
    col4.metric("10y−5y spread", f"{signal.spread_bps:+.0f}bps")

    curve_label = signal.curve_state.capitalize() if signal.curve_state else "—"
    days_str = f"{signal.consecutive_days} consecutive UK business days" if signal.consecutive_days is not None else "—"
    st.caption(f"Shape: **{curve_label}** · {days_str}")

    if signal.state in ("warning", "stale"):
        st.warning(signal.explanation)
    else:
        st.info(signal.explanation)

    with st.expander("About this signal"):
        st.write(
            "Uses the 10y−5y nominal par yield spread from Bank of England IADB data "
            "(series IUDMNPY and IUDSNPY). The design target is the 10y−2y spread, but "
            "the BoE IADB does not publish a 2-year series. "
            "Classification: Normal (spread >+10bps), Inverted (<−10bps), "
            "Flat (within ±10bps), Humped (10y above both 5y and 20y by >10bps). "
            "A warning fires only after the non-normal shape has held for "
            "5 consecutive UK business days."
        )


def render_duration_liquidity_signal_card(
    duration_liquidity_rows: pd.DataFrame,
    floor: float,
    ceiling: float,
    liquidity_threshold: float,
) -> None:
    st.subheader("Duration & Liquidity Alert")

    rows = duration_liquidity_rows.to_dict("records") if not duration_liquidity_rows.empty else []

    signal = evaluate_duration_liquidity_signal(
        rows=rows, floor=floor, ceiling=ceiling, liquidity_threshold=liquidity_threshold
    )

    col1, col2, col3 = st.columns(3)

    if signal.state == "unavailable":
        col1.metric("Avg duration", "—")
        col2.metric("10y+ concentration", "—")
        col3.metric("Gilt holdings", "0")
        st.error(signal.explanation)
        return

    col3.metric("Gilt holdings", str(signal.gilt_count))

    if signal.state == "degraded":
        col1.metric("Avg duration", "—")
        col2.metric("10y+ concentration", "—")
        st.warning(signal.explanation)
        return

    mid = (floor + ceiling) / 2
    col1.metric(
        "Avg duration",
        f"{signal.avg_duration_years:.2f}y",
        delta=f"{signal.avg_duration_years - mid:+.2f}y vs midpoint",
        delta_color="off",
    )
    col2.metric(
        "10y+ concentration",
        f"{signal.concentration_10y_plus_pct:.1f}%",
        delta=f"limit {liquidity_threshold:.0f}%",
        delta_color="off",
    )

    if signal.state == "triggered":
        st.warning(signal.explanation)
    else:
        st.info(signal.explanation)


def render_signals_tab(state: dict[str, Any]) -> None:
    st.subheader("Signals")
    render_gilt_ranking_card(state["gilt_ranking"])
    st.divider()
    erp_threshold_pct = float(st.session_state.get(ERP_THRESHOLD_KEY, 0.0))
    render_equity_macro_signal_card(
        equity_valuation=state.get("equity_valuation"),
        gilt_ranking=state["gilt_ranking"],
        erp_threshold_pct=erp_threshold_pct,
    )
    st.divider()
    render_yield_curve_shape_signal_card(
        yield_curve=state.get("yield_curve"),
        yield_curve_history=state.get("yield_curve_history", []),
    )
    st.divider()
    render_duration_liquidity_signal_card(
        duration_liquidity_rows=state.get("duration_liquidity_rows", pd.DataFrame()),
        floor=float(st.session_state.get(DURATION_FLOOR_KEY, 2.0)),
        ceiling=float(st.session_state.get(DURATION_CEILING_KEY, 8.0)),
        liquidity_threshold=float(st.session_state.get(LIQUIDITY_THRESHOLD_KEY, 35.0)),
    )
    st.divider()
    active_signal_count = int(state["summary"]["active_signal_count"] or 0)
    st.write(
        f"There are currently `{active_signal_count}` active persisted alert episodes."
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
