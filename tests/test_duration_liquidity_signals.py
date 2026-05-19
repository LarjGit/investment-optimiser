from __future__ import annotations

import datetime
from pathlib import Path
import sqlite3

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.equity_signals import (
    DurationLiquiditySignal,
    evaluate_duration_liquidity_signal,
    fetch_duration_liquidity_metrics,
)


# ---------------------------------------------------------------------------
# Row builder — matches the dict shape returned by fetch_duration_liquidity_metrics
# ---------------------------------------------------------------------------

def _today_plus_years(years: int) -> str:
    today = datetime.date.today()
    try:
        return today.replace(year=today.year + years).isoformat()
    except ValueError:
        return today.replace(year=today.year + years, day=28).isoformat()


def _row(
    *,
    isin: str = "GB00B54HL0K3",
    market_value_gbp: float = 10_000.0,
    modified_duration_years: float | None = 5.0,
    maturity_date: str | None = None,
) -> dict:
    return {
        "isin": isin,
        "market_value_gbp": market_value_gbp,
        "modified_duration_years": modified_duration_years,
        "maturity_date": maturity_date if maturity_date is not None else _today_plus_years(5),
    }


# ---------------------------------------------------------------------------
# evaluate_duration_liquidity_signal — state transitions
# ---------------------------------------------------------------------------

def test_unavailable_when_no_gilt_rows() -> None:
    result = evaluate_duration_liquidity_signal(
        rows=[], floor=2.0, ceiling=8.0, liquidity_threshold=35.0
    )
    assert result.state == "unavailable"
    assert result.avg_duration_years is None
    assert result.concentration_10y_plus_pct is None
    assert result.gilt_count == 0


def test_degraded_when_any_analytics_missing() -> None:
    rows = [
        _row(isin="GB0001", modified_duration_years=5.0),
        _row(isin="GB0002", modified_duration_years=None),
    ]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "degraded"
    assert result.analytics_missing_count == 1


def test_degraded_when_all_analytics_missing() -> None:
    rows = [
        _row(isin="GB0001", modified_duration_years=None),
        _row(isin="GB0002", modified_duration_years=None),
    ]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "degraded"
    assert result.analytics_missing_count == 2


def test_quiet_when_within_all_thresholds() -> None:
    # duration=5y (in floor=2..ceiling=8), concentration=0% (no 10y+ gilts), threshold=35%
    rows = [_row(modified_duration_years=5.0, maturity_date=_today_plus_years(5))]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "quiet"
    assert result.avg_duration_years == pytest.approx(5.0)
    assert result.concentration_10y_plus_pct == pytest.approx(0.0)


def test_triggered_when_duration_above_ceiling() -> None:
    rows = [_row(modified_duration_years=10.0, maturity_date=_today_plus_years(5))]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "triggered"


def test_triggered_when_duration_below_floor() -> None:
    rows = [_row(modified_duration_years=1.0, maturity_date=_today_plus_years(5))]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "triggered"


def test_triggered_when_concentration_above_threshold() -> None:
    # All value in a gilt maturing 11y out → 100% concentration > 35% threshold
    rows = [_row(modified_duration_years=5.0, maturity_date=_today_plus_years(11))]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.state == "triggered"
    assert result.concentration_10y_plus_pct == pytest.approx(100.0)


def test_weighted_average_duration_correct() -> None:
    # £10k at 4y + £30k at 8y → WA = (4*10k + 8*30k) / 40k = 7y
    rows = [
        _row(isin="GB0001", market_value_gbp=10_000.0, modified_duration_years=4.0, maturity_date=_today_plus_years(5)),
        _row(isin="GB0002", market_value_gbp=30_000.0, modified_duration_years=8.0, maturity_date=_today_plus_years(5)),
    ]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=10.0, liquidity_threshold=35.0)
    assert result.avg_duration_years == pytest.approx(7.0)


def test_concentration_counts_10y_plus_correctly() -> None:
    # £40k in 5y gilt (within 10y), £10k in 15y gilt (beyond 10y) → 20% concentration
    rows = [
        _row(isin="GB0001", market_value_gbp=40_000.0, modified_duration_years=5.0, maturity_date=_today_plus_years(5)),
        _row(isin="GB0002", market_value_gbp=10_000.0, modified_duration_years=12.0, maturity_date=_today_plus_years(15)),
    ]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=15.0, liquidity_threshold=35.0)
    assert result.concentration_10y_plus_pct == pytest.approx(20.0)
    assert result.state == "quiet"


def test_signal_exposes_thresholds() -> None:
    rows = [_row(modified_duration_years=5.0)]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.duration_floor_years == 2.0
    assert result.duration_ceiling_years == 8.0
    assert result.liquidity_threshold_pct == 35.0


