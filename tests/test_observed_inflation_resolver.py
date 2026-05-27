from __future__ import annotations

from datetime import date

import pytest

from investment_optimiser.observed_inflation_resolver import (
    InflationResolutionError,
    ResolvedInflationContract,
    resolve_il_contract,
)

_ISIN = "GB00BZ1NTB69"
_SETTLEMENT = date(2026, 5, 27)
_MATURITY_POST_2030 = date(2040, 11, 22)
_MATURITY_PRE_2030 = date(2028, 3, 22)

_OBSERVED_ROW = {
    "isin": _ISIN,
    "settlement_date": "2026-05-27",
    "instrument_name": "0 1/8% Index-linked Treasury Gilt 2028",
    "index_ratio": 1.46186,
    "reference_rpi": 408.2,
    "provider": "DMO_D10C",
    "fetched_at": "2026-05-27T08:00:00Z",
    "confidence_tier": "authoritative",
    "is_degraded": 0,
}


# ---------------------------------------------------------------------------
# Test 1 — Tracer bullet: happy path returns a ResolvedInflationContract
# ---------------------------------------------------------------------------

def test_resolve_returns_contract_when_all_inputs_present() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_POST_2030,
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, ResolvedInflationContract)
    assert result.isin == _ISIN
    assert result.index_ratio == pytest.approx(1.46186)
    assert result.reference_rpi == pytest.approx(408.2)
    assert result.observed_provider == "DMO_D10C"
    assert result.forward_rpi_pre_2030_pct == pytest.approx(3.0)
    assert result.forward_rpi_post_2030_pct == pytest.approx(2.5)
    assert 2.5 <= result.effective_forward_rpi_pct <= 3.0


# ---------------------------------------------------------------------------
# Test 2 — Fail-closed: no observed row
# ---------------------------------------------------------------------------

def test_resolve_fails_closed_when_observed_row_is_none() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_POST_2030,
        observed_row=None,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, InflationResolutionError)
    assert result.isin == _ISIN
    assert _ISIN in result.warning


# ---------------------------------------------------------------------------
# Test 3 — Fail-closed: pre_2030 is None
# ---------------------------------------------------------------------------

def test_resolve_fails_closed_when_pre_2030_is_none() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_POST_2030,
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=None,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, InflationResolutionError)
    assert result.isin == _ISIN


# ---------------------------------------------------------------------------
# Test 4 — Fail-closed: post_2030 is None
# ---------------------------------------------------------------------------

def test_resolve_fails_closed_when_post_2030_is_none() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_POST_2030,
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=None,
    )

    assert isinstance(result, InflationResolutionError)
    assert result.isin == _ISIN


# ---------------------------------------------------------------------------
# Test 5 — Fail-closed: pre_2030 is zero (invalid)
# ---------------------------------------------------------------------------

def test_resolve_fails_closed_when_pre_2030_is_zero() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_POST_2030,
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=0.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, InflationResolutionError)


# ---------------------------------------------------------------------------
# Test 6 — Effective RPI: gilt maturing before alignment date uses pre_2030
# ---------------------------------------------------------------------------

def test_effective_forward_rpi_uses_pre_2030_for_gilt_maturing_before_alignment() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=_SETTLEMENT,
        maturity_date=_MATURITY_PRE_2030,
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, ResolvedInflationContract)
    assert result.effective_forward_rpi_pct == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Test 7 — Effective RPI: settlement is after alignment date → post_2030 only
# ---------------------------------------------------------------------------

def test_effective_forward_rpi_uses_post_2030_when_settlement_is_after_alignment() -> None:
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=date(2031, 3, 15),
        maturity_date=date(2055, 11, 22),
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, ResolvedInflationContract)
    assert result.effective_forward_rpi_pct == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# Test 8 — Effective RPI: straddling 2030 produces a blend between pre and post
# ---------------------------------------------------------------------------

def test_effective_forward_rpi_blends_for_gilt_straddling_alignment_date() -> None:
    # Settlement May 2026, maturity Nov 2040 (~14.5 years total)
    # Pre-2030 window: May 2026 → Jan 2030 ≈ 3.7 years
    # Post-2030 window: ≈ 10.8 years
    # Expected effective rate is between pre(3.0) and post(2.5), closer to post
    result = resolve_il_contract(
        isin=_ISIN,
        settlement_date=date(2026, 5, 27),
        maturity_date=date(2040, 11, 22),
        observed_row=_OBSERVED_ROW,
        forward_rpi_pre_2030_pct=3.0,
        forward_rpi_post_2030_pct=2.5,
    )

    assert isinstance(result, ResolvedInflationContract)
    assert 2.5 < result.effective_forward_rpi_pct < 3.0
    # Closer to post_2030 because most of the gilt life is post-2030
    assert result.effective_forward_rpi_pct < 2.75
