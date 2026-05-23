from __future__ import annotations

import datetime
from dataclasses import dataclass
import sqlite3

import pandas as pd

_MIN_HISTORY_DEFAULT = 30
_TREND_EMA_FAST = 50
_TREND_EMA_SLOW = 200
_TREND_DAMPENER_BEAR_DEFAULT = 0.75

_BAND_HIGHLY_ATTRACTIVE = 0.72
_BAND_ATTRACTIVE = 0.55
_BAND_MODEST = 0.35

try:
    from govuk_bank_holidays.bank_holidays import BankHolidays
    _bh = BankHolidays()
    _UK_HOLIDAYS: set[datetime.date] = {
        h["date"]
        for h in _bh.get_holidays(division=BankHolidays.ENGLAND_AND_WALES)
    }
except Exception:
    _UK_HOLIDAYS = set()


ERP_STALE_TRADING_DAYS = 5
CURVE_FLAT_THRESHOLD_BPS = 10.0
CURVE_PERSISTENCE_DAYS = 5


@dataclass(frozen=True)
class YieldCurveSignal:
    state: str
    curve_state: str | None
    consecutive_days: int | None
    spread_bps: float | None
    two_year_pct: float | None
    five_year_pct: float | None
    ten_year_pct: float | None
    cache_date: str | None
    explanation: str


@dataclass(frozen=True)
class ErpSignal:
    state: str
    erp_pct: float | None
    earnings_yield_pct: float | None
    best_gilt_gry_pct: float | None
    explanation: str


@dataclass(frozen=True)
class DurationLiquiditySignal:
    state: str
    avg_duration_years: float | None
    concentration_10y_plus_pct: float | None
    duration_floor_years: float
    duration_ceiling_years: float
    liquidity_threshold_pct: float
    gilt_count: int
    analytics_missing_count: int
    explanation: str


def _cutoff_10y() -> datetime.date:
    today = datetime.date.today()
    try:
        return today.replace(year=today.year + 10)
    except ValueError:
        return today.replace(year=today.year + 10, day=28)


def fetch_duration_liquidity_metrics(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
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
        """
    ).fetchall()
    return [
        {
            "isin": row[0],
            "market_value_gbp": row[1],
            "modified_duration_years": row[2],
            "maturity_date": row[3],
        }
        for row in rows
    ]


def evaluate_duration_liquidity_signal(
    rows: list[dict],
    floor: float,
    ceiling: float,
    liquidity_threshold: float,
) -> DurationLiquiditySignal:
    if not rows:
        return DurationLiquiditySignal(
            state="unavailable",
            avg_duration_years=None,
            concentration_10y_plus_pct=None,
            duration_floor_years=floor,
            duration_ceiling_years=ceiling,
            liquidity_threshold_pct=liquidity_threshold,
            gilt_count=0,
            analytics_missing_count=0,
            explanation="No gilt holdings found in the latest portfolio snapshot.",
        )

    gilt_count = len(rows)
    analytics_missing_count = sum(1 for r in rows if pd.isna(r["modified_duration_years"]))

    if analytics_missing_count > 0:
        return DurationLiquiditySignal(
            state="degraded",
            avg_duration_years=None,
            concentration_10y_plus_pct=None,
            duration_floor_years=floor,
            duration_ceiling_years=ceiling,
            liquidity_threshold_pct=liquidity_threshold,
            gilt_count=gilt_count,
            analytics_missing_count=analytics_missing_count,
            explanation=(
                f"{analytics_missing_count} of {gilt_count} gilt holding(s) have no duration analytics. "
                "Run a market refresh to populate analytics."
            ),
        )

    total_value = sum(r["market_value_gbp"] for r in rows)
    avg_duration = (
        sum(r["modified_duration_years"] * r["market_value_gbp"] for r in rows) / total_value
    )

    cutoff = _cutoff_10y()
    long_dated_value = sum(
        r["market_value_gbp"]
        for r in rows
        if pd.notna(r["maturity_date"])
        and datetime.date.fromisoformat(r["maturity_date"]) > cutoff
    )
    concentration = long_dated_value / total_value * 100.0

    alerts: list[str] = []
    if avg_duration < floor:
        alerts.append(f"avg duration {avg_duration:.2f}y is below floor {floor:.2f}y")
    if avg_duration > ceiling:
        alerts.append(f"avg duration {avg_duration:.2f}y is above ceiling {ceiling:.2f}y")
    if concentration > liquidity_threshold:
        alerts.append(f"10y+ concentration {concentration:.1f}% exceeds {liquidity_threshold:.1f}% threshold")

    if alerts:
        state = "triggered"
        explanation = "Alert: " + "; ".join(alerts) + "."
    else:
        state = "quiet"
        explanation = (
            f"Duration {avg_duration:.2f}y is within range [{floor:.2f}y, {ceiling:.2f}y]. "
            f"10y+ concentration {concentration:.1f}% is within {liquidity_threshold:.1f}% threshold."
        )

    return DurationLiquiditySignal(
        state=state,
        avg_duration_years=round(avg_duration, 4),
        concentration_10y_plus_pct=round(concentration, 4),
        duration_floor_years=floor,
        duration_ceiling_years=ceiling,
        liquidity_threshold_pct=liquidity_threshold,
        gilt_count=gilt_count,
        analytics_missing_count=0,
        explanation=explanation,
    )


def fetch_equity_valuation(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        """
        SELECT cache_date, source_name, pe_ratio, pe_as_of, fetched_at
        FROM equity_valuation_cache
        WHERE source_name = 'yfinance_equities'
        ORDER BY cache_date DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "cache_date": row[0],
        "source_name": row[1],
        "pe_ratio": row[2],
        "pe_as_of": row[3],
        "fetched_at": row[4],
    }


