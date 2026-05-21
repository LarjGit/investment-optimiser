from __future__ import annotations

RISK_PASS_OUTCOMES = frozenset(("pass", "not_gated", "not_evaluated"))

RISK_OUTCOME_LABELS: dict[str, str] = {
    "blocked_concentration": "Concentration",
    "blocked_maturity": "Maturity",
    "blocked_liquidity": "Liquidity",
}


def categorise_blocked_trades(
    trades: list[dict],
) -> tuple[list[dict], list[dict]]:
    friction_blocked = [t for t in trades if t["friction_outcome"] == "red"]
    risk_blocked = [
        t for t in trades
        if t["risk_outcome"] not in RISK_PASS_OUTCOMES
        and t["friction_outcome"] != "red"
    ]
    return friction_blocked, risk_blocked