def test_signal_exposes_gilt_count() -> None:
    rows = [
        _row(isin="GB0001", modified_duration_years=5.0),
        _row(isin="GB0002", modified_duration_years=6.0),
    ]
    result = evaluate_duration_liquidity_signal(rows=rows, floor=2.0, ceiling=8.0, liquidity_threshold=35.0)
    assert result.gilt_count == 2


# ---------------------------------------------------------------------------
# fetch_duration_liquidity_metrics — integration tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        yield connection


def _seed_reference(
    connection: sqlite3.Connection,
    *,
    isin: str,
    coupon_pct: float = 4.0,
    maturity_date: str = "2035-06-07",
    instrument_type: str = "Conventional",
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_reference (
            isin, instrument_name, coupon_pct, maturity_date,
            dividend_months, dividend_day, instrument_type, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (isin, "Test Gilt", coupon_pct, maturity_date, "Jun,Dec", 7, instrument_type, "2026-05-20T08:00:00Z"),
    )


def _seed_snapshot(
    connection: sqlite3.Connection,
    *,
    isin: str | None = "GB00B54HL0K3",
    symbol: str = "TG35",
    asset_type: str = "gilt_conventional",
    market_value_gbp: float = 10_000.0,
    snapshot_date: str = "2026-05-20",
) -> None:
    connection.execute(
        """
        INSERT INTO portfolio_snapshots (
            snapshot_date, symbol, isin, instrument_name, asset_type,
            quantity, clean_price_gbp, market_value_gbp, weight_pct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snapshot_date, symbol, isin, "Test Gilt", asset_type, 100.0, 100.0, market_value_gbp, 100.0),
    )


def _seed_price_cache(
    connection: sqlite3.Connection,
    *,
    isin: str,
    modified_duration_years: float | None = 5.0,
    maturity_date: str = "2035-06-07",
    cache_date: str = "2026-05-20",
) -> None:
    connection.execute(
        """
        INSERT INTO gilt_price_cache (
            cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years,
            coupon_pct, maturity_date, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_date, isin, 100.0, 0.04, modified_duration_years, 4.0, maturity_date, "2026-05-20T08:00:00Z"),
    )


def test_fetch_returns_empty_when_no_gilt_holdings(db: sqlite3.Connection) -> None:
    _seed_snapshot(db, isin=None, symbol="SWRD", asset_type="etf")
    db.commit()

    rows = fetch_duration_liquidity_metrics(db)

    assert rows == []


def test_fetch_returns_gilt_rows_with_analytics(db: sqlite3.Connection) -> None:
    _seed_reference(db, isin="GB00B54HL0K3", maturity_date="2035-06-07")
    _seed_snapshot(db, isin="GB00B54HL0K3", symbol="TG35", asset_type="gilt_conventional", market_value_gbp=15_000.0)
    _seed_price_cache(db, isin="GB00B54HL0K3", modified_duration_years=8.5, maturity_date="2035-06-07")
    db.commit()

    rows = fetch_duration_liquidity_metrics(db)

    assert len(rows) == 1
    assert rows[0]["isin"] == "GB00B54HL0K3"
    assert rows[0]["market_value_gbp"] == pytest.approx(15_000.0)
    assert rows[0]["modified_duration_years"] == pytest.approx(8.5)
    assert rows[0]["maturity_date"] == "2035-06-07"


def test_fetch_returns_null_analytics_when_cache_missing(db: sqlite3.Connection) -> None:
    # Gilt in portfolio but no gilt_price_cache row → modified_duration_years is None
    _seed_reference(db, isin="GB00B54HL0K3")
    _seed_snapshot(db, isin="GB00B54HL0K3", symbol="TG35", asset_type="gilt_conventional")
    db.commit()

    rows = fetch_duration_liquidity_metrics(db)

    assert len(rows) == 1
    assert rows[0]["modified_duration_years"] is None


def test_fetch_scopes_to_latest_snapshot_date(db: sqlite3.Connection) -> None:
    # Two snapshots — only the latest should be returned
    _seed_reference(db, isin="GB00B54HL0K3")
    _seed_snapshot(db, isin="GB00B54HL0K3", symbol="TG35", snapshot_date="2026-05-19", market_value_gbp=9_000.0)
    _seed_snapshot(db, isin="GB00B54HL0K3", symbol="TG35", snapshot_date="2026-05-20", market_value_gbp=10_000.0)
    _seed_price_cache(db, isin="GB00B54HL0K3", modified_duration_years=5.0)
    db.commit()

    rows = fetch_duration_liquidity_metrics(db)

    assert len(rows) == 1
    assert rows[0]["market_value_gbp"] == pytest.approx(10_000.0)