def fetch_best_conventional_gry(connection: sqlite3.Connection) -> float | None:
    row = connection.execute(
        """
        SELECT MAX(p.gry_pct)
        FROM gilt_price_cache p
        JOIN gilt_reference r ON r.isin = p.isin
        WHERE r.instrument_type = 'Conventional'
          AND p.cache_date = (SELECT MAX(cache_date) FROM gilt_price_cache)
        """
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def trading_days_since(cache_date: str) -> int:
    """Approximate Mon–Fri count; no UK bank-holiday awareness."""
    today = datetime.date.today().isoformat()
    if today <= cache_date:
        return 0
    return len(pd.bdate_range(cache_date, today)) - 1


def evaluate_erp_signal(
    pe_ratio: float | None,
    best_gry: float | None,
    cache_date: str | None,
    erp_threshold_pct: float,
) -> ErpSignal:
    if pe_ratio is None or best_gry is None or cache_date is None:
        return ErpSignal(
            state="unavailable",
            erp_pct=None,
            earnings_yield_pct=None,
            best_gilt_gry_pct=None,
            explanation="Equity valuation data is unavailable.",
        )

    earnings_yield = 1.0 / pe_ratio
    erp = earnings_yield - best_gry
    erp_pct = round(erp * 100, 6)
    earnings_yield_pct = round(earnings_yield * 100, 6)
    best_gilt_gry_pct = round(best_gry * 100, 6)

    if trading_days_since(cache_date) > ERP_STALE_TRADING_DAYS:
        state = "stale"
        explanation = (
            f"Data is stale (last fetched {cache_date}). "
            f"ERP was {erp_pct:+.2f}% "
            f"(earnings yield {earnings_yield_pct:.2f}% vs gilt GRY {best_gilt_gry_pct:.2f}%)."
        )
    elif erp < erp_threshold_pct / 100:
        state = "warning"
        explanation = (
            f"ERP is {erp_pct:+.2f}% — below the {erp_threshold_pct:+.2f}% threshold. "
            f"Gilt GRY ({best_gilt_gry_pct:.2f}%) exceeds equity earnings yield ({earnings_yield_pct:.2f}%)."
        )
    else:
        state = "quiet"
        explanation = (
            f"ERP is {erp_pct:+.2f}% — equities retain a positive risk premium over gilts. "
            f"Earnings yield {earnings_yield_pct:.2f}% vs gilt GRY {best_gilt_gry_pct:.2f}%."
        )

    return ErpSignal(
        state=state,
        erp_pct=erp_pct,
        earnings_yield_pct=earnings_yield_pct,
        best_gilt_gry_pct=best_gilt_gry_pct,
        explanation=explanation,
    )


def classify_curve_state(
    two_y: float,
    five_y: float,
    ten_y: float,
    flat_threshold_bps: float = CURVE_FLAT_THRESHOLD_BPS,
) -> str:
    two_to_ten_bps = (ten_y - two_y) * 100
    five_above_two_bps = (five_y - two_y) * 100
    five_above_ten_bps = (five_y - ten_y) * 100
    if five_above_two_bps > flat_threshold_bps and five_above_ten_bps > flat_threshold_bps:
        return "humped"
    if two_to_ten_bps > flat_threshold_bps:
        return "normal"
    if two_to_ten_bps < -flat_threshold_bps:
        return "inverted"
    return "flat"


def count_consecutive_bdays_with_state(
    history: list[tuple[str, str]],
    target_state: str,
    holiday_set: set[datetime.date],
) -> int:
    if not history:
        return 0

    date_state = {datetime.date.fromisoformat(d): s for d, s in history}
    most_recent = max(date_state)
    earliest = min(date_state)

    count = 0
    current = most_recent
    while current >= earliest:
        is_bday = current.weekday() < 5 and current not in holiday_set
        if is_bday:
            if current not in date_state or date_state[current] != target_state:
                break
            count += 1
        current -= datetime.timedelta(days=1)

    return count


def evaluate_yield_curve_shape_signal(
    two_y: float | None,
    five_y: float | None,
    ten_y: float | None,
    cache_date: str | None,
    history: list[tuple[str, str]],
    flat_threshold_bps: float = CURVE_FLAT_THRESHOLD_BPS,
    persistence_days: int = CURVE_PERSISTENCE_DAYS,
) -> YieldCurveSignal:
    if two_y is None or five_y is None or ten_y is None or cache_date is None:
        return YieldCurveSignal(
            state="unavailable",
            curve_state=None,
            consecutive_days=None,
            spread_bps=None,
            two_year_pct=None,
            five_year_pct=None,
            ten_year_pct=None,
            cache_date=cache_date,
            explanation="Yield curve data is unavailable.",
        )

    spread_bps = round((ten_y - two_y) * 100, 2)
    curve_state = classify_curve_state(two_y, five_y, ten_y, flat_threshold_bps)
    consecutive_days = count_consecutive_bdays_with_state(history, curve_state, _UK_HOLIDAYS)
    label = curve_state.capitalize()

    if trading_days_since(cache_date) > ERP_STALE_TRADING_DAYS:
        return YieldCurveSignal(
            state="stale",
            curve_state=curve_state,
            consecutive_days=consecutive_days,
            spread_bps=spread_bps,
            two_year_pct=round(two_y, 4),
            five_year_pct=round(five_y, 4),
            ten_year_pct=round(ten_y, 4),
            cache_date=cache_date,
            explanation=(
                f"Data is stale (last fetched {cache_date}). "
                f"Curve was {label} with 10y−2y spread {spread_bps:+.0f}bps."
            ),
        )

    if curve_state != "normal" and consecutive_days >= persistence_days:
        state = "warning"
        explanation = (
            f"Curve is {label} — 10y−2y spread {spread_bps:+.0f}bps "
            f"({two_y:.2f}% / {five_y:.2f}% / {ten_y:.2f}%). "
            f"This shape has held for {consecutive_days} consecutive UK business days "
            f"(≥{persistence_days}-day persistence threshold)."
        )
    else:
        state = "quiet"
        if curve_state == "normal":
            explanation = (
                f"Curve is Normal — 10y−2y spread {spread_bps:+.0f}bps "
                f"({two_y:.2f}% / {five_y:.2f}% / {ten_y:.2f}%). "
                "No warning condition active."
            )
        else:
            explanation = (
                f"Curve is {label} — 10y−2y spread {spread_bps:+.0f}bps "
                f"({two_y:.2f}% / {five_y:.2f}% / {ten_y:.2f}%). "
                f"Held for {consecutive_days} of {persistence_days} required consecutive "
                "UK business days before this triggers a warning."
            )

    return YieldCurveSignal(
        state=state,
        curve_state=curve_state,
        consecutive_days=consecutive_days,
        spread_bps=spread_bps,
        two_year_pct=round(two_y, 4),
        five_year_pct=round(five_y, 4),
        ten_year_pct=round(ten_y, 4),
        cache_date=cache_date,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Equity opportunity overlay
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EquityOpportunitySignal:
    state: str
    composite_score: float | None
    erp_component: float | None
    valuation_component: float | None
    drawdown_component: float | None
    trend_dampener: float | None
    components_available: int
    is_degraded: bool
    explanation: str


def _score_to_opportunity_band(score: float) -> str:
    if score >= _BAND_HIGHLY_ATTRACTIVE:
        return "highly_attractive"
    if score >= _BAND_ATTRACTIVE:
        return "attractive"
    if score >= _BAND_MODEST:
        return "modest"
    return "neutral"


def _compute_erp_component(conn: sqlite3.Connection, min_history: int) -> float | None:
    rows = conn.execute(
        "SELECT value FROM signal_readings "
        "WHERE signal_name='erp' AND metric_name='erp_pct' "
        "ORDER BY reading_date ASC"
    ).fetchall()
    if len(rows) < min_history:
        return None
    series = pd.Series([float(r[0]) for r in rows])
    return float(series.expanding().rank(pct=True).iloc[-1])


def _compute_valuation_component(conn: sqlite3.Connection, min_history: int) -> float | None:
    rows = conn.execute(
        "SELECT pe_ratio FROM equity_valuation_cache "
        "WHERE source_name='yfinance_equities' "
        "ORDER BY cache_date ASC"
    ).fetchall()
    if len(rows) < min_history:
        return None
    earnings_yields = pd.Series([1.0 / float(r[0]) for r in rows])
    return float(earnings_yields.expanding().rank(pct=True).iloc[-1])


def _compute_drawdown_component(
    conn: sqlite3.Connection,
    ticker: str,
    min_history: int,
) -> float | None:
    rows = conn.execute(
        "SELECT close_price FROM equity_benchmark_prices "
        "WHERE ticker=? "
        "ORDER BY price_date ASC",
        (ticker,),
    ).fetchall()
    if len(rows) < min_history:
        return None
    prices = pd.Series([float(r[0]) for r in rows])
    rolling_peak = prices.rolling(252, min_periods=1).max()
    drawdown_magnitude = (rolling_peak - prices) / rolling_peak
    return float(drawdown_magnitude.expanding().rank(pct=True).iloc[-1])


def _compute_trend_dampener(
    conn: sqlite3.Connection,
    ticker: str,
    trend_dampener_bear: float,
) -> float:
    rows = conn.execute(
        "SELECT close_price FROM equity_benchmark_prices "
        "WHERE ticker=? "
        "ORDER BY price_date ASC",
        (ticker,),
    ).fetchall()
    if len(rows) < _TREND_EMA_SLOW:
        return 1.0
    prices = pd.Series([float(r[0]) for r in rows])
    fast_ema = prices.ewm(span=_TREND_EMA_FAST, adjust=False).mean()
    slow_ema = prices.ewm(span=_TREND_EMA_SLOW, adjust=False).mean()
    if fast_ema.iloc[-1] < slow_ema.iloc[-1]:
        return trend_dampener_bear
    return 1.0


def _opportunity_explanation(
    state: str,
    is_degraded: bool,
    erp: float | None,
    valuation: float | None,
    drawdown: float | None,
    dampener: float,
) -> str:
    band_intro = {
        "highly_attractive": "Highly attractive entry conditions historically.",
        "attractive": "Attractive entry conditions historically.",
        "modest": "Modest opportunity — conditions are somewhat favourable.",
        "neutral": "Neutral — no strong historical entry signal right now.",
    }
    parts = [band_intro[state]]

    if erp is not None:
        if erp >= 0.6:
            parts.append("Equities offer a favourable premium over available gilt yields.")
        elif erp <= 0.3:
            parts.append("Equity premium over gilts is historically low.")

    if valuation is not None:
        if valuation >= 0.6:
            parts.append("Global equities are cheap relative to their own recent history.")
        elif valuation <= 0.3:
            parts.append("Global equities are expensive relative to their own recent history.")

    if drawdown is not None:
        if drawdown >= 0.6:
            parts.append(
                "Markets are materially below their recent high, "
                "which historically improves long-term entry conditions."
            )
        elif drawdown <= 0.3:
            parts.append("Markets are near their recent high — limited drawdown discount.")

    if dampener < 1.0:
        parts.append("Trend conditions are weak; the score has been dampened rather than blocked.")

    if is_degraded:
        parts.append("Score is based on fewer than all three components — treat with caution.")

    return " ".join(parts)


def _unavailable_explanation(
    erp: float | None,
    valuation: float | None,
    drawdown: float | None,
) -> str:
    missing = [
        name
        for name, val in (("ERP history", erp), ("valuation history", valuation), ("price history", drawdown))
        if val is None
    ]
    return (
        f"Insufficient history for a composite score ({', '.join(missing)} not yet available). "
        "Run more market refreshes to build up the historical series."
    )


def evaluate_equity_opportunity_signal(
    conn: sqlite3.Connection,
    benchmark_ticker: str,
    min_history: int = _MIN_HISTORY_DEFAULT,
    trend_dampener_bear: float = _TREND_DAMPENER_BEAR_DEFAULT,
) -> EquityOpportunitySignal:
    erp = _compute_erp_component(conn, min_history)
    valuation = _compute_valuation_component(conn, min_history)
    drawdown = _compute_drawdown_component(conn, benchmark_ticker, min_history)

    available = [c for c in [erp, valuation, drawdown] if c is not None]
    n = len(available)

    if n < 2:
        return EquityOpportunitySignal(
            state="unavailable",
            composite_score=None,
            erp_component=erp,
            valuation_component=valuation,
            drawdown_component=drawdown,
            trend_dampener=None,
            components_available=n,
            is_degraded=False,
            explanation=_unavailable_explanation(erp, valuation, drawdown),
        )

    is_degraded = n < 3
    dampener = _compute_trend_dampener(conn, benchmark_ticker, trend_dampener_bear)
    composite = round(sum(available) / n * dampener, 4)
    state = _score_to_opportunity_band(composite)

    return EquityOpportunitySignal(
        state=state,
        composite_score=composite,
        erp_component=erp,
        valuation_component=valuation,
        drawdown_component=drawdown,
        trend_dampener=dampener,
        components_available=n,
        is_degraded=is_degraded,
        explanation=_opportunity_explanation(state, is_degraded, erp, valuation, drawdown, dampener),
    )
