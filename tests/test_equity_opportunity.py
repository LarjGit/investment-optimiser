from __future__ import annotations

import sqlite3

import pytest

from investment_optimiser.migrations import create_initial_schema


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    create_initial_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS equity_benchmark_prices (
            price_date   TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            close_price  REAL NOT NULL,
            volume       INTEGER,
            fetched_at   TEXT NOT NULL,
            PRIMARY KEY (price_date, ticker)
        ) STRICT, WITHOUT ROWID
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_equity_benchmark_prices_ticker_date
        ON equity_benchmark_prices(ticker, price_date DESC)
        """
    )
    return conn


def _seed_erp(conn: sqlite3.Connection, values: list[float]) -> None:
    for i, v in enumerate(values):
        d = f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO signal_readings "
            "(reading_date, signal_name, metric_name, value, unit) "
            "VALUES (?, 'erp', 'erp_pct', ?, 'pct')",
            (d, v),
        )


def _seed_pe(conn: sqlite3.Connection, values: list[float]) -> None:
    for i, v in enumerate(values):
        d = f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO equity_valuation_cache "
            "(cache_date, source_name, pe_ratio, pe_as_of, fetched_at) "
            "VALUES (?, 'yfinance_equities', ?, ?, 'now')",
            (d, v, d),
        )


def _seed_prices(conn: sqlite3.Connection, ticker: str, prices: list[float]) -> None:
    for i, p in enumerate(prices):
        d = f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO equity_benchmark_prices "
            "(price_date, ticker, close_price, volume, fetched_at) "
            "VALUES (?, ?, ?, 1000, 'now')",
            (d, ticker, p),
        )


# ---------------------------------------------------------------------------
# evaluate_equity_opportunity_signal — state and availability
# ---------------------------------------------------------------------------

def test_unavailable_when_no_data() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    result = evaluate_equity_opportunity_signal(_make_db(), "SWRD.L", min_history=5)
    assert result.state == "unavailable"
    assert result.composite_score is None
    assert result.components_available == 0


def test_unavailable_when_only_one_component() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.state == "unavailable"
    assert result.components_available == 1
    assert result.composite_score is None


def test_degraded_with_two_components() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.5 for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.is_degraded is True
    assert result.components_available == 2
    assert result.state != "unavailable"
    assert result.composite_score is not None


def test_not_degraded_with_all_three_components() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.is_degraded is False
    assert result.components_available == 3


def test_composite_score_bounded_0_to_1() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.composite_score is not None
    assert 0.0 <= result.composite_score <= 1.0


# ---------------------------------------------------------------------------
# Trend dampener
# ---------------------------------------------------------------------------

def test_trend_dampener_is_1_when_insufficient_price_history() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    # fewer than 200 price rows → no dampening
    assert result.trend_dampener == pytest.approx(1.0)


def test_trend_dampener_applied_in_persistent_bear_market() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    # 250 rows of steadily declining prices → fast EMA < slow EMA (bearish)
    declining = [200.0 - i * 0.4 for i in range(250)]
    _seed_erp(conn, [3.0] * 250)
    _seed_pe(conn, [20.0] * 250)
    _seed_prices(conn, "SWRD.L", declining)
    result = evaluate_equity_opportunity_signal(
        conn, "SWRD.L", min_history=5, trend_dampener_bear=0.75
    )
    assert result.trend_dampener == pytest.approx(0.75)


def test_trend_dampener_is_1_in_rising_market() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    # 250 rows of rising prices → fast EMA > slow EMA (bullish)
    rising = [50.0 + i * 0.4 for i in range(250)]
    _seed_erp(conn, [3.0] * 250)
    _seed_pe(conn, [20.0] * 250)
    _seed_prices(conn, "SWRD.L", rising)
    result = evaluate_equity_opportunity_signal(
        conn, "SWRD.L", min_history=5, trend_dampener_bear=0.75
    )
    assert result.trend_dampener == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# State bands
# ---------------------------------------------------------------------------

def test_score_to_opportunity_band_neutral() -> None:
    from investment_optimiser.equity_signals import _score_to_opportunity_band

    assert _score_to_opportunity_band(0.0) == "neutral"
    assert _score_to_opportunity_band(0.34) == "neutral"


def test_score_to_opportunity_band_modest() -> None:
    from investment_optimiser.equity_signals import _score_to_opportunity_band

    assert _score_to_opportunity_band(0.35) == "modest"
    assert _score_to_opportunity_band(0.54) == "modest"


def test_score_to_opportunity_band_attractive() -> None:
    from investment_optimiser.equity_signals import _score_to_opportunity_band

    assert _score_to_opportunity_band(0.55) == "attractive"
    assert _score_to_opportunity_band(0.71) == "attractive"


def test_score_to_opportunity_band_highly_attractive() -> None:
    from investment_optimiser.equity_signals import _score_to_opportunity_band

    assert _score_to_opportunity_band(0.72) == "highly_attractive"
    assert _score_to_opportunity_band(1.0) == "highly_attractive"


def test_high_score_state_is_attractive_or_better() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    # ERP: ascending series — latest is at the top (high percentile)
    erp_vals = [float(i) * 0.1 for i in range(1, 61)]
    # PE: declining (earnings yield rising) — latest is best valuation
    pe_vals = [30.0 - float(i) * 0.15 for i in range(60)]
    # Price: peak-and-decline so latest has large drawdown (good entry)
    prices = [100.0 + float(i) for i in range(30)] + [129.0 - float(i) * 2.0 for i in range(30)]
    _seed_erp(conn, erp_vals)
    _seed_pe(conn, pe_vals)
    _seed_prices(conn, "SWRD.L", prices)
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.state in ("attractive", "highly_attractive")


def test_low_score_state_is_neutral_or_modest() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    # ERP: descending — latest is at the bottom (low ERP = unattractive)
    erp_vals = [float(i) * 0.1 for i in range(60, 0, -1)]
    # PE: rising (earnings yield declining) — latest is most expensive
    pe_vals = [15.0 + float(i) * 0.3 for i in range(60)]
    # Price: steadily rising — no drawdown (worst for drawdown component)
    prices = [50.0 + float(i) * 0.5 for i in range(60)]
    _seed_erp(conn, erp_vals)
    _seed_pe(conn, pe_vals)
    _seed_prices(conn, "SWRD.L", prices)
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.state in ("neutral", "modest")


# ---------------------------------------------------------------------------
# Explanation and dataclass completeness
# ---------------------------------------------------------------------------

def test_explanation_is_non_empty() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert len(result.explanation) > 0


def test_unavailable_explanation_mentions_missing_data() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    result = evaluate_equity_opportunity_signal(_make_db(), "SWRD.L", min_history=5)
    assert "history" in result.explanation.lower() or "unavailable" in result.explanation.lower()


def test_erp_component_stored_on_signal() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.erp_component is not None
    assert 0.0 <= result.erp_component <= 1.0


def test_valuation_component_stored_on_signal() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.valuation_component is not None
    assert 0.0 <= result.valuation_component <= 1.0


def test_drawdown_component_stored_on_signal() -> None:
    from investment_optimiser.equity_signals import evaluate_equity_opportunity_signal

    conn = _make_db()
    _seed_erp(conn, list(range(1, 11)))
    _seed_pe(conn, [30.0 - i * 0.3 for i in range(10)])
    _seed_prices(conn, "SWRD.L", [100.0 + i for i in range(10)])
    result = evaluate_equity_opportunity_signal(conn, "SWRD.L", min_history=5)
    assert result.drawdown_component is not None
    assert 0.0 <= result.drawdown_component <= 1.0
