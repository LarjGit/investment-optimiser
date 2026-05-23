from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from investment_optimiser.boe import boe_handler
from functools import partial

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
    EquityOpportunitySignal,
    ErpSignal,
    YieldCurveSignal,
    classify_curve_state,
    evaluate_duration_liquidity_signal,
    evaluate_equity_opportunity_signal,
    evaluate_erp_signal,
    evaluate_yield_curve_shape_signal,
)
from investment_optimiser.decision_log import insert_decision
from investment_optimiser.policy_pack import load_policy_pack
from investment_optimiser.strategic_baseline import (
    BaselineRecord,
    insert_baseline,
)
from investment_optimiser.allocation_view import build_allocation_table, enrich_with_buckets, style_allocation_table
from investment_optimiser.allocation_runs import insert_allocation_run
from investment_optimiser.cash_allocator import build_cash_run_record, compute_cash_deployment
from investment_optimiser.lp_recommendation import build_lp_recommendation
from investment_optimiser.scenario_comparison import (
    build_coverage_summary,
    build_scenario_comparison_df,
    compute_scenario_totals,
)
from investment_optimiser.recommendation_change_summary import (
    build_allocation_change_df,
    build_headline_metrics,
)
from investment_optimiser.blocked_trade_display import (
    categorise_blocked_trades,
    RISK_OUTCOME_LABELS,
    RISK_PASS_OUTCOMES,
)
from investment_optimiser.narrative_explanation import build_narrative_components
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
RPI_ASSUMPTION_KEY = "expected_rpi_pct"
DURATION_FLOOR_KEY = "duration_floor_years"
DURATION_CEILING_KEY = "duration_ceiling_years"
LIQUIDITY_THRESHOLD_KEY = "liquidity_concentration_10y_plus_pct"
BASELINE_EDITING_KEY = "baseline_editing"
BASELINE_EDITOR_KEY_COUNTER = "baseline_editor_key_counter"


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
        SELECT id, alert_type, severity, message, started_at
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
            snapshot_date,
            isin
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
    holdings_rows = enrich_holdings_with_maturity_years(connection, holdings_rows)
    decision_rows = connection.query(
        """
        SELECT id, decision_date, action, instruments_affected, notes, signal_event_id, created_at
        FROM decision_log
        ORDER BY created_at DESC
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
            r.instrument_type,
            p.maturity_date,
            p.coupon_pct,
            p.clean_price_gbp,
            p.gry_pct,
            p.real_gry_pct,
            p.nominal_equivalent_gry_pct,
            p.modified_duration_years
        FROM gilt_price_cache p
        JOIN gilt_reference r ON r.isin = p.isin
        WHERE p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
        ORDER BY p.maturity_date ASC
        """,
        ttl=60,
    )
    gilt_ref_count_rows = connection.query(
        "SELECT COUNT(*) AS total FROM gilt_reference WHERE instrument_type = 'Conventional'",
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
            MAX(CASE WHEN curve_key = 'lse_derived_2y'  THEN rate_pct END) AS two_year_pct,
            MAX(CASE WHEN curve_key = 'lse_derived_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'lse_derived_10y' THEN rate_pct END) AS ten_year_pct,
            cache_date
        FROM yield_curve_cache
        WHERE cache_date = (
            SELECT MAX(cache_date) FROM yield_curve_cache WHERE curve_key = 'lse_derived_2y'
        )
        GROUP BY cache_date
        """,
        ttl=60,
    )
    yield_curve_history_rows = connection.query(
        """
        SELECT
            cache_date,
            MAX(CASE WHEN curve_key = 'lse_derived_2y'  THEN rate_pct END) AS two_year_pct,
            MAX(CASE WHEN curve_key = 'lse_derived_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'lse_derived_10y' THEN rate_pct END) AS ten_year_pct
        FROM yield_curve_cache
        WHERE curve_key IN ('lse_derived_2y', 'lse_derived_5y', 'lse_derived_10y')
          AND cache_date >= date('now', '-40 days')
        GROUP BY cache_date
        HAVING MAX(CASE WHEN curve_key = 'lse_derived_2y'  THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'lse_derived_5y'  THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'lse_derived_10y' THEN rate_pct END) IS NOT NULL
        ORDER BY cache_date DESC
        """,
        ttl=60,
    )

    yield_curve: dict | None = None
    if not yield_curve_rows.empty:
        row = yield_curve_rows.iloc[0]
        if pd.notna(row["two_year_pct"]) and pd.notna(row["five_year_pct"]) and pd.notna(row["ten_year_pct"]):
            yield_curve = {
                "cache_date": row["cache_date"],
                "two_year_pct": float(row["two_year_pct"]),
                "five_year_pct": float(row["five_year_pct"]),
                "ten_year_pct": float(row["ten_year_pct"]),
            }

    yield_curve_history: list[tuple[str, str]] = []
    for _, row in yield_curve_history_rows.iterrows():
        if pd.notna(row["two_year_pct"]) and pd.notna(row["five_year_pct"]) and pd.notna(row["ten_year_pct"]):
            curve_state = classify_curve_state(
                float(row["two_year_pct"]),
                float(row["five_year_pct"]),
                float(row["ten_year_pct"]),
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

    baseline_rows = connection.query(
        """
        SELECT created_at, label, policy_version, weights_json, notes
        FROM strategic_baseline
        ORDER BY id DESC
        LIMIT 1
        """,
        ttl=60,
    )
    current_baseline: BaselineRecord | None = None
    if not baseline_rows.empty:
        row = baseline_rows.iloc[0]
        current_baseline = BaselineRecord(
            created_at=row["created_at"],
            label=row["label"],
            policy_version=row["policy_version"],
            weights=json.loads(row["weights_json"]),
            notes=row["notes"] if pd.notna(row["notes"]) else None,
        )

    gilt_candidate_warnings = _build_gilt_candidate_warnings(gilt_ranking_rows, gilt_ref_count_rows)

    return {
        "summary": summary_row,
        "active_signals": active_signal_rows,
        "holdings": holdings_rows,
        "decisions": decision_rows,
        "refresh_state": refresh_state,
        "gilt_ranking": gilt_ranking_rows,
        "gilt_candidate_warnings": gilt_candidate_warnings,
        "equity_valuation": equity_valuation,
        "yield_curve": yield_curve,
        "yield_curve_history": yield_curve_history,
        "duration_liquidity_rows": duration_liquidity_rows,
        "current_baseline": current_baseline,
    }


def _build_gilt_candidate_warnings(
    gilt_ranking: pd.DataFrame,
    gilt_ref_count: pd.DataFrame,
) -> list[str]:
    warnings: list[str] = []
    total_ref = int(gilt_ref_count.iloc[0]["total"]) if not gilt_ref_count.empty else 0
    conventional = (
        gilt_ranking[gilt_ranking["instrument_type"] == "Conventional"]
        if "instrument_type" in gilt_ranking.columns
        else gilt_ranking
    )
    unpriced_count = max(0, total_ref - len(conventional))
    if unpriced_count:
        warnings.append(
            f"{unpriced_count} gilt(s) have no current price in the market snapshot"
        )
    no_analytics = int(conventional["gry_pct"].isna().sum())
    if no_analytics:
        warnings.append(
            f"{no_analytics} gilt(s) have a price but missing GRY analytics"
            " — analytics refresh may be needed"
        )
    return warnings


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
                    ORDER BY fetched_at DESC, cache_date DESC
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


def enrich_holdings_with_maturity_years(
    connection: Any,
    holdings_frame: pd.DataFrame,
) -> pd.DataFrame:
    if holdings_frame.empty:
        return holdings_frame.assign(maturity_years=None)
    has_gilts = holdings_frame["asset_type"].isin({"gilt_conventional", "gilt_index_linked"}).any()
    if not has_gilts:
        return holdings_frame.assign(maturity_years=None)
    maturity_rows = connection.query(
        "SELECT isin, maturity_date FROM gilt_reference",
        ttl=3600,
    )
    if maturity_rows.empty:
        return holdings_frame.assign(maturity_years=None)
    today = pd.Timestamp.today().normalize()
    maturity_rows["maturity_years"] = (
        pd.to_datetime(maturity_rows["maturity_date"]) - today
    ).dt.days / 365.25
    return holdings_frame.merge(
        maturity_rows[["isin", "maturity_years"]], on="isin", how="left"
    )


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
                    "gilt_analytics": partial(
                        gilt_analytics_handler,
                        rpi_assumption_pct=float(st.session_state.get(RPI_ASSUMPTION_KEY, 0.0)) or None,
                    ),
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
        st.caption("Index-Linked Gilts")
        if RPI_ASSUMPTION_KEY not in st.session_state:
            st.session_state[RPI_ASSUMPTION_KEY] = float(
                _policy_field_default("expected_rpi_pct") or 3.0
            )
        st.number_input(
            "RPI assumption (%)",
            min_value=0.0,
            max_value=15.0,
            step=0.25,
            key=RPI_ASSUMPTION_KEY,
            help=(
                "Assumed annual RPI inflation used to compute IL gilt real GRY and "
                "nominal-equivalent yield for comparison with conventional gilts. "
                "Set to 0 to exclude IL gilts from yield ranking and optimisation."
            ),
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


def _render_allocation_vs_baseline(
    holdings_frame: pd.DataFrame,
    current_baseline: Any,
) -> None:
    st.subheader("Allocation vs Baseline")
    if current_baseline is None:
        st.info("No baseline set. Add one in the Scenarios tab.")
        return

    pack = load_policy_pack()
    buckets = pack["baseline_bucket_model"]["buckets"]
    bucket_labels = {b["id"]: b["label"] for b in buckets}

    alloc = build_allocation_table(holdings_frame, current_baseline.weights, bucket_labels)
    display = alloc[["label", "current_pct", "baseline_pct", "drift_pct"]].rename(
        columns={"label": "Bucket", "current_pct": "Current %", "baseline_pct": "Baseline %", "drift_pct": "Drift %"}
    )
    styled = (
        style_allocation_table(display)
        .format({"Current %": "{:.1f}", "Baseline %": "{:.1f}", "Drift %": "{:+.1f}"})
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    uncertain_buckets = alloc[alloc["uncertain"] == True]
    if not uncertain_buckets.empty:
        enriched = enrich_with_buckets(holdings_frame)
        uncertain_rows = enriched[enriched["resolution_method"].isin({"name_keywords", "catch_all"})]
        st.caption(
            "⚠ Some holdings were classified by name-keyword matching or fell to the catch-all bucket. "
            "Use symbol overrides in the code to correct any misclassifications."
        )
        with st.expander("Holdings with uncertain bucket classification"):
            st.dataframe(
                uncertain_rows[["symbol", "instrument_name", "asset_type", "bucket_id", "resolution_method"]].rename(
                    columns={"bucket_id": "Assigned bucket", "resolution_method": "Method"}
                ),
                hide_index=True,
                use_container_width=True,
            )

    st.divider()


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

    _render_allocation_vs_baseline(holdings_frame, state.get("current_baseline"))

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


def render_gilt_ranking_card(
    df: pd.DataFrame,
    warnings: list[str] | None = None,
    holdings_df: pd.DataFrame | None = None,
) -> None:
    rpi_assumption = float(st.session_state.get(RPI_ASSUMPTION_KEY, 0.0))

    if "instrument_type" in df.columns:
        il_df = df[df["instrument_type"] == "Index-linked"]
        df = df[df["instrument_type"] == "Conventional"].copy()
    else:
        il_df = pd.DataFrame()

    st.subheader("Gilt Ranking")
    for w in warnings or []:
        st.warning(w)
    if df.empty:
        st.info(
            "No conventional gilt prices available yet. "
            "Run a market data refresh to populate the ranking."
        )
        return

    # Build the display DataFrame: conventional by gry_pct; IL by nominal_equivalent_gry_pct
    if rpi_assumption and not il_df.empty:
        il_with_analytics = il_df[il_df["nominal_equivalent_gry_pct"].notna()].copy()
        if not il_with_analytics.empty:
            il_with_analytics = il_with_analytics.assign(
                gry_pct=il_with_analytics["nominal_equivalent_gry_pct"]
            )
            df = pd.concat([df, il_with_analytics], ignore_index=True)

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

    df = df.sort_values("gry_pct", ascending=False, na_position="last").reset_index(drop=True)

    # Mark held gilts by ISIN
    held_isins: set[str] = set()
    if holdings_df is not None and not holdings_df.empty and "isin" in holdings_df.columns:
        gilt_holdings = holdings_df[
            holdings_df["asset_type"].isin({"gilt_conventional", "gilt_index_linked"})
        ]
        held_isins = set(gilt_holdings["isin"].dropna().tolist())
    df["held"] = df["isin"].isin(held_isins)

    best_gry = df["gry_pct"].max()
    lowest_duration = df["modified_duration_years"].min()
    gilt_count = len(df)

    # Switch banner: compare best market GRY to best held GRY
    if held_isins:
        held_rows = df[df["held"]]
        if not held_rows.empty and held_rows["gry_pct"].notna().any():
            best_held_gry = held_rows["gry_pct"].max()
            switch_threshold = 0.001  # 10 bps
            gap = best_gry - best_held_gry
            if gap > switch_threshold:
                best_market_gilt = df.iloc[0]["instrument_name"]
                st.warning(
                    f"Switch opportunity: **{best_market_gilt}** yields "
                    f"**{best_gry * 100:.2f}%** vs your best held gilt at "
                    f"**{best_held_gry * 100:.2f}%** — a gap of **{gap * 100:.2f}%** "
                    f"({gap * 10000:.0f}bps). See the Scenarios tab to run a full trade recommendation."
                )
            else:
                st.success(
                    f"Your best held gilt ({best_held_gry * 100:.2f}% GRY) is within "
                    f"{gap * 10000:.0f}bps of the market's best available gilt. No switch needed."
                )

    col1, col2, col3 = st.columns(3)
    col1.metric("Best GRY", f"{best_gry * 100:.2f}%")
    col2.metric("Lowest Duration", f"{lowest_duration:.2f} yrs" if pd.notna(lowest_duration) else "—")
    col3.metric("Gilts in Snapshot", str(gilt_count))

    display_cols = ["held", "isin", "instrument_name", "maturity_date", "coupon_pct", "clean_price_gbp", "gry_pct", "modified_duration_years"]
    display_df = df[[c for c in display_cols if c in df.columns]].assign(gry_pct=df["gry_pct"] * 100)
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "held": st.column_config.CheckboxColumn("Held", help="You currently hold this gilt"),
            "isin": st.column_config.TextColumn("ISIN"),
            "instrument_name": st.column_config.TextColumn("Name"),
            "maturity_date": st.column_config.TextColumn("Maturity"),
            "coupon_pct": st.column_config.NumberColumn("Coupon %", format="%.2f%%"),
            "clean_price_gbp": st.column_config.NumberColumn("Clean Price", format="%.4f"),
            "gry_pct": st.column_config.NumberColumn("GRY %", format="%.2f%%"),
            "modified_duration_years": st.column_config.NumberColumn("Mod. Duration", format="%.2f"),
        },
    )

    il_held = not il_df.empty
    if rpi_assumption and il_held:
        neq_col = "nominal_equivalent_gry_pct"
        il_uncomputed = int(il_df[neq_col].isna().sum()) if neq_col in il_df.columns else len(il_df)
        if il_uncomputed:
            st.info(
                f"{il_uncomputed} index-linked gilt(s) are held but have no computed real GRY yet. "
                "Run a market data refresh to include them in the ranking."
            )
    elif il_held and not rpi_assumption:
        il_count = len(il_df)
        st.info(
            f"{il_count} index-linked gilt(s) are excluded from this ranking because no RPI assumption "
            "is set. Set an RPI assumption in the sidebar to include them in yield comparison and optimisation."
        )
    st.caption("Ranked by GRY descending. IL gilts use nominal-equivalent GRY at the assumed RPI. Held = currently in your portfolio.")


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

    two_y: float | None = yield_curve.get("two_year_pct") if yield_curve else None
    five_y: float | None = yield_curve.get("five_year_pct") if yield_curve else None
    ten_y: float | None = yield_curve.get("ten_year_pct") if yield_curve else None
    cache_date: str | None = yield_curve.get("cache_date") if yield_curve else None

    signal = evaluate_yield_curve_shape_signal(
        two_y=two_y,
        five_y=five_y,
        ten_y=ten_y,
        cache_date=cache_date,
        history=yield_curve_history,
    )

    col1, col2, col3, col4 = st.columns(4)

    if signal.state == "unavailable":
        col1.metric("2y yield", "—")
        col2.metric("5y yield", "—")
        col3.metric("10y yield", "—")
        col4.metric("10y−2y spread", "—")
        st.error(signal.explanation)
        return

    col1.metric("2y yield", f"{signal.two_year_pct:.2f}%")
    col2.metric("5y yield", f"{signal.five_year_pct:.2f}%")
    col3.metric("10y yield", f"{signal.ten_year_pct:.2f}%")
    col4.metric("10y−2y spread", f"{signal.spread_bps:+.0f}bps")

    curve_label = signal.curve_state.capitalize() if signal.curve_state else "—"
    days_str = f"{signal.consecutive_days} consecutive UK business days" if signal.consecutive_days is not None else "—"
    st.caption(f"Shape: **{curve_label}** · {days_str}")

    if signal.state in ("warning", "stale"):
        st.warning(signal.explanation)
    else:
        st.info(signal.explanation)

    with st.expander("About this signal"):
        st.write(
            "Uses the 10y−2y nominal yield spread derived from LSE gilt prices. "
            "2y, 5y, and 10y benchmark yields are each taken from the nearest-maturity "
            "conventional gilt in the daily LSE price feed. "
            "Classification: Normal (10y−2y spread >+10bps), Inverted (<−10bps), "
            "Flat (within ±10bps), Humped (5y above both 2y and 10y by >10bps). "
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


def render_equity_opportunity_signal_card(conn: sqlite3.Connection, benchmark_ticker: str) -> None:
    st.subheader("Global Equity Opportunity")

    signal = evaluate_equity_opportunity_signal(conn, benchmark_ticker)

    if signal.state == "unavailable":
        col1, col2, col3 = st.columns(3)
        col1.metric("Opportunity score", "—")
        col2.metric("Components", "0 / 3")
        col3.metric("Trend", "—")
        st.error(signal.explanation)
        return

    band_labels = {
        "highly_attractive": "Highly attractive",
        "attractive": "Attractive",
        "modest": "Modest",
        "neutral": "Neutral",
    }
    score_pct = f"{signal.composite_score * 100:.0f} / 100"
    band_label = band_labels[signal.state]
    trend_str = (
        f"Dampened ({signal.trend_dampener:.0%})" if signal.trend_dampener is not None and signal.trend_dampener < 1.0
        else "Undampened"
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Opportunity score", score_pct, delta=band_label, delta_color="off")
    col2.metric(
        "Components",
        f"{signal.components_available} / 3",
        delta="degraded" if signal.is_degraded else None,
        delta_color="inverse" if signal.is_degraded else "off",
    )
    col3.metric("Trend", trend_str)

    with st.expander("Component detail", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "ERP percentile",
            f"{signal.erp_component * 100:.0f}th" if signal.erp_component is not None else "—",
        )
        c2.metric(
            "Valuation percentile",
            f"{signal.valuation_component * 100:.0f}th" if signal.valuation_component is not None else "—",
        )
        c3.metric(
            "Drawdown percentile",
            f"{signal.drawdown_component * 100:.0f}th" if signal.drawdown_component is not None else "—",
        )

    if signal.state in ("attractive", "highly_attractive"):
        st.info(signal.explanation)
    elif signal.is_degraded:
        st.warning(signal.explanation)
    else:
        st.info(signal.explanation)

    with st.expander("About this signal"):
        st.write(
            "Composite score (0–100) ranking current conditions against history across three factors: "
            "equity risk premium vs gilts, global equity valuation level (earnings yield percentile), "
            "and market drawdown from 52-week high. "
            "Scores are expanding percentile ranks — they reflect where conditions sit relative to "
            "all readings since the app first ran. "
            "A 50/200-day EMA trend dampener scales the score down to 75% during persistent bear markets. "
            "The score is informational only and does not change the baseline allocation."
        )


def _build_lp_gilt_ranking(gilt_ranking: pd.DataFrame) -> pd.DataFrame:
    """Return gilt ranking for LP: conventional always; IL only when RPI set and analytics present."""
    rpi_assumption = float(st.session_state.get(RPI_ASSUMPTION_KEY, 0.0))

    if "instrument_type" not in gilt_ranking.columns:
        return gilt_ranking

    conventional = gilt_ranking[gilt_ranking["instrument_type"] == "Conventional"].copy()
    if not rpi_assumption:
        return conventional

    if "nominal_equivalent_gry_pct" not in gilt_ranking.columns:
        return conventional

    il = gilt_ranking[
        (gilt_ranking["instrument_type"] == "Index-linked")
        & gilt_ranking["nominal_equivalent_gry_pct"].notna()
    ].copy()
    il["gry_pct"] = il["nominal_equivalent_gry_pct"]

    return pd.concat([conventional, il], ignore_index=True)


def render_signals_tab(state: dict[str, Any], database_url: str) -> None:
    st.subheader("Signals")
    render_gilt_ranking_card(
        state["gilt_ranking"],
        warnings=state.get("gilt_candidate_warnings"),
        holdings_df=state.get("holdings"),
    )
    st.divider()
    erp_threshold_pct = float(st.session_state.get(ERP_THRESHOLD_KEY, 0.0))
    render_equity_macro_signal_card(
        equity_valuation=state.get("equity_valuation"),
        gilt_ranking=state["gilt_ranking"],
        erp_threshold_pct=erp_threshold_pct,
    )
    st.divider()
    policy = load_policy_pack()
    schema_fields = {f["key"]: f["default"] for f in policy["shared_assumption_schema"]["fields"]}
    benchmark_ticker = str(schema_fields.get("benchmark_ticker", "SWRD.L"))
    db_path = sqlite_path_from_url(database_url)
    with sqlite3.connect(str(db_path)) as opp_conn:
        render_equity_opportunity_signal_card(opp_conn, benchmark_ticker)
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


def render_baseline_section(
    state: dict[str, Any], database_url: str
) -> None:
    st.subheader("Strategic baseline")

    pack = load_policy_pack()
    buckets = pack["baseline_bucket_model"]["buckets"]
    bucket_ids = [b["id"] for b in buckets]
    bucket_labels = [b["label"] for b in buckets]

    current_baseline: BaselineRecord | None = state["current_baseline"]
    editing = st.session_state.get(BASELINE_EDITING_KEY, False)
    editor_counter = st.session_state.get(BASELINE_EDITOR_KEY_COUNTER, 0)

    if not editing:
        if current_baseline is None:
            st.info(
                "No strategic baseline has been saved yet. "
                "Set target weights for each asset bucket below."
            )
        else:
            display_rows = [
                {"Bucket": label, "Weight (%)": current_baseline.weights.get(bid, 0.0)}
                for bid, label in zip(bucket_ids, bucket_labels)
            ]
            st.dataframe(
                pd.DataFrame(display_rows),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                f"Label: **{current_baseline.label}** · "
                f"Saved: {current_baseline.created_at[:10]}"
                + (f" · {current_baseline.notes}" if current_baseline.notes else "")
            )

        if st.button(
            "Edit baseline" if current_baseline else "Create baseline",
            key="baseline_edit_btn",
        ):
            st.session_state[BASELINE_EDITING_KEY] = True
            st.rerun()
        return

    if current_baseline is not None:
        initial_weights = [
            current_baseline.weights.get(bid, 0.0) for bid in bucket_ids
        ]
    else:
        equal_w = round(100.0 / len(buckets), 1)
        initial_weights = [equal_w] * len(buckets)

    editor_df = pd.DataFrame(
        {"Bucket": bucket_labels, "Weight (%)": initial_weights}
    )
    editor_df["Weight (%)"] = editor_df["Weight (%)"].astype(float)

    label_default = current_baseline.label if current_baseline else ""
    notes_default = (current_baseline.notes or "") if current_baseline else ""

    with st.form("baseline_editor_form", clear_on_submit=False):
        label = st.text_input(
            "Baseline label",
            value=label_default,
            placeholder="e.g. initial, defensive_tilt, post_review",
        )
        notes = st.text_input("Notes (optional)", value=notes_default)
        edited_df = st.data_editor(
            editor_df,
            key=f"baseline_editor_{editor_counter}",
            column_config={
                "Bucket": st.column_config.TextColumn("Bucket", disabled=True),
                "Weight (%)": st.column_config.NumberColumn(
                    "Weight (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=0.1,
                    format="%.1f",
                ),
            },
            num_rows="fixed",
            use_container_width=True,
        )
        total = float(edited_df["Weight (%)"].sum())
        st.caption(f"Total: {total:.1f}%")
        col1, col2 = st.columns(2)
        with col1:
            save = st.form_submit_button("Save baseline")
        with col2:
            cancel = st.form_submit_button("Cancel")

    if cancel:
        st.session_state[BASELINE_EDITING_KEY] = False
        st.session_state[BASELINE_EDITOR_KEY_COUNTER] = editor_counter + 1
        st.rerun()

    if save:
        if not label.strip():
            st.error("Baseline label must not be empty.")
            return

        edited_weights = {
            bid: float(w)
            for bid, w in zip(bucket_ids, edited_df["Weight (%)"])
        }
        try:
            record = BaselineRecord(
                created_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                label=label.strip(),
                policy_version=pack["policy_version"],
                weights=edited_weights,
                notes=notes.strip() or None,
            )
            db_path = sqlite_path_from_url(database_url)
            with sqlite3.connect(str(db_path)) as conn:
                insert_baseline(conn, record)
                conn.commit()
        except ValueError as exc:
            st.error(str(exc))
            return

        st.session_state[BASELINE_EDITING_KEY] = False
        st.session_state[BASELINE_EDITOR_KEY_COUNTER] = editor_counter + 1
        st.cache_data.clear()
        st.rerun()


def _render_cash_recommendation(state: dict[str, Any], database_url: str) -> None:
    st.subheader("Cash recommendation")

    holdings = state["holdings"]
    current_baseline = state["current_baseline"]
    snapshot_date = state["summary"].get("latest_snapshot_date") or ""

    if holdings.empty:
        st.info("No portfolio snapshot loaded. Import a portfolio CSV first.")
        return

    if current_baseline is None:
        st.info("No strategic baseline set. Add one in the baseline section above.")
        return

    policy = load_policy_pack()
    enriched = enrich_with_buckets(holdings)
    slim = enriched[["bucket_id", "market_value_gbp"]].copy()
    result = compute_cash_deployment(slim, current_baseline.weights, policy)

    cash_gbp = result.current_cash_pct / 100.0 * result.total_portfolio_gbp
    col1, col2, col3 = st.columns(3)
    col1.metric("Current cash / MMF", f"£{cash_gbp:,.0f}", f"{result.current_cash_pct:.1f}% of portfolio")
    col2.metric("Baseline target", f"{result.target_cash_pct:.1f}%")
    col3.metric("Excess to deploy", f"£{result.excess_cash_gbp:,.0f}")

    if st.button("Generate cash recommendation", type="primary"):
        record = build_cash_run_record(
            result=result,
            holdings_df=slim,
            baseline_label=current_baseline.label,
            policy=policy,
            snapshot_date=snapshot_date,
        )
        db_path = sqlite_path_from_url(database_url)
        write_conn = sqlite3.connect(str(db_path))
        try:
            insert_allocation_run(write_conn, record)
            write_conn.commit()
        finally:
            write_conn.close()
        st.cache_data.clear()
        st.rerun()

    connection = st.connection("db", type="sql", url=database_url)
    recent = connection.query(
        """
        SELECT id, created_at, solver_status, baseline_version, snapshot_json
        FROM allocation_runs
        WHERE solver_status = 'cash_only_prorata'
        ORDER BY id DESC
        LIMIT 5
        """,
        ttl=0,
    )

    if recent.empty:
        st.caption("No cash recommendation runs yet. Click the button above to generate one.")
        return

    latest = recent.iloc[0]
    snapshot = json.loads(latest["snapshot_json"])
    outputs = snapshot.get("outputs", {})
    allocations = outputs.get("recommended_allocations", [])
    diagnostics = snapshot.get("diagnostics", {})

    st.caption(f"Latest run: {latest['created_at']}  |  Baseline: {latest['baseline_version']}")

    if not allocations:
        st.success("No excess cash to deploy — portfolio cash allocation is at or below the target.")
    else:
        deploy_df = pd.DataFrame(allocations)[["label", "deploy_gbp", "target_pct_of_portfolio"]]
        deploy_df.columns = ["Bucket", "Deploy (£)", "Baseline target (%)"]
        deploy_df["Deploy (£)"] = deploy_df["Deploy (£)"].map(lambda v: f"£{v:,.0f}")
        deploy_df["Baseline target (%)"] = deploy_df["Baseline target (%)"].map(lambda v: f"{v:.1f}%")
        st.dataframe(deploy_df, hide_index=True, use_container_width=True)

    with st.expander("Assumptions used for this run"):
        policy_inputs = snapshot.get("policy_inputs", {})
        st.json(policy_inputs)
        notes = diagnostics.get("notes", [])
        if notes:
            for note in notes:
                st.caption(note)

    if len(recent) > 1:
        with st.expander(f"Run history ({len(recent)} most recent)"):
            history = recent[["id", "created_at", "baseline_version"]].copy()
            history.columns = ["Run ID", "Created at", "Baseline"]
            st.dataframe(history, hide_index=True, use_container_width=True)


def _render_lp_recommendation(state: dict[str, Any], database_url: str) -> None:
    st.subheader("Portfolio recommendation")

    holdings = state["holdings"]
    current_baseline = state["current_baseline"]
    snapshot_date = state["summary"].get("latest_snapshot_date") or ""

    if holdings.empty:
        st.info("No portfolio snapshot loaded. Import a portfolio CSV first.")
        return
    if current_baseline is None:
        st.info("No strategic baseline set. Add one in the baseline section above.")
        return
    if state["gilt_ranking"].empty:
        st.info("No gilt data available. Run a market data refresh first.")
        return

    policy = load_policy_pack()

    if st.button("Generate recommendation", type="primary", key="lp_recommend_btn"):
        with st.spinner("Running portfolio optimisation…", show_time=True):
            enriched = enrich_with_buckets(holdings)
            gilt_ranking_df = _build_lp_gilt_ranking(state["gilt_ranking"])
            result = build_lp_recommendation(
                enriched_holdings_df=enriched,
                baseline_weights=current_baseline.weights,
                baseline_label=current_baseline.label,
                policy=policy,
                snapshot_date=snapshot_date,
                gilt_ranking_df=gilt_ranking_df,
            )
        if result.solver_status != "optimal":
            st.error(
                f"LP solver returned '{result.solver_status}' — no executable recommendation. "
                + "; ".join(result.warnings)
            )
        else:
            db_path = sqlite_path_from_url(database_url)
            write_conn = sqlite3.connect(str(db_path))
            try:
                insert_allocation_run(write_conn, result.record)
                write_conn.commit()
            finally:
                write_conn.close()
            st.cache_data.clear()
            st.success("Recommendation generated and saved.")
            st.rerun()

    connection = st.connection("db", type="sql", url=database_url)
    recent = connection.query(
        """
        SELECT id, created_at, solver_status, baseline_version, snapshot_json
        FROM allocation_runs
        WHERE solver_status = 'optimal'
        ORDER BY id DESC
        LIMIT 1
        """,
        ttl=0,
    )

    if recent.empty:
        st.caption("No recommendation runs yet. Click the button above to generate one.")
        return

    latest = recent.iloc[0]
    snapshot = json.loads(latest["snapshot_json"])
    outputs = snapshot.get("outputs", {})
    trades = outputs.get("trades", [])
    recommended = outputs.get("recommended_allocations", [])
    diagnostics = snapshot.get("diagnostics", {})

    st.caption(
        f"Latest run: {latest['created_at']}  |  Baseline: {latest['baseline_version']}"
    )

    if recommended:
        st.markdown("**Executable portfolio (post-gate)**")
        rec_df = pd.DataFrame(recommended)[["label", "proposed_value_gbp", "proposed_pct"]]
        rec_df.columns = ["Bucket", "Value (£)", "Weight (%)"]
        rec_df["Value (£)"] = rec_df["Value (£)"].map(lambda v: f"£{v:,.0f}")
        rec_df["Weight (%)"] = rec_df["Weight (%)"].map(lambda v: f"{v:.1f}%")
        st.dataframe(rec_df, hide_index=True, use_container_width=True)

    if trades:
        friction_blocked, risk_blocked = categorise_blocked_trades(trades)
        friction_blocked = [t for t in friction_blocked if abs(t["delta_value_gbp"]) >= 1]
        risk_blocked = [t for t in risk_blocked if abs(t["delta_value_gbp"]) >= 1]
        passing = [
            t for t in trades
            if t["friction_outcome"] != "red"
            and t["risk_outcome"] in RISK_PASS_OUTCOMES
            and abs(t["delta_value_gbp"]) >= 1
        ]

        if passing:
            st.markdown("**Approved trades**")
            pass_df = pd.DataFrame(passing)[["symbol", "bucket_id", "delta_value_gbp", "friction_outcome", "friction_note"]]
            pass_df.columns = ["Symbol", "Bucket", "Delta (£)", "Friction", "Note"]
            pass_df["Delta (£)"] = pass_df["Delta (£)"].map(lambda v: f"£{v:+,.0f}")
            st.dataframe(pass_df, hide_index=True, use_container_width=True)

        if not friction_blocked and not risk_blocked:
            st.success("No blocked trades — all recommendations cleared friction and risk checks.")
        else:
            if friction_blocked:
                st.markdown(":red-badge[Friction block] Trade stopped because transaction cost exceeds yield benefit")
                fb_df = pd.DataFrame(friction_blocked)[["symbol", "delta_value_gbp", "friction_note"]]
                fb_df.columns = ["Trade", "Delta (£)", "Why blocked"]
                fb_df["Delta (£)"] = fb_df["Delta (£)"].map(lambda v: f"£{v:+,.0f}")
                with st.expander(f"Friction-blocked trades ({len(friction_blocked)})", expanded=True):
                    st.table(fb_df)

            if risk_blocked:
                st.markdown(":orange-badge[Risk block] Trade stopped by portfolio risk constraints")
                rb_df = pd.DataFrame(risk_blocked)[["symbol", "delta_value_gbp", "risk_outcome", "risk_note"]]
                rb_df["risk_outcome"] = rb_df["risk_outcome"].map(lambda o: RISK_OUTCOME_LABELS.get(o, o))
                rb_df.columns = ["Trade", "Delta (£)", "Constraint", "Why blocked"]
                rb_df["Delta (£)"] = rb_df["Delta (£)"].map(lambda v: f"£{v:+,.0f}")
                with st.expander(f"Risk-blocked trades ({len(risk_blocked)})", expanded=True):
                    st.table(rb_df)

    binding = diagnostics.get("binding_constraints", [])
    binding_details = diagnostics.get("binding_constraint_details", [])
    warnings = diagnostics.get("warnings", [])
    if binding or warnings:
        with st.expander("Constraints and warnings"):
            if binding_details:
                rows = [
                    {
                        "Constraint": d["label"],
                        "Explanation": d["short"],
                        "Shadow price": (
                            f"{d['shadow_price']:.4f}" if d["shadow_price"] is not None else "—"
                        ),
                        "Status": "Near-binding" if d["status"] == "near_binding" else "Binding",
                    }
                    for d in binding_details
                ]
                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    use_container_width=True,
                )
            elif binding:
                st.caption("Binding constraints: " + ", ".join(binding))
            for w in warnings:
                st.caption(f"⚠ {w}")


def _render_scenario_comparison(database_url: str) -> None:
    st.subheader("Scenario comparison")

    connection = st.connection("db", type="sql", url=database_url)
    recent = connection.query(
        """
        SELECT snapshot_json
        FROM allocation_runs
        WHERE solver_status = 'optimal'
        ORDER BY id DESC
        LIMIT 1
        """,
        ttl=0,
    )

    if recent.empty:
        st.info("No recommendation run found. Generate a recommendation above to see scenario comparison.")
        return

    snapshot = json.loads(recent.iloc[0]["snapshot_json"])
    records = snapshot.get("outputs", {}).get("scenario_results", [])

    if not records:
        st.info("This run pre-dates scenario results. Generate a new recommendation to populate the comparison.")
        return

    scenario_names = sorted({r["scenario_name"] for r in records})
    selected = st.selectbox("Scenario", options=scenario_names, key="scenario_compare_select")

    totals = compute_scenario_totals(records, selected)
    current_pnl = totals.get("current", 0.0)
    rec_pnl = totals.get("executable_recommended", 0.0)
    improvement = rec_pnl - current_pnl

    col1, col2, col3 = st.columns(3)
    col1.metric("Current portfolio PnL", f"£{current_pnl:,.0f}")
    col2.metric("Recommended portfolio PnL", f"£{rec_pnl:,.0f}")
    col3.metric("Improvement", f"£{improvement:+,.0f}")

    comparison_df = build_scenario_comparison_df(records, selected)
    if not comparison_df.empty:
        _COMPARISON_COL_LABELS: dict[str, str] = {
            "holding_name": "Holding",
            "asset_type": "Type",
            "bucket_name": "Bucket",
            "current_value_gbp_current": "Current value",
            "current_value_gbp_executable_recommended": "Recommended value",
            "scenario_value_gbp_current": "Scenario value (current)",
            "scenario_value_gbp_executable_recommended": "Scenario value (recommended)",
            "pnl_gbp_current": "PnL (current)",
            "pnl_gbp_executable_recommended": "PnL (recommended)",
        }
        _TEXT_COLS = {"holding_name", "asset_type", "bucket_name"}
        col_config = {
            c: (
                st.column_config.TextColumn(_COMPARISON_COL_LABELS.get(c, c))
                if c in _TEXT_COLS
                else st.column_config.NumberColumn(_COMPARISON_COL_LABELS.get(c, c), format="£%.0f")
            )
            for c in comparison_df.columns
        }
        st.dataframe(comparison_df, column_config=col_config, hide_index=True, use_container_width=True)

    coverage = build_coverage_summary(records, selected)
    if not coverage.empty:
        with st.expander("Coverage disclosure"):
            st.caption(
                "Shows how each holding is priced under the scenario. "
                "'exact' = full repricing model applied; "
                "'held_flat' = capital held constant (e.g. MMF); "
                "'unmodelled_held_flat' = no model available."
            )
            st.dataframe(
                coverage.rename(columns={"portfolio_state": "State", "model_status": "Model", "count": "Holdings"}),
                hide_index=True,
                use_container_width=True,
            )


def _render_recommendation_change_summary(database_url: str) -> None:
    st.subheader("Change summary")

    connection = st.connection("db", type="sql", url=database_url)
    recent = connection.query(
        """
        SELECT id, created_at, snapshot_json
        FROM allocation_runs
        WHERE solver_status = 'optimal'
        ORDER BY id DESC
        LIMIT 2
        """,
        ttl=0,
    )

    if recent.empty:
        st.info("No recommendation runs yet.")
        return

    current_snap = json.loads(recent.iloc[0]["snapshot_json"])
    prior_snap = json.loads(recent.iloc[1]["snapshot_json"]) if len(recent) >= 2 else None

    if prior_snap is None:
        st.info("This is the first recommendation run — no prior run to compare against.")
        return

    metrics = build_headline_metrics(prior_snap, current_snap)

    if metrics["regime_changed"]:
        st.info(
            f"Regime changed: **{metrics['prior_regime']}** → **{metrics['current_regime']}**"
        )
    if metrics["scenario_set_changed"]:
        st.info(
            f"Scenario set changed: **{metrics['prior_scenario_set']}** → **{metrics['current_scenario_set']}**"
        )

    prior_date = recent.iloc[1]["created_at"][:10]
    current_date = recent.iloc[0]["created_at"][:10]

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Portfolio value",
        f"£{metrics['current_value_gbp']:,.0f}",
        f"£{metrics['value_delta_gbp']:+,.0f}",
    )
    col2.metric(
        "Trades recommended",
        metrics["current_trade_count"],
        metrics["trade_count_delta"],
    )
    col3.metric("Prior run date", prior_date, help="Date of the run being compared against")

    change_df = build_allocation_change_df(prior_snap, current_snap)
    if change_df.empty:
        st.caption("No allocation shifts above threshold since the prior run.")
    else:
        st.dataframe(
            change_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "bucket_id": st.column_config.TextColumn("Bucket ID"),
                "label": st.column_config.TextColumn("Bucket"),
                "prior_pct": st.column_config.NumberColumn("Prior %", format="%.1f%%"),
                "current_pct": st.column_config.NumberColumn("Current %", format="%.1f%%"),
                "delta_pct": st.column_config.NumberColumn("Change", format="%+.1f%%"),
            },
        )

    with st.expander("Run details"):
        st.caption(f"Current run: {current_date}  |  Prior run: {prior_date}")


def _render_narrative_explanation_panel(database_url: str) -> None:
    connection = st.connection("db", type="sql", url=database_url)
    recent = connection.query(
        """
        SELECT id, created_at, snapshot_json
        FROM allocation_runs
        WHERE solver_status = 'optimal'
        ORDER BY id DESC
        LIMIT 2
        """,
        ttl=0,
    )

    if recent.empty:
        return

    current_snap = json.loads(recent.iloc[0]["snapshot_json"])
    prior_snap = json.loads(recent.iloc[1]["snapshot_json"]) if len(recent) >= 2 else None

    c = build_narrative_components(current_snap, prior_snapshot=prior_snap)

    st.subheader("Why this recommendation?")

    with st.container(border=True):
        _render_narrative_overview(c)
        _render_narrative_allocation_shifts(c)
        _render_narrative_blocked_trades(c)
        _render_narrative_binding_constraints(c)


def _render_narrative_overview(c: dict) -> None:
    n_approved = len(c["approved_trades"])
    n_friction = len(c["friction_blocked"])
    n_risk = len(c["risk_blocked"])
    n_blocked = n_friction + n_risk

    if c["headline"] is not None:
        h = c["headline"]
        col1, col2, col3 = st.columns(3)
        col1.metric(
            "Portfolio value",
            f"£{h['current_value_gbp']:,.0f}",
            f"£{h['value_delta_gbp']:+,.0f}",
        )
        col2.metric("Approved trades", n_approved)
        col3.metric("Blocked trades", n_blocked)
        if h["regime_changed"]:
            st.info(f"Regime changed: **{h['prior_regime']}** → **{h['current_regime']}**")
        if h["scenario_set_changed"]:
            st.info(
                f"Scenario set changed: **{h['prior_scenario_set']}** → **{h['current_scenario_set']}**"
            )
    else:
        col1, col2 = st.columns(2)
        col1.metric("Approved trades", n_approved)
        col2.metric("Blocked trades", n_blocked)


def _render_narrative_allocation_shifts(c: dict) -> None:
    deltas = c["allocation_deltas"]
    if deltas is None or deltas.empty:
        return

    by_abs = deltas.sort_values("delta_pct", key=lambda s: s.abs(), ascending=False)
    increases = by_abs[by_abs["delta_pct"] > 0].head(3)
    decreases = by_abs[by_abs["delta_pct"] < 0].head(3)

    if increases.empty and decreases.empty:
        return

    st.markdown("**Allocation shifts since prior run**")
    lines = []
    for _, row in increases.iterrows():
        lines.append(f"- **{row['label']}** +{row['delta_pct']:.1f}%")
    for _, row in decreases.iterrows():
        lines.append(f"- **{row['label']}** {row['delta_pct']:.1f}%")
    st.markdown("\n".join(lines))


def _render_narrative_blocked_trades(c: dict) -> None:
    if not c["friction_blocked"] and not c["risk_blocked"]:
        return

    if c["friction_blocked"]:
        st.markdown("**Friction-blocked** (dealing cost exceeds yield gain)")
        lines = []
        for t in c["friction_blocked"]:
            note = t.get("friction_note") or "cost exceeds gain"
            lines.append(f"- **{t['symbol']}** £{t['delta_value_gbp']:+,.0f} — {note}")
        st.markdown("\n".join(lines))

    if c["risk_blocked"]:
        st.markdown("**Risk-blocked** (policy constraint)")
        lines = []
        for t in c["risk_blocked"]:
            reason = t.get("risk_note") or RISK_OUTCOME_LABELS.get(t["risk_outcome"], t["risk_outcome"])
            lines.append(f"- **{t['symbol']}** £{t['delta_value_gbp']:+,.0f} — {reason}")
        st.markdown("\n".join(lines))


def _render_narrative_binding_constraints(c: dict) -> None:
    if not c["binding_constraints"]:
        return

    st.markdown("**Active constraints**")
    lines = []
    for constraint in c["binding_constraints"]:
        sp = constraint.get("shadow_price")
        sp_str = f" (shadow price: {sp:.4f})" if sp is not None else ""
        marker = " _(near binding)_" if constraint["status"] == "near_binding" else ""
        lines.append(f"- {constraint['short']}{sp_str}{marker}")
    st.markdown("\n".join(lines))


def render_scenarios_tab(state: dict[str, Any], database_url: str) -> None:
    render_baseline_section(state, database_url)
    st.divider()
    _render_lp_recommendation(state, database_url)
    st.divider()
    _render_scenario_comparison(database_url)
    st.divider()
    _render_recommendation_change_summary(database_url)
    st.divider()
    _render_narrative_explanation_panel(database_url)
    st.divider()
    _render_cash_recommendation(state, database_url)
    st.divider()
    refresh_frame = state["refresh_state"]
    st.caption("Market data refresh status")
    st.dataframe(refresh_frame, width="stretch", hide_index=True)


def render_decision_log_tab(state: dict[str, Any], database_url: str) -> None:
    st.subheader("Decision Log")

    decisions = state["decisions"]
    if decisions.empty:
        st.info("No decisions have been logged yet.")
    else:
        display = decisions[["decision_date", "action", "instruments_affected", "notes", "signal_event_id", "created_at"]].copy()
        display["instruments_affected"] = display["instruments_affected"].apply(
            lambda v: ", ".join(json.loads(v)) if pd.notna(v) and v else ""
        )
        st.dataframe(display, width="stretch", hide_index=True)

    st.divider()
    st.subheader("Log a decision")

    holdings = state["holdings"]
    symbols = sorted(holdings["symbol"].dropna().tolist()) if not holdings.empty else []

    active_signals = state["active_signals"]
    signal_options = ["(none)"]
    signal_id_map: dict[str, int | None] = {"(none)": None}
    if not active_signals.empty:
        for _, row in active_signals.iterrows():
            label = f"{row['alert_type']} — {row['message'][:60]}"
            signal_options.append(label)
            signal_id_map[label] = int(row["id"])

    with st.form("log_decision", clear_on_submit=True):
        decision_date = st.date_input("Date", value=date.today())
        action = st.selectbox("Action", ["acted", "passed", "deferred"])
        instruments = st.multiselect("Instruments affected", options=symbols, default=[])
        signal_label = st.selectbox("Link to signal event (optional)", options=signal_options)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Log decision")

    if submitted:
        db_path = sqlite_path_from_url(database_url)
        write_conn = sqlite3.connect(str(db_path))
        try:
            insert_decision(
                write_conn,
                decision_date=decision_date.isoformat(),
                action=action,
                instruments_affected=instruments,
                notes=notes,
                signal_event_id=signal_id_map.get(signal_label),
                created_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            write_conn.commit()
        finally:
            write_conn.close()
        st.cache_data.clear()
        st.rerun()


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
        render_signals_tab(state, database_url)
    with scenarios_tab:
        render_scenarios_tab(state, database_url)
    with decision_log_tab:
        render_decision_log_tab(state, database_url)


if __name__ == "__main__":
    main()
