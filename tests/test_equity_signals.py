from __future__ import annotations

import datetime

import pytest

from investment_optimiser.equity_signals import (
    ErpSignal,
    YieldCurveSignal,
    classify_curve_state,
    count_consecutive_bdays_with_state,
    evaluate_erp_signal,
    evaluate_yield_curve_shape_signal,
)


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


# ---------------------------------------------------------------------------
# classify_curve_state
# ---------------------------------------------------------------------------

def test_classify_normal_when_spread_above_threshold() -> None:
    # 10y−2y = 50bps > 10bps, 5y not a hump → normal
    assert classify_curve_state(two_y=4.0, five_y=4.3, ten_y=4.5) == "normal"


def test_classify_inverted_when_spread_below_negative_threshold() -> None:
    # 10y−2y = −50bps < −10bps → inverted
    assert classify_curve_state(two_y=4.5, five_y=4.2, ten_y=4.0) == "inverted"


def test_classify_flat_when_spread_within_threshold() -> None:
    # 10y−2y = 5bps, |5| <= 10 → flat
    assert classify_curve_state(two_y=4.0, five_y=4.0, ten_y=4.05) == "flat"


def test_classify_humped_when_five_year_is_local_peak() -> None:
    # 5y above both 2y and 10y by >10bps → humped
    assert classify_curve_state(two_y=4.0, five_y=4.5, ten_y=4.1) == "humped"


def test_classify_normal_not_humped_when_ten_year_also_high() -> None:
    # 5y=4.3 above 2y=4.0 by 30bps, but 5y < 10y=4.5 → not humped → normal
    assert classify_curve_state(two_y=4.0, five_y=4.3, ten_y=4.5) == "normal"


def test_classify_respects_custom_threshold() -> None:
    # 10y−2y = 15bps, threshold=20bps → flat (not normal)
    assert classify_curve_state(two_y=4.0, five_y=4.0, ten_y=4.15, flat_threshold_bps=20.0) == "flat"


# ---------------------------------------------------------------------------
# count_consecutive_bdays_with_state
# ---------------------------------------------------------------------------

_NO_HOLIDAYS: set[datetime.date] = set()


def test_consecutive_returns_zero_for_empty_history() -> None:
    assert count_consecutive_bdays_with_state([], "normal", _NO_HOLIDAYS) == 0


def test_consecutive_counts_matching_streak() -> None:
    # Mon-Fri last week all "inverted"
    history = [
        ("2026-05-15", "inverted"),  # Fri
        ("2026-05-14", "inverted"),  # Thu
        ("2026-05-13", "inverted"),  # Wed
        ("2026-05-12", "inverted"),  # Tue
        ("2026-05-11", "inverted"),  # Mon
    ]
    assert count_consecutive_bdays_with_state(history, "inverted", _NO_HOLIDAYS) == 5


def test_consecutive_breaks_on_different_state() -> None:
    history = [
        ("2026-05-15", "inverted"),
        ("2026-05-14", "inverted"),
        ("2026-05-13", "normal"),   # different state — streak stops
        ("2026-05-12", "inverted"),
        ("2026-05-11", "inverted"),
    ]
    assert count_consecutive_bdays_with_state(history, "inverted", _NO_HOLIDAYS) == 2


def test_consecutive_breaks_on_data_gap_for_business_day() -> None:
    # 2026-05-14 (Thu) is missing from history — business day with no data breaks streak
    history = [
        ("2026-05-15", "inverted"),  # Fri — present
        # Thu missing
        ("2026-05-13", "inverted"),  # Wed
    ]
    assert count_consecutive_bdays_with_state(history, "inverted", _NO_HOLIDAYS) == 1


def test_consecutive_skips_weekend_days() -> None:
    # Sat/Sun are not business days and should not break the streak
    history = [
        ("2026-05-18", "inverted"),  # Mon
        ("2026-05-15", "inverted"),  # Fri (weekend gap in between is fine)
        ("2026-05-14", "inverted"),  # Thu
    ]
    assert count_consecutive_bdays_with_state(history, "inverted", _NO_HOLIDAYS) == 3


