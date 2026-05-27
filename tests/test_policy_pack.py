import json

import pytest

from investment_optimiser import policy_pack as policy_pack_module
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
        "benchmark_ticker",
        "erp_threshold_pct",
    }


def test_load_policy_pack_v1_exposes_user_facing_bucket_labels() -> None:
    policy_pack = load_policy_pack("v1")

    labels_by_id = {
        bucket["id"]: bucket["label"]
        for bucket in policy_pack["baseline_bucket_model"]["buckets"]
    }

    assert labels_by_id["listed_risk_assets"] == "Equities"
    assert (
        labels_by_id["diversifiers_and_manual"]
        == "Real Assets, Diversifiers & Other"
    )


def test_dump_policy_pack_json_is_canonical_and_round_trips() -> None:
    dumped_policy_pack = dump_policy_pack_json("v1")

    assert dumped_policy_pack.endswith("\n")
    assert json.loads(dumped_policy_pack) == load_policy_pack("v1")


def test_load_policy_pack_v2_exposes_split_forward_inflation_contract() -> None:
    policy_pack = load_policy_pack("v2")

    assert policy_pack["policy_version"] == "v2"

    fields_by_key = {
        field["key"]: field for field in policy_pack["shared_assumption_schema"]["fields"]
    }

    assert "expected_rpi_pct" not in fields_by_key
    assert fields_by_key["rpi_assumption_pre_2030_pct"]["label"] == (
        "Expected RPI assumption to January 2030"
    )
    assert fields_by_key["rpi_assumption_pre_2030_pct"]["default"] == 3.0
    assert fields_by_key["rpi_assumption_post_2030_pct"]["label"] == (
        "Expected post-2030 RPI or CPIH-aligned assumption"
    )
    assert fields_by_key["rpi_assumption_post_2030_pct"]["default"] == 3.0


def test_load_policy_pack_defaults_to_active_v2_contract() -> None:
    assert load_policy_pack()["policy_version"] == "v2"
    assert load_policy_pack("v1")["policy_version"] == "v1"


def test_load_policy_pack_reads_current_pack_contents_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            json.dumps(
                {
                    "policy_version": "v1",
                    "baseline_bucket_model": {
                        "buckets": [
                            {"id": "listed_risk_assets", "label": "Old label"}
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "policy_version": "v1",
                    "baseline_bucket_model": {
                        "buckets": [
                            {"id": "listed_risk_assets", "label": "New label"}
                        ]
                    },
                }
            ),
        ]
    )

    monkeypatch.setattr(
        policy_pack_module,
        "_read_policy_pack_text",
        lambda version: next(payloads),
    )

    first = load_policy_pack("v1")
    second = load_policy_pack("v1")

    assert first["baseline_bucket_model"]["buckets"][0]["label"] == "Old label"
    assert second["baseline_bucket_model"]["buckets"][0]["label"] == "New label"


def test_load_policy_pack_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="Unsupported policy pack version"):
        load_policy_pack("v3")
