from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class LPSolveResult:
    solver_status: str  # "optimal", "infeasible", "unbounded", "numerical_failure", "limit_reached"
    target_weights: dict[str, float] | None  # percentages summing to 100; None if not optimal
    binding_constraints: list[str]
    marginals: dict[str, float]
    notes: list[str]
    fallback_path: str | None


_STATUS_MAP = {
    0: "optimal",
    1: "limit_reached",
    2: "infeasible",
    3: "unbounded",
    4: "numerical_failure",
}

_FALLBACK_MAP = {
    "infeasible": "infeasible_at_constraints",
    "unbounded": "unbounded_investigate",
    "numerical_failure": "numerical_failure",
    "limit_reached": "limit_reached",
}


def solve_bucket_weights(
    baseline_weights: dict[str, float],
    current_weights: dict[str, float],
    score_coefficients: dict[str, float],
    regime_state: str,
    policy: dict[str, Any],
    *,
    bucket_scenario_sensitivities: dict[str, dict[str, float]] | None = None,
) -> LPSolveResult:
    """Solve for optimal target bucket weights using a continuous LP.

    Weights are expressed as percentages (summing to 100) in inputs and
    outputs. The LP is formulated internally in fractions (0–1 scale).

    Variables: [w_0..w_{n-1}, d_0..d_{n-1}] where d_i are auxiliary
    variables that track absolute turnover per bucket.
    """
    constraints = policy["default_constraints"]
    bucket_ids = list(baseline_weights.keys())
    n = len(bucket_ids)

    base = np.array([baseline_weights[bid] / 100.0 for bid in bucket_ids])
    cur = np.array([current_weights[bid] / 100.0 for bid in bucket_ids])
    scores = np.array([score_coefficients.get(bid, 0.0) for bid in bucket_ids])

    tilt = constraints["baseline_tilt_band_pct"] / 100.0
    min_cash = constraints["minimum_cash_mmf_pct"] / 100.0
    min_short = constraints["minimum_short_duration_pct"] / 100.0
    turnover_limit = constraints["turnover_limit_pct_by_regime"][regime_state] / 100.0

    _FLOOR_VALUES = {"liquidity_reserve": min_cash, "short_duration_nominal_gilts": min_short}
    floors = np.array([_FLOOR_VALUES.get(bid, 0.0) for bid in bucket_ids])

    lb = np.maximum(0.0, np.maximum(base - tilt, floors))
    ub = base + tilt
    bounds = list(zip(lb.tolist(), ub.tolist())) + [(0.0, None)] * n

    c = np.concatenate([-scores, np.zeros(n)])

    A_eq = np.zeros((1, 2 * n))
    A_eq[0, :n] = 1.0
    b_eq = np.array([1.0])

    A_ub_rows: list[np.ndarray] = []
    b_ub_rows: list[float] = []
    constraint_labels: list[str] = []

    for i, bid in enumerate(bucket_ids):
        row_pos = np.zeros(2 * n)
        row_pos[i] = 1.0
        row_pos[n + i] = -1.0
        A_ub_rows.append(row_pos)
        b_ub_rows.append(float(cur[i]))
        constraint_labels.append(f"turnover_upper[{bid}]")

        row_neg = np.zeros(2 * n)
        row_neg[i] = -1.0
        row_neg[n + i] = -1.0
        A_ub_rows.append(row_neg)
        b_ub_rows.append(-float(cur[i]))
        constraint_labels.append(f"turnover_lower[{bid}]")

    row_total = np.zeros(2 * n)
    row_total[n:] = 1.0
    A_ub_rows.append(row_total)
    b_ub_rows.append(turnover_limit)
    constraint_labels.append("total_turnover_limit")

    notes: list[str] = []
    scenario_floors = constraints.get("scenario_floor_pct_of_current_value", {})
    if bucket_scenario_sensitivities is not None:
        for scenario_id, floor_pct in scenario_floors.items():
            sensitivities = bucket_scenario_sensitivities.get(scenario_id)
            if sensitivities is None:
                notes.append(
                    f"Scenario floor skipped for '{scenario_id}': no sensitivities supplied."
                )
                continue
            shocks = np.array([sensitivities.get(bid, 0.0) for bid in bucket_ids])
            row_floor = np.zeros(2 * n)
            row_floor[:n] = -(1.0 + shocks)
            A_ub_rows.append(row_floor)
            b_ub_rows.append(-floor_pct / 100.0)
            constraint_labels.append(f"scenario_floor[{scenario_id}]")
    elif scenario_floors:
        notes.append(
            "Scenario floor constraints skipped: no bucket_scenario_sensitivities supplied."
        )

    A_ub = np.array(A_ub_rows)
    b_ub = np.array(b_ub_rows)

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    solver_status = _STATUS_MAP.get(res.status, "numerical_failure")

    if res.status == 3:
        res2 = linprog(
            c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds,
            method="highs", options={"presolve": False},
        )
        solver_status = _STATUS_MAP.get(res2.status, "numerical_failure")
        if res2.status == 2:
            res = res2

    if solver_status != "optimal":
        notes = [f"Solver returned: {res.message}"] + notes
        return LPSolveResult(
            solver_status=solver_status,
            target_weights=None,
            binding_constraints=[],
            marginals={},
            notes=notes,
            fallback_path=_FALLBACK_MAP.get(solver_status, solver_status),
        )

    w_opt = res.x[:n]
    target_weights = {bid: float(w_opt[i]) * 100.0 for i, bid in enumerate(bucket_ids)}

    tol = 1e-6
    binding: list[str] = []
    marginals: dict[str, float] = {}

    if hasattr(res, "ineqlin") and res.ineqlin is not None:
        for j, label in enumerate(constraint_labels):
            if abs(res.ineqlin.residual[j]) < tol:
                binding.append(label)
                if res.ineqlin.marginals is not None:
                    marginals[label] = float(res.ineqlin.marginals[j])

    if hasattr(res, "lower") and res.lower is not None:
        for i, bid in enumerate(bucket_ids):
            if abs(res.lower.residual[i]) < tol:
                label = f"lower_bound[{bid}]"
                binding.append(label)
                if res.lower.marginals is not None:
                    marginals[label] = float(res.lower.marginals[i])

    if hasattr(res, "upper") and res.upper is not None:
        for i, bid in enumerate(bucket_ids):
            if abs(res.upper.residual[i]) < tol:
                label = f"upper_bound[{bid}]"
                binding.append(label)
                if res.upper.marginals is not None:
                    marginals[label] = float(res.upper.marginals[i])

    return LPSolveResult(
        solver_status=solver_status,
        target_weights=target_weights,
        binding_constraints=binding,
        marginals=marginals,
        notes=notes,
        fallback_path=None,
    )