def test_consecutive_skips_bank_holiday() -> None:
    # 2026-05-04 is a Monday bank holiday — should not break the streak
    may_bank_holiday = datetime.date(2026, 5, 4)
    history = [
        ("2026-05-05", "inverted"),  # Tue
        ("2026-05-01", "inverted"),  # Fri (Mon is a bank holiday)
    ]
    assert count_consecutive_bdays_with_state(
        history, "inverted", {may_bank_holiday}
    ) == 2


# ---------------------------------------------------------------------------
# evaluate_yield_curve_shape_signal
# ---------------------------------------------------------------------------

def test_yield_curve_unavailable_when_no_data() -> None:
    result = evaluate_yield_curve_shape_signal(
        two_y=None, five_y=None, ten_y=None, cache_date=None, history=[]
    )
    assert result.state == "unavailable"
    assert result.curve_state is None


def test_yield_curve_unavailable_when_partial_data() -> None:
    result = evaluate_yield_curve_shape_signal(
        two_y=4.0, five_y=4.3, ten_y=None, cache_date="2026-05-19", history=[]
    )
    assert result.state == "unavailable"


def test_yield_curve_stale_when_old_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since", lambda _: 6
    )
    result = evaluate_yield_curve_shape_signal(
        two_y=4.0, five_y=4.3, ten_y=4.5,
        cache_date="2026-05-10",
        history=[("2026-05-10", "normal")],
    )
    assert result.state == "stale"
    assert result.curve_state == "normal"


def test_yield_curve_quiet_when_normal(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since", lambda _: 1
    )
    history = [(f"2026-05-{d:02d}", "normal") for d in range(5, 20)]
    result = evaluate_yield_curve_shape_signal(
        two_y=4.0, five_y=4.3, ten_y=4.5,
        cache_date="2026-05-19",
        history=history,
    )
    assert result.state == "quiet"
    assert result.curve_state == "normal"


def test_yield_curve_quiet_when_inverted_but_too_short(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since", lambda _: 1
    )
    # Only 3 consecutive business days (Fri/Mon/Tue) — below persistence threshold
    history = [
        ("2026-05-19", "inverted"),  # Tue
        ("2026-05-18", "inverted"),  # Mon
        ("2026-05-15", "inverted"),  # Fri
        ("2026-05-14", "normal"),    # Thu — different state
    ]
    result = evaluate_yield_curve_shape_signal(
        two_y=4.5, five_y=4.2, ten_y=4.0,
        cache_date="2026-05-19",
        history=history,
        persistence_days=5,
    )
    assert result.state == "quiet"
    assert result.curve_state == "inverted"
    assert result.consecutive_days == 3


def test_yield_curve_warning_when_inverted_long_enough(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since", lambda _: 1
    )
    # 5 consecutive business days: Wed/Thu/Fri/Mon/Tue
    history = [
        ("2026-05-19", "inverted"),  # Tue
        ("2026-05-18", "inverted"),  # Mon
        ("2026-05-15", "inverted"),  # Fri
        ("2026-05-14", "inverted"),  # Thu
        ("2026-05-13", "inverted"),  # Wed
    ]
    result = evaluate_yield_curve_shape_signal(
        two_y=4.5, five_y=4.2, ten_y=4.0,
        cache_date="2026-05-19",
        history=history,
        persistence_days=5,
    )
    assert result.state == "warning"
    assert result.curve_state == "inverted"
    assert result.consecutive_days == 5


def test_yield_curve_spread_bps_computed_correctly(monkeypatch) -> None:
    monkeypatch.setattr(
        "investment_optimiser.equity_signals.trading_days_since", lambda _: 1
    )
    # 10y=4.5, 2y=4.0 → 10y−2y spread = 50bps
    result = evaluate_yield_curve_shape_signal(
        two_y=4.0, five_y=4.3, ten_y=4.5,
        cache_date="2026-05-19",
        history=[("2026-05-19", "normal")],
    )
    assert result.spread_bps == pytest.approx(50.0, abs=1e-6)
