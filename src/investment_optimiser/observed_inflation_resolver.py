from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# Date of the RPI-to-CPIH alignment announcement for long-dated IL gilts.
_RPI_CPIH_ALIGNMENT_DATE = date(2030, 1, 30)


@dataclass(frozen=True)
class ResolvedInflationContract:
    """Resolved pricing-state inputs for one IL gilt on one settlement date.

    Observed fields come from authoritative public data (e.g. DMO D10C).
    Forward assumption fields come from the active user-authored policy state.
    ``effective_forward_rpi_pct`` is the single-rate Fisher-equation input
    derived from the two forward assumptions weighted by the gilt's remaining
    life relative to the RPI/CPIH alignment date.
    """

    isin: str
    settlement_date: date
    maturity_date: date
    # Observed pricing-state inputs from the DMO D10C cache
    index_ratio: float
    reference_rpi: float
    observed_provider: str
    observed_as_of: str
    observed_confidence_tier: str
    is_degraded: bool
    # Forward assumptions (user-authored policy inputs)
    forward_rpi_pre_2030_pct: float
    forward_rpi_post_2030_pct: float
    # Resolved effective forward RPI for the Fisher nominal-equivalent equation
    effective_forward_rpi_pct: float


@dataclass(frozen=True)
class InflationResolutionError:
    """Returned when required inputs are absent; signals fail-closed behaviour.

    The ``warning`` field is a human-readable message suitable for inclusion in
    the handler's warning list.
    """

    isin: str
    warning: str


def _effective_forward_rpi(
    settlement_date: date,
    maturity_date: date,
    pre_2030_pct: float,
    post_2030_pct: float,
) -> float:
    """Time-weighted blend of pre- and post-2030 forward RPI assumptions.

    Cash flows before the RPI/CPIH alignment date are weighted by the
    pre-2030 assumption; cash flows after are weighted by the post-2030
    assumption.  The result is a single rate suitable for the semi-annual
    Fisher equation in ``compute_real_gry``.
    """
    if maturity_date <= _RPI_CPIH_ALIGNMENT_DATE:
        return pre_2030_pct
    if settlement_date >= _RPI_CPIH_ALIGNMENT_DATE:
        return post_2030_pct
    # Both early returns guarantee: settlement < alignment < maturity, so total_days > 0.
    total_days = (maturity_date - settlement_date).days
    pre_days = (_RPI_CPIH_ALIGNMENT_DATE - settlement_date).days
    pre_weight = pre_days / total_days
    return pre_weight * pre_2030_pct + (1.0 - pre_weight) * post_2030_pct


def resolve_il_contract(
    isin: str,
    settlement_date: date,
    maturity_date: date,
    observed_row: dict[str, Any] | None,
    forward_rpi_pre_2030_pct: float | None,
    forward_rpi_post_2030_pct: float | None,
) -> ResolvedInflationContract | InflationResolutionError:
    """Resolve observed inflation data and forward assumptions for one IL gilt.

    Returns a ``ResolvedInflationContract`` when all required inputs are
    present and valid.  Returns an ``InflationResolutionError`` (fail-closed)
    when:

    - ``observed_row`` is ``None`` (no D10C data for this ISIN)
    - either forward assumption is ``None`` or ``<= 0`` (policy inputs absent)

    The resolver is pure: it performs no database access.  Callers are
    responsible for supplying the observed row from the cache.
    """
    if observed_row is None:
        return InflationResolutionError(
            isin=isin,
            warning=(
                f"{isin}: no observed inflation data available — "
                "IL analytics skipped (run a market refresh to populate DMO D10C data)"
            ),
        )

    if forward_rpi_pre_2030_pct is None or forward_rpi_pre_2030_pct <= 0.0:
        return InflationResolutionError(
            isin=isin,
            warning=(
                f"{isin}: pre-2030 forward RPI assumption is missing or invalid — "
                "IL analytics skipped"
            ),
        )

    if forward_rpi_post_2030_pct is None or forward_rpi_post_2030_pct <= 0.0:
        return InflationResolutionError(
            isin=isin,
            warning=(
                f"{isin}: post-2030 forward RPI assumption is missing or invalid — "
                "IL analytics skipped"
            ),
        )

    effective = _effective_forward_rpi(
        settlement_date, maturity_date, forward_rpi_pre_2030_pct, forward_rpi_post_2030_pct
    )

    return ResolvedInflationContract(
        isin=isin,
        settlement_date=settlement_date,
        maturity_date=maturity_date,
        index_ratio=float(observed_row["index_ratio"]),
        reference_rpi=float(observed_row["reference_rpi"]),
        observed_provider=observed_row["provider"],
        observed_as_of=observed_row["settlement_date"],
        observed_confidence_tier=observed_row["confidence_tier"],
        is_degraded=bool(observed_row["is_degraded"]),
        forward_rpi_pre_2030_pct=forward_rpi_pre_2030_pct,
        forward_rpi_post_2030_pct=forward_rpi_post_2030_pct,
        effective_forward_rpi_pct=effective,
    )
