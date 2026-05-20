from investment_optimiser.bucket_assignment import SYMBOL_OVERRIDES, BucketResolution, assign_bucket


def _row(**kwargs):
    return {"symbol": "TEST", "instrument_name": "", **kwargs}


def test_plain_equity_lands_in_listed_risk_assets():
    result = assign_bucket(_row(asset_type="equity"))
    assert result.bucket_id == "listed_risk_assets"
    assert result.method == "asset_type_fallback"


def test_symbol_override_wins_over_all_other_rules():
    SYMBOL_OVERRIDES["OVERRIDE_TEST"] = "liquidity_reserve"
    try:
        result = assign_bucket(_row(symbol="OVERRIDE_TEST", asset_type="equity"))
        assert result.bucket_id == "liquidity_reserve"
        assert result.method == "override"
    finally:
        del SYMBOL_OVERRIDES["OVERRIDE_TEST"]


# --- Derived metadata ---


def test_mmf_lands_in_liquidity_reserve():
    result = assign_bucket(_row(asset_type="mmf"))
    assert result.bucket_id == "liquidity_reserve"
    assert result.method == "derived_metadata"


def test_index_linked_gilt_lands_in_index_linked_gilts():
    result = assign_bucket(_row(asset_type="gilt_index_linked"))
    assert result.bucket_id == "index_linked_gilts"
    assert result.method == "derived_metadata"


def test_short_gilt_lands_in_short_duration_bucket():
    result = assign_bucket(_row(asset_type="gilt_conventional", maturity_years=3.0))
    assert result.bucket_id == "short_duration_nominal_gilts"
    assert result.method == "derived_metadata"


def test_long_gilt_lands_in_long_duration_bucket():
    result = assign_bucket(_row(asset_type="gilt_conventional", maturity_years=10.0))
    assert result.bucket_id == "long_duration_nominal_gilts"
    assert result.method == "derived_metadata"


def test_gilt_without_maturity_falls_back_to_long_duration():
    result = assign_bucket(_row(asset_type="gilt_conventional"))
    assert result.bucket_id == "long_duration_nominal_gilts"


# --- Name keywords ---


def test_equity_etf_lands_in_listed_risk_assets():
    result = assign_bucket(_row(asset_type="etf", instrument_name="iShares Core MSCI World ETF"))
    assert result.bucket_id == "listed_risk_assets"


def test_gilt_etf_does_not_land_in_listed_risk_assets():
    result = assign_bucket(_row(asset_type="etf", instrument_name="Vanguard UK Gilt ETF"))
    assert result.bucket_id != "listed_risk_assets"
    assert result.method == "name_keywords"


def test_equity_fund_lands_in_listed_risk_assets_via_keywords():
    result = assign_bucket(_row(asset_type="fund", instrument_name="Vanguard FTSE All-World Equity Fund"))
    assert result.bucket_id == "listed_risk_assets"
    assert result.method == "name_keywords"


def test_property_fund_lands_in_diversifiers():
    result = assign_bucket(_row(asset_type="fund", instrument_name="M&G Property Portfolio"))
    assert result.bucket_id == "diversifiers_and_manual"
    assert result.method == "name_keywords"


def test_infrastructure_investment_trust_lands_in_diversifiers():
    result = assign_bucket(_row(asset_type="investment_trust", instrument_name="3i Infrastructure plc"))
    assert result.bucket_id == "diversifiers_and_manual"
    assert result.method == "name_keywords"


def test_gold_etc_lands_in_diversifiers():
    result = assign_bucket(_row(asset_type="etf", instrument_name="iShares Physical Gold ETC"))
    assert result.bucket_id == "diversifiers_and_manual"
    assert result.method == "name_keywords"


# --- Remaining asset-type fallbacks ---


def test_reit_lands_in_diversifiers():
    result = assign_bucket(_row(asset_type="reit"))
    assert result.bucket_id == "diversifiers_and_manual"


def test_other_lands_in_diversifiers():
    result = assign_bucket(_row(asset_type="other"))
    assert result.bucket_id == "diversifiers_and_manual"
