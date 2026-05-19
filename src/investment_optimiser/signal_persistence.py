from __future__ import annotations

import json
import sqlite3

from investment_optimiser.equity_signals import (
    classify_curve_state,
    evaluate_duration_liquidity_signal,
    evaluate_erp_signal,
    evaluate_yield_curve_shape_signal,
    fetch_best_conventional_gry,
    fetch_duration_liquidity_metrics,
    fetch_equity_valuation,
)
from investment_optimiser.policy_pack import load_policy_pack


def write_signal_readings(
    conn: sqlite3.Connection,
    reading_date: str,
    signal_name: str,
    metrics: list[tuple[str, float, str]],
) -> None:
    for metric_name, value, unit in metrics:
        conn.execute(
            """
            INSERT INTO signal_readings (reading_date, signal_name, metric_name, value, unit)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(reading_date, signal_name, metric_name)
            DO UPDATE SET value = excluded.value, unit = excluded.unit
            """,
            (reading_date, signal_name, metric_name, value, unit),
        )


def reconcile_signal_event(
    conn: sqlite3.Connection,
    alert_type: str,
    scope_key: str,
    is_firing: bool,
    severity: str,
    message: str,
    details_json: str,
    now: str,
) -> None:
    row = conn.execute(
        "SELECT id FROM signal_events WHERE alert_type=? AND scope_key=? AND cleared_at IS NULL",
        (alert_type, scope_key),
    ).fetchone()

    if is_firing:
        if row is None:
            conn.execute(
                """
                INSERT INTO signal_events
                    (alert_type, scope_key, severity, started_at, last_seen_at, message, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (alert_type, scope_key, severity, now, now, message, details_json),
            )
        else:
            conn.execute(
                "UPDATE signal_events SET last_seen_at=? WHERE id=?",
                (now, row[0]),
            )
    elif row is not None:
        conn.execute(
            "UPDATE signal_events SET cleared_at=?, last_seen_at=? WHERE id=?",
            (now, now, row[0]),
        )


def _fetch_yield_curve_data(
    conn: sqlite3.Connection,
    reading_date: str,
) -> tuple[dict | None, list[tuple[str, str]]]:
    latest_row = conn.execute(
        """
        SELECT
            cache_date,
            MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) AS ten_year_pct,
            MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) AS twenty_year_pct
        FROM yield_curve_cache
        WHERE cache_date = (
            SELECT MAX(cache_date) FROM yield_curve_cache WHERE curve_key = 'boe_10y'
        )
        GROUP BY cache_date
        """
    ).fetchone()

    yield_curve: dict | None = None
    if latest_row and all(v is not None for v in [latest_row[1], latest_row[2], latest_row[3]]):
        yield_curve = {
            "cache_date": latest_row[0],
            "five_year_pct": float(latest_row[1]),
            "ten_year_pct": float(latest_row[2]),
            "twenty_year_pct": float(latest_row[3]),
        }

    history_rows = conn.execute(
        """
        SELECT
            cache_date,
            MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) AS five_year_pct,
            MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) AS ten_year_pct,
            MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) AS twenty_year_pct
        FROM yield_curve_cache
        WHERE curve_key IN ('boe_5y', 'boe_10y', 'boe_20y')
          AND cache_date >= date(?, '-40 days')
        GROUP BY cache_date
        HAVING MAX(CASE WHEN curve_key = 'boe_5y'  THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'boe_10y' THEN rate_pct END) IS NOT NULL
           AND MAX(CASE WHEN curve_key = 'boe_20y' THEN rate_pct END) IS NOT NULL
        ORDER BY cache_date DESC
        """,
        (reading_date,),
    ).fetchall()

    history: list[tuple[str, str]] = [
        (row[0], classify_curve_state(float(row[1]), float(row[2]), float(row[3])))
        for row in history_rows
    ]
    return yield_curve, history


def run_signal_persistence(
    conn: sqlite3.Connection,
    reading_date: str,
    now: str,
) -> None:
    policy = load_policy_pack()
    constraints = policy["default_constraints"]
    schema_fields = {f["key"]: f["default"] for f in policy["shared_assumption_schema"]["fields"]}

    erp_threshold_pct = float(schema_fields.get("erp_threshold_pct", 0.0))
    duration_floor = float(constraints["duration_floor_years"])
    duration_ceiling = float(constraints["duration_ceiling_years"])
    liquidity_threshold = float(constraints["liquidity_concentration_10y_plus_pct"])

    equity_valuation = fetch_equity_valuation(conn)
    best_gry = fetch_best_conventional_gry(conn)

    pe_ratio: float | None = None
    cache_date: str | None = None
    if equity_valuation is not None:
        pe_ratio = equity_valuation.get("pe_ratio")
        cache_date = equity_valuation.get("cache_date")

    erp_signal = evaluate_erp_signal(
        pe_ratio=pe_ratio,
        best_gry=best_gry,
        cache_date=cache_date,
        erp_threshold_pct=erp_threshold_pct,
    )

    if erp_signal.erp_pct is not None:
        write_signal_readings(
            conn,
            reading_date=reading_date,
            signal_name="erp",
            metrics=[
                ("erp_pct", erp_signal.erp_pct, "pct"),
                ("earnings_yield_pct", erp_signal.earnings_yield_pct, "pct"),
                ("best_gilt_gry_pct", erp_signal.best_gilt_gry_pct, "pct"),
            ],
        )

    erp_firing = erp_signal.state == "warning"
    reconcile_signal_event(
        conn,
        alert_type="erp_warning",
        scope_key="global",
        is_firing=erp_firing,
        severity="warning",
        message=erp_signal.explanation if erp_firing else "",
        details_json=json.dumps({
            "erp_pct": erp_signal.erp_pct,
            "earnings_yield_pct": erp_signal.earnings_yield_pct,
            "best_gilt_gry_pct": erp_signal.best_gilt_gry_pct,
        }) if erp_firing else "{}",
        now=now,
    )

    yield_curve, yield_curve_history = _fetch_yield_curve_data(conn, reading_date)

    yc_signal = evaluate_yield_curve_shape_signal(
        five_y=yield_curve.get("five_year_pct") if yield_curve else None,
        ten_y=yield_curve.get("ten_year_pct") if yield_curve else None,
        twenty_y=yield_curve.get("twenty_year_pct") if yield_curve else None,
        cache_date=yield_curve.get("cache_date") if yield_curve else None,
        history=yield_curve_history,
    )

    if yc_signal.spread_bps is not None:
        yc_metrics: list[tuple[str, float, str]] = [
            ("five_year_pct", yc_signal.five_year_pct, "pct"),
            ("ten_year_pct", yc_signal.ten_year_pct, "pct"),
            ("twenty_year_pct", yc_signal.twenty_year_pct, "pct"),
            ("spread_bps", yc_signal.spread_bps, "bps"),
        ]
        if yc_signal.consecutive_days is not None:
            yc_metrics.append(("consecutive_days", float(yc_signal.consecutive_days), "days"))
        write_signal_readings(conn, reading_date=reading_date, signal_name="yield_curve_shape", metrics=yc_metrics)

    yc_firing = yc_signal.state == "warning"
    reconcile_signal_event(
        conn,
        alert_type="yield_curve_shape_warning",
        scope_key="global",
        is_firing=yc_firing,
        severity="warning",
        message=yc_signal.explanation if yc_firing else "",
        details_json=json.dumps({
            "curve_state": yc_signal.curve_state,
            "consecutive_days": yc_signal.consecutive_days,
            "spread_bps": yc_signal.spread_bps,
        }) if yc_firing else "{}",
        now=now,
    )

    dl_rows = fetch_duration_liquidity_metrics(conn)
    dl_signal = evaluate_duration_liquidity_signal(
        rows=dl_rows,
        floor=duration_floor,
        ceiling=duration_ceiling,
        liquidity_threshold=liquidity_threshold,
    )

    if dl_signal.avg_duration_years is not None:
        write_signal_readings(
            conn,
            reading_date=reading_date,
            signal_name="duration_liquidity",
            metrics=[
                ("avg_duration_years", dl_signal.avg_duration_years, "years"),
                ("concentration_10y_plus_pct", dl_signal.concentration_10y_plus_pct, "pct"),
            ],
        )

    duration_firing = (
        dl_signal.avg_duration_years is not None
        and (
            dl_signal.avg_duration_years < duration_floor
            or dl_signal.avg_duration_years > duration_ceiling
        )
    )
    liquidity_firing = (
        dl_signal.concentration_10y_plus_pct is not None
        and dl_signal.concentration_10y_plus_pct > liquidity_threshold
    )

    reconcile_signal_event(
        conn,
        alert_type="duration_warning",
        scope_key="global",
        is_firing=duration_firing,
        severity="warning",
        message=(
            f"Avg duration {dl_signal.avg_duration_years:.2f}y outside "
            f"[{duration_floor:.2f}y, {duration_ceiling:.2f}y]."
        ) if duration_firing else "",
        details_json=json.dumps({
            "avg_duration_years": dl_signal.avg_duration_years,
            "floor": duration_floor,
            "ceiling": duration_ceiling,
        }) if duration_firing else "{}",
        now=now,
    )

    reconcile_signal_event(
        conn,
        alert_type="liquidity_concentration_warning",
        scope_key="global",
        is_firing=liquidity_firing,
        severity="warning",
        message=(
            f"10y+ concentration {dl_signal.concentration_10y_plus_pct:.1f}% "
            f"exceeds {liquidity_threshold:.1f}% threshold."
        ) if liquidity_firing else "",
        details_json=json.dumps({
            "concentration_10y_plus_pct": dl_signal.concentration_10y_plus_pct,
            "threshold": liquidity_threshold,
        }) if liquidity_firing else "{}",
        now=now,
    )
