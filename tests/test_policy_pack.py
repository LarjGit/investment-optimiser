import json

import pytest

from investment_optimiser.policy_pack import dump_policy_pack_json, load_policy_pack


def test_load_policy_pack_v1_exposes_frozen_contract() -> None:
    policy_pack = load_policy_pack("v1")

    assert policy_pack["policy_version"] == "v1"
    assert policy_pack["scenario_set_name"] == "v1"
    assert "baseline_bucket_model" in policy_pack
    assert "named_scenarios" in policy_pack
    assert "default_constraints" in policy_pack
    assert "shared_assumption_schema" in policy_pack

    assumption_keys = {
        field["key"] for field in policy_pack["shared_assumption_schema"]["fields"]
    }

    assert assumption_keys == {
        "active_scenario",
        "scenario_magnitude",
        "gry_improvement_threshold_bps",
        "duration_floor_years",
        "duration_ceiling_years",
        "liquidity_concentration_10y_plus_pct",
        "max_maturity_years",
        "max_single_position_pct",
        "minimum_cash_mmf_pct",
        "minimum_short_duration_pct",
        "expected_rpi_pct",
        "interactive_investor_trade_fee_gbp",
        "expected_hold_period_years",
        "spread_bps_by_friction_class",
    }


def test_dump_policy_pack_json_is_canonical_and_round_trips() -> None:
    dumped_policy_pack = dump_policy_pack_json("v1")

    assert dumped_policy_pack.endswith("\n")
    assert json.loads(dumped_policy_pack) == load_policy_pack("v1")


def test_load_policy_pack_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="Unsupported policy pack version"):
        load_policy_pack("v2")
