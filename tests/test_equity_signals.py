from __future__ import annotations

import pytest

from investment_optimiser.equity_signals import ErpSignal, evaluate_erp_signal


def test_unavailable_when_pe_ratio_is_none() -> None:
    result = evaluate_erp_signal(
        pe_ratio=None,
        best_gry=0.045,
        cache_date="2026-05-19",
        erp_threshold_pct=0.0,
    )
    assert result.state == "unavailable"
    assert result.erp_pct is None
    assert result.earnings_yield_pct is None


def test_unavailable_when_best_gry_is_none() -> None:
    result = evaluate_erp_signal(
        pe_ratio=25.0,
        best_gry=None,
        cache_date="2026-05-19",
        erp_threshold_pct=0.0,
    )
    assert result.state == "unavailable"
    assert result.erp_pct is None


def test_unavailable_when_cache_date_is_none() -> None:
    result = evaluate_erp_signal(
        pe_ratio=25.0,
        best_gry=0.045,
        cache_date=None,
        erp_threshold_pct=0.0,
    )
    assert result.state == "unavailable"


def test_quiet_when_erp_above_threshold(monkeypatch) -> None:
    # PE 20 → earnings yield 5%, gilt GRY 4.5% → ERP +0.5% > 0% threshold
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since",
        lambda _: 1,
    )
    result = evaluate_erp_signal(
        pe_ratio=20.0,
        best_gry=0.045,
        cache_date="2026-05-19",
        erp_threshold_pct=0.0,
    )
    assert result.state == "quiet"
    assert result.erp_pct == pytest.approx(0.5, abs=1e-6)
    assert result.earnings_yield_pct == pytest.approx(5.0, abs=1e-6)
    assert result.best_gilt_gry_pct == pytest.approx(4.5, abs=1e-6)


def test_warning_when_erp_below_threshold(monkeypatch) -> None:
    # PE 30 → earnings yield 3.33%, gilt GRY 4.5% → ERP -1.17% < 0% threshold
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since",
        lambda _: 1,
    )
    result = evaluate_erp_signal(
        pe_ratio=30.0,
        best_gry=0.045,
        cache_date="2026-05-19",
        erp_threshold_pct=0.0,
    )
    assert result.state == "warning"
    assert result.erp_pct == pytest.approx((1 / 30 - 0.045) * 100, abs=1e-6)


def test_warning_respects_custom_threshold(monkeypatch) -> None:
    # ERP = +0.5% but threshold is 1% → still warning
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since",
        lambda _: 1,
    )
    result = evaluate_erp_signal(
        pe_ratio=20.0,
        best_gry=0.045,
        cache_date="2026-05-19",
        erp_threshold_pct=1.0,
    )
    assert result.state == "warning"


def test_stale_when_data_older_than_five_trading_days(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since",
        lambda _: 6,
    )
    result = evaluate_erp_signal(
        pe_ratio=20.0,
        best_gry=0.045,
        cache_date="2026-05-10",
        erp_threshold_pct=0.0,
    )
    assert result.state == "stale"
    # ERP values are still computed even when stale
    assert result.erp_pct is not None
    assert result.earnings_yield_pct == pytest.approx(5.0, abs=1e-6)


def test_not_stale_at_exactly_five_trading_days(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since",
        lambda _: 5,
    )
    result = evaluate_erp_signal(
        pe_ratio=20.0,
        best_gry=0.045,
        cache_date="2026-05-12",
        erp_threshold_pct=0.0,
    )
    assert result.state != "stale"
