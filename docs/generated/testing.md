<!--
generated_by: repodocs/0.1.0
output_id: testing-md
output_purpose: reference
primary_audience: reviewer
ownership_class: generated
engine_version: 0.1.0
renderer_version: testing-markdown-v1
last_run_id: dd8bc596-c35a-4962-b1bb-775fba14bbab
-->

# Testing

This file summarizes stored test inventory facts from repodocs, then preserves the grounded per-file inventory and target-link distinctions.

## Testing Summary

- 468 stored test facts across 37 test files.
- 423 runnable test items: 0 linked, 423 unlinked.
- Inventory includes 8 class collectors when present in stored facts.

## Linked Targets

No runnable test items were linked to stored targets.

## File Inventory


### `tests/test_allocation_runs.py`

- `tests/test_allocation_runs.py` - file-level test container
- `tests/test_allocation_runs.py::test_dump_allocation_run_snapshot_json_is_canonical_and_round_trips` — no target link
- `tests/test_allocation_runs.py::test_insert_allocation_run_rejects_mismatched_scalar_metadata` — no target link
- `tests/test_allocation_runs.py::test_insert_and_fetch_allocation_run_round_trips` — no target link

### `tests/test_allocation_view.py`

- `tests/test_allocation_view.py` - file-level test container
- `tests/test_allocation_view.py::test_all_six_buckets_always_present` — no target link
- `tests/test_allocation_view.py::test_bucket_labels_mapped_correctly` — no target link
- `tests/test_allocation_view.py::test_certain_classification_not_flagged` — no target link
- `tests/test_allocation_view.py::test_current_pct_computed_from_market_value` — no target link
- `tests/test_allocation_view.py::test_drift_is_current_minus_baseline` — no target link
- `tests/test_allocation_view.py::test_empty_bucket_has_zero_current_pct` — no target link
- `tests/test_allocation_view.py::test_empty_holdings_gives_all_zero_current` — no target link
- `tests/test_allocation_view.py::test_keyword_classification_flagged_as_uncertain` — no target link
- `tests/test_allocation_view.py::test_long_gilt_classified_from_maturity_date` — no target link
- `tests/test_allocation_view.py::test_short_gilt_classified_from_maturity_date` — no target link

### `tests/test_app_smoke.py`

- `tests/test_app_smoke.py` - file-level test container
- `tests/test_app_smoke.py::test_app_boots_into_tab_shell_and_runs_migrations` — no target link
- `tests/test_app_smoke.py::test_app_uploads_csv_and_immediately_updates_authoritative_snapshot` — no target link
- `tests/test_app_smoke.py::test_app_uses_split_forward_inflation_sidebar_controls` — no target link
- `tests/test_app_smoke.py::test_portfolio_tab_prefers_most_recently_fetched_equity_price_row` — no target link
- `tests/test_app_smoke.py::test_portfolio_tab_reads_persisted_non_gilt_prices_from_equity_cache` — no target link
- `tests/test_app_smoke.py::test_portfolio_tab_renders_kpis_from_latest_persisted_snapshot` — no target link
- `tests/test_app_smoke.py::test_portfolio_tab_shows_last_successful_market_refresh_after_failure` — no target link
- `tests/test_app_smoke.py::test_signals_tab_renders_gilt_ranking_with_seeded_analytics` — no target link

### `tests/test_blocked_trade_explanations.py`

- `tests/test_blocked_trade_explanations.py` - file-level test container
- `tests/test_blocked_trade_explanations.py::test_all_risk_block_outcomes_categorised_correctly` — no target link
- `tests/test_blocked_trade_explanations.py::test_empty_input_returns_empty_lists` — no target link
- `tests/test_blocked_trade_explanations.py::test_friction_blocked_trade_goes_to_friction_list` — no target link
- `tests/test_blocked_trade_explanations.py::test_friction_blocked_trade_not_duplicated_in_risk_list` — no target link
- `tests/test_blocked_trade_explanations.py::test_multiple_friction_and_risk_blocks_separated` — no target link
- `tests/test_blocked_trade_explanations.py::test_no_blocked_trades_returns_empty_lists` — no target link
- `tests/test_blocked_trade_explanations.py::test_risk_blocked_trade_goes_to_risk_list` — no target link

### `tests/test_boe.py`

- `tests/test_boe.py` - file-level test container
- `tests/test_boe.py::test_boe_handler_handles_empty_response_without_error` — no target link
- `tests/test_boe.py::test_boe_handler_inserts_rows_for_each_series_and_date` — no target link
- `tests/test_boe.py::test_boe_handler_propagates_http_error` — no target link
- `tests/test_boe.py::test_boe_handler_skips_missing_values_without_error` — no target link

### `tests/test_bucket_assignment.py`

- `tests/test_bucket_assignment.py` - file-level test container
- `tests/test_bucket_assignment.py::test_equity_etf_lands_in_listed_risk_assets` — no target link
- `tests/test_bucket_assignment.py::test_equity_fund_lands_in_listed_risk_assets_via_keywords` — no target link
- `tests/test_bucket_assignment.py::test_gilt_etf_does_not_land_in_listed_risk_assets` — no target link
- `tests/test_bucket_assignment.py::test_gilt_without_maturity_falls_back_to_long_duration` — no target link
- `tests/test_bucket_assignment.py::test_gold_etc_lands_in_diversifiers` — no target link
- `tests/test_bucket_assignment.py::test_index_linked_gilt_lands_in_index_linked_gilts` — no target link
- `tests/test_bucket_assignment.py::test_infrastructure_investment_trust_lands_in_diversifiers` — no target link
- `tests/test_bucket_assignment.py::test_long_gilt_lands_in_long_duration_bucket` — no target link
- `tests/test_bucket_assignment.py::test_mmf_lands_in_liquidity_reserve` — no target link
- `tests/test_bucket_assignment.py::test_other_lands_in_diversifiers` — no target link
- `tests/test_bucket_assignment.py::test_plain_equity_lands_in_listed_risk_assets` — no target link
- `tests/test_bucket_assignment.py::test_property_fund_lands_in_diversifiers` — no target link
- `tests/test_bucket_assignment.py::test_reit_lands_in_diversifiers` — no target link
- `tests/test_bucket_assignment.py::test_short_gilt_lands_in_short_duration_bucket` — no target link
- `tests/test_bucket_assignment.py::test_symbol_override_wins_over_all_other_rules` — no target link

### `tests/test_cash_allocator.py`

- `tests/test_cash_allocator.py` - file-level test container
- `tests/test_cash_allocator.py::test_build_cash_run_record_passes_validation` — no target link
- `tests/test_cash_allocator.py::test_build_cash_run_record_solver_status` — no target link
- `tests/test_cash_allocator.py::test_deployment_dicts_have_required_keys` — no target link
- `tests/test_cash_allocator.py::test_deployments_proportional_to_gap` — no target link
- `tests/test_cash_allocator.py::test_deployments_sum_to_excess` — no target link
- `tests/test_cash_allocator.py::test_empty_holdings_no_excess` — no target link
- `tests/test_cash_allocator.py::test_excess_cash_computed_correctly` — no target link
- `tests/test_cash_allocator.py::test_excess_larger_than_total_gap_fills_gaps_then_distributes_remainder` — no target link
- `tests/test_cash_allocator.py::test_missing_liquidity_reserve_key_raises` — no target link
- `tests/test_cash_allocator.py::test_no_excess_when_cash_at_target` — no target link
- `tests/test_cash_allocator.py::test_no_excess_when_cash_below_target` — no target link
- `tests/test_cash_allocator.py::test_over_target_bucket_receives_nothing` — no target link

### `tests/test_constraint_explanations.py`

- `tests/test_constraint_explanations.py` - file-level test container
- `tests/test_constraint_explanations.py::test_empty_input_returns_empty_list` — no target link
- `tests/test_constraint_explanations.py::test_lower_bound_references_bucket_label_and_floor` — no target link
- `tests/test_constraint_explanations.py::test_marginal_above_threshold_is_binding` — no target link
- `tests/test_constraint_explanations.py::test_marginal_at_threshold_is_near_binding` — no target link
- `tests/test_constraint_explanations.py::test_missing_marginal_gives_none_shadow_price_and_near_binding` — no target link
- `tests/test_constraint_explanations.py::test_scenario_floor_references_scenario_name` — no target link
- `tests/test_constraint_explanations.py::test_total_turnover_limit_binding` — no target link
- `tests/test_constraint_explanations.py::test_turnover_upper_references_bucket` — no target link
- `tests/test_constraint_explanations.py::test_unknown_label_falls_back_gracefully` — no target link
- `tests/test_constraint_explanations.py::test_upper_bound_references_bucket_label_and_tilt` — no target link

### `tests/test_decision_log.py`

- `tests/test_decision_log.py` - file-level test container
- `tests/test_decision_log.py::test_insert_decision_round_trip` — no target link
- `tests/test_decision_log.py::test_newest_first_ordering` — no target link
- `tests/test_decision_log.py::test_signal_event_id_nullable` — no target link

### `tests/test_dmo.py`

- `tests/test_dmo.py` - file-level test container
- `tests/test_dmo.py::test_dmo_handler_excludes_3month_il_gilt` — no target link
- `tests/test_dmo.py::test_dmo_handler_inserts_correct_rows` — no target link
- `tests/test_dmo.py::test_dmo_handler_preserves_tidm_on_second_run` — no target link
- `tests/test_dmo.py::test_dmo_handler_propagates_http_error` — no target link
- `tests/test_dmo.py::test_dmo_handler_replaces_all_rows_on_second_run` — no target link
- `tests/test_dmo.py::test_dmo_handler_skips_row_with_unparseable_coupon` — no target link
- `tests/test_dmo.py::test_normalize_type_accepts_3_month_lag` — no target link
- `tests/test_dmo.py::test_normalize_type_accepts_8_month_lag` — no target link
- `tests/test_dmo.py::test_normalize_type_accepts_conventional` — no target link
- `tests/test_dmo.py::test_normalize_type_rejects_unknown` — no target link
- `tests/test_dmo.py::test_parse_coupon_ascii_fraction` — no target link
- `tests/test_dmo.py::test_parse_coupon_ascii_fraction_zero_integer` — no target link
- `tests/test_dmo.py::test_parse_coupon_pure_vulgar_fraction` — no target link
- `tests/test_dmo.py::test_parse_coupon_returns_none_when_no_coupon` — no target link
- `tests/test_dmo.py::test_parse_coupon_unicode_vulgar_fraction_with_integer` — no target link
- `tests/test_dmo.py::test_parse_coupon_whole_number` — no target link
- `tests/test_dmo.py::test_parse_dividend_dates_empty_returns_none` — no target link
- `tests/test_dmo.py::test_parse_dividend_dates_garbled_returns_none` — no target link
- `tests/test_dmo.py::test_parse_dividend_dates_jan_jul` — no target link
- `tests/test_dmo.py::test_parse_dividend_dates_mar_sep` — no target link

### `tests/test_dmo_d10c.py`

- `tests/test_dmo_d10c.py` - file-level test container
- `tests/test_dmo_d10c.py::test_dmo_d10c_handler_error_envelope_raises` — no target link
- `tests/test_dmo_d10c.py::test_dmo_d10c_handler_idempotent_rerun` — no target link
- `tests/test_dmo_d10c.py::test_dmo_d10c_handler_inserts_rows` — no target link
- `tests/test_dmo_d10c.py::test_dmo_d10c_handler_multi_date_stores_all_rows` — no target link
- `tests/test_dmo_d10c.py::test_dmo_d10c_handler_propagates_http_error` — no target link
- `tests/test_dmo_d10c.py::test_get_freshness_returns_correct_metadata` — no target link
- `tests/test_dmo_d10c.py::test_get_freshness_returns_none_when_empty` — no target link
- `tests/test_dmo_d10c.py::test_get_latest_observed_inflation_returns_one_row_per_isin` — no target link

### `tests/test_duration_liquidity_signals.py`

- `tests/test_duration_liquidity_signals.py` - file-level test container
- `tests/test_duration_liquidity_signals.py::test_concentration_counts_10y_plus_correctly` — no target link
- `tests/test_duration_liquidity_signals.py::test_degraded_when_all_analytics_missing` — no target link
- `tests/test_duration_liquidity_signals.py::test_degraded_when_any_analytics_missing` — no target link
- `tests/test_duration_liquidity_signals.py::test_fetch_returns_empty_when_no_gilt_holdings` — no target link
- `tests/test_duration_liquidity_signals.py::test_fetch_returns_gilt_rows_with_analytics` — no target link
- `tests/test_duration_liquidity_signals.py::test_fetch_returns_null_analytics_when_cache_missing` — no target link
- `tests/test_duration_liquidity_signals.py::test_fetch_scopes_to_latest_snapshot_date` — no target link
- `tests/test_duration_liquidity_signals.py::test_quiet_when_within_all_thresholds` — no target link
- `tests/test_duration_liquidity_signals.py::test_signal_exposes_gilt_count` — no target link
- `tests/test_duration_liquidity_signals.py::test_signal_exposes_thresholds` — no target link
- `tests/test_duration_liquidity_signals.py::test_triggered_when_concentration_above_threshold` — no target link
- `tests/test_duration_liquidity_signals.py::test_triggered_when_duration_above_ceiling` — no target link
- `tests/test_duration_liquidity_signals.py::test_triggered_when_duration_below_floor` — no target link
- `tests/test_duration_liquidity_signals.py::test_unavailable_when_no_gilt_rows` — no target link
- `tests/test_duration_liquidity_signals.py::test_weighted_average_duration_correct` — no target link

### `tests/test_equity_opportunity.py`

- `tests/test_equity_opportunity.py` - file-level test container
- `tests/test_equity_opportunity.py::test_composite_score_bounded_0_to_1` — no target link
- `tests/test_equity_opportunity.py::test_degraded_with_two_components` — no target link
- `tests/test_equity_opportunity.py::test_drawdown_component_stored_on_signal` — no target link
- `tests/test_equity_opportunity.py::test_erp_component_stored_on_signal` — no target link
- `tests/test_equity_opportunity.py::test_explanation_is_non_empty` — no target link
- `tests/test_equity_opportunity.py::test_high_score_state_is_attractive_or_better` — no target link
- `tests/test_equity_opportunity.py::test_low_score_state_is_neutral_or_modest` — no target link
- `tests/test_equity_opportunity.py::test_not_degraded_with_all_three_components` — no target link
- `tests/test_equity_opportunity.py::test_score_to_opportunity_band_attractive` — no target link
- `tests/test_equity_opportunity.py::test_score_to_opportunity_band_highly_attractive` — no target link
- `tests/test_equity_opportunity.py::test_score_to_opportunity_band_modest` — no target link
- `tests/test_equity_opportunity.py::test_score_to_opportunity_band_neutral` — no target link
- `tests/test_equity_opportunity.py::test_trend_dampener_applied_in_persistent_bear_market` — no target link
- `tests/test_equity_opportunity.py::test_trend_dampener_is_1_in_rising_market` — no target link
- `tests/test_equity_opportunity.py::test_trend_dampener_is_1_when_insufficient_price_history` — no target link
- `tests/test_equity_opportunity.py::test_unavailable_explanation_mentions_missing_data` — no target link
- `tests/test_equity_opportunity.py::test_unavailable_when_no_data` — no target link
- `tests/test_equity_opportunity.py::test_unavailable_when_only_one_component` — no target link
- `tests/test_equity_opportunity.py::test_valuation_component_stored_on_signal` — no target link

### `tests/test_equity_signals.py`

- `tests/test_equity_signals.py` - file-level test container
- `tests/test_equity_signals.py::test_classify_flat_when_spread_within_threshold` — no target link
- `tests/test_equity_signals.py::test_classify_humped_when_five_year_is_local_peak` — no target link
- `tests/test_equity_signals.py::test_classify_inverted_when_spread_below_negative_threshold` — no target link
- `tests/test_equity_signals.py::test_classify_normal_not_humped_when_ten_year_also_high` — no target link
- `tests/test_equity_signals.py::test_classify_normal_when_spread_above_threshold` — no target link
- `tests/test_equity_signals.py::test_classify_respects_custom_threshold` — no target link
- `tests/test_equity_signals.py::test_consecutive_breaks_on_data_gap_for_business_day` — no target link
- `tests/test_equity_signals.py::test_consecutive_breaks_on_different_state` — no target link
- `tests/test_equity_signals.py::test_consecutive_counts_matching_streak` — no target link
- `tests/test_equity_signals.py::test_consecutive_returns_zero_for_empty_history` — no target link
- `tests/test_equity_signals.py::test_consecutive_skips_bank_holiday` — no target link
- `tests/test_equity_signals.py::test_consecutive_skips_weekend_days` — no target link
- `tests/test_equity_signals.py::test_not_stale_at_exactly_five_trading_days` — no target link
- `tests/test_equity_signals.py::test_quiet_when_erp_above_threshold` — no target link
- `tests/test_equity_signals.py::test_stale_when_data_older_than_five_trading_days` — no target link
- `tests/test_equity_signals.py::test_unavailable_when_best_gry_is_none` — no target link
- `tests/test_equity_signals.py::test_unavailable_when_cache_date_is_none` — no target link
- `tests/test_equity_signals.py::test_unavailable_when_pe_ratio_is_none` — no target link
- `tests/test_equity_signals.py::test_warning_respects_custom_threshold` — no target link
- `tests/test_equity_signals.py::test_warning_when_erp_below_threshold` — no target link
- `tests/test_equity_signals.py::test_yield_curve_quiet_when_inverted_but_too_short` — no target link
- `tests/test_equity_signals.py::test_yield_curve_quiet_when_normal` — no target link
- `tests/test_equity_signals.py::test_yield_curve_spread_bps_computed_correctly` — no target link
- `tests/test_equity_signals.py::test_yield_curve_stale_when_old_data` — no target link
- `tests/test_equity_signals.py::test_yield_curve_unavailable_when_no_data` — no target link
- `tests/test_equity_signals.py::test_yield_curve_unavailable_when_partial_data` — no target link
- `tests/test_equity_signals.py::test_yield_curve_warning_when_inverted_long_enough` — no target link

### `tests/test_friction_gate.py`

- `tests/test_friction_gate.py` - file-level test container
- `tests/test_friction_gate.py::test_break_even_estimate_amber` — no target link
- `tests/test_friction_gate.py::test_break_even_estimate_green` — no target link
- `tests/test_friction_gate.py::test_break_even_estimate_negative_gap` — no target link
- `tests/test_friction_gate.py::test_break_even_estimate_red` — no target link
- `tests/test_friction_gate.py::test_break_even_estimate_zero_gap` — no target link
- `tests/test_friction_gate.py::test_break_even_is_none_when_yield_improvement_is_negative` — no target link
- `tests/test_friction_gate.py::test_break_even_is_none_when_yield_improvement_is_none` — no target link
- `tests/test_friction_gate.py::test_break_even_is_none_when_yield_improvement_is_zero` — no target link
- `tests/test_friction_gate.py::test_equity_buy_friction_cost` — no target link
- `tests/test_friction_gate.py::test_equity_buy_has_stamp_duty_of_half_percent` — no target link
- `tests/test_friction_gate.py::test_equity_routes_to_equities_and_investment_trusts` — no target link
- `tests/test_friction_gate.py::test_etf_routes_to_equities_and_investment_trusts` — no target link
- `tests/test_friction_gate.py::test_gate_is_amber_when_break_even_between_12_and_24_months` — no target link
- `tests/test_friction_gate.py::test_gate_is_green_when_break_even_under_12_months` — no target link
- `tests/test_friction_gate.py::test_gate_is_red_when_break_even_over_24_months` — no target link
- `tests/test_friction_gate.py::test_gate_trades_mixed_portfolio` — no target link
- `tests/test_friction_gate.py::test_gilt_buy_break_even_months` — no target link
- `tests/test_friction_gate.py::test_gilt_buy_friction_cost` — no target link
- `tests/test_friction_gate.py::test_gilt_buy_has_zero_stamp_duty` — no target link
- `tests/test_friction_gate.py::test_gilt_conventional_routes_to_conventional_gilts` — no target link
- `tests/test_friction_gate.py::test_gilt_index_linked_routes_to_index_linked_gilts` — no target link
- `tests/test_friction_gate.py::test_green_buy_proposed_value_is_not_reverted` — no target link
- `tests/test_friction_gate.py::test_mmf_routes_to_cash_and_mmf` — no target link
- `tests/test_friction_gate.py::test_none_asset_type_routes_to_equities_and_investment_trusts` — no target link
- `tests/test_friction_gate.py::test_red_buy_creates_liquidity_reserve_when_absent` — no target link
- `tests/test_friction_gate.py::test_red_buy_reverts_to_current_value_and_liquidity_absorbs_delta` — no target link
- `tests/test_friction_gate.py::test_sell_trade_has_gate_outcome_not_gated` — no target link

### `tests/test_gilt_analytics.py`

- `tests/test_gilt_analytics.py` - file-level test container
- `tests/test_gilt_analytics.py::test_compute_gry_final_period_gilt` — no target link
- `tests/test_gilt_analytics.py::test_compute_gry_returns_none_on_impossible_price` — no target link
- `tests/test_gilt_analytics.py::test_compute_gry_standard_coupon_gilt` — no target link
- `tests/test_gilt_analytics.py::test_compute_real_gry_negative_real_yield` — no target link
- `tests/test_gilt_analytics.py::test_compute_real_gry_par_il_gilt` — no target link
- `tests/test_gilt_analytics.py::test_compute_real_gry_returns_none_on_impossible_price` — no target link
- `tests/test_gilt_analytics.py::test_fisher_conversion` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_derives_lse_benchmark_yields` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_fills_in_null_analytics` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_fills_nominal_equivalent_for_il_gilt_with_observed_data` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_returns_warning_on_failed_solve` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_skips_already_solved_rows` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_skips_benchmark_when_no_gry_rows` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_skips_il_gilts_when_forward_assumptions_absent` — no target link
- `tests/test_gilt_analytics.py::test_gilt_analytics_handler_warns_on_il_gilt_missing_from_observed_cache` — no target link
- `tests/test_gilt_analytics.py::test_il_exclusion_reason_cleared_when_analytics_succeed` — no target link
- `tests/test_gilt_analytics.py::test_il_exclusion_reason_distinct_when_forward_assumptions_absent` — no target link
- `tests/test_gilt_analytics.py::test_il_exclusion_reason_written_when_observed_data_missing` — no target link
- `tests/test_gilt_analytics.py::test_il_gilt_analytics_handler_fills_real_gry_when_rpi_present` — no target link
- `tests/test_gilt_analytics.py::test_il_gilt_analytics_handler_skips_il_gilts_when_no_rpi` — no target link

### `tests/test_gilt_signals.py`

- `tests/test_gilt_signals.py` - file-level test container
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_empty_falls_back_to_ttm` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_long_title_case` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_lowercase` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_medium_title_case` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_none_falls_back_to_ttm` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_short_title_case` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_ultra_short_space_variant` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_ultra_short_title_case` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_dmo_unknown_falls_back_to_ttm` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_just_over_15y` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_just_over_5y` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_long_by_ttm` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_medium_by_ttm` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_null_maturity_returns_short` — no target link
- `tests/test_gilt_signals.py::test_assign_bracket_short_by_ttm` — no target link
- `tests/test_gilt_signals.py::test_build_universe_empty_reference_returns_empty` — no target link
- `tests/test_gilt_signals.py::test_build_universe_fully_priced_gilt_no_warnings` — no target link
- `tests/test_gilt_signals.py::test_build_universe_includes_il_gilt_when_nominal_equivalent_gry_is_set` — no target link
- `tests/test_gilt_signals.py::test_build_universe_index_linked_always_excluded` — no target link
- `tests/test_gilt_signals.py::test_build_universe_maturity_cutoff_excludes_gilt_with_warning` — no target link
- `tests/test_gilt_signals.py::test_build_universe_multiple_warnings_combined` — no target link
- `tests/test_gilt_signals.py::test_build_universe_price_only_gilt_in_frame_with_analytics_warning` — no target link
- `tests/test_gilt_signals.py::test_build_universe_sorted_gry_descending_nulls_last` — no target link
- `tests/test_gilt_signals.py::test_build_universe_unpriced_gilt_excluded_with_warning` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_excludes_index_linked_gilts` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_includes_il_gilts_when_nominal_equivalent_gry_is_set` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_includes_instrument_name_from_reference` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_nulls_sort_to_bottom` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_returns_empty_dataframe_when_cache_is_empty` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_returns_rows_sorted_by_gry_descending` — no target link
- `tests/test_gilt_signals.py::test_fetch_gilt_ranking_scopes_to_latest_cache_date` — no target link

### `tests/test_gilt_switch_table.py`

- `tests/test_gilt_switch_table.py` - file-level test container
- `tests/test_gilt_switch_table.py::test_already_best_when_gap_at_threshold` — no target link
- `tests/test_gilt_switch_table.py::test_already_best_when_no_other_gilts_in_bracket` — no target link
- `tests/test_gilt_switch_table.py::test_held_gilt_not_considered_as_its_own_best_alternative` — no target link
- `tests/test_gilt_switch_table.py::test_held_gilt_skipped_when_no_bid_offer` — no target link
- `tests/test_gilt_switch_table.py::test_il_gilt_excluded_from_rows` — no target link
- `tests/test_gilt_switch_table.py::test_multiple_held_gilts_in_different_brackets` — no target link
- `tests/test_gilt_switch_table.py::test_position_in_row` — no target link
- `tests/test_gilt_switch_table.py::test_position_none_when_no_held_values` — no target link
- `tests/test_gilt_switch_table.py::test_returns_empty_when_df_is_empty` — no target link
- `tests/test_gilt_switch_table.py::test_returns_empty_when_no_held_isins` — no target link
- `tests/test_gilt_switch_table.py::test_spread_calculated_from_bid_offer` — no target link
- `tests/test_gilt_switch_table.py::test_switch_opportunity_above_threshold` — no target link

### `tests/test_holdings_translator.py`

- `tests/test_holdings_translator.py` - file-level test container
- `tests/test_holdings_translator.py::test_bucket_absent_from_targets_passes_through_unchanged` — no target link
- `tests/test_holdings_translator.py::test_empty_long_gilt_bucket_picks_highest_gry_candidate` — no target link
- `tests/test_holdings_translator.py::test_empty_non_gilt_bucket_emits_warning_and_sentinel` — no target link
- `tests/test_holdings_translator.py::test_empty_short_gilt_bucket_picks_candidate_within_five_years` — no target link
- `tests/test_holdings_translator.py::test_full_exit_when_target_zero` — no target link
- `tests/test_holdings_translator.py::test_output_dataframe_has_required_columns` — no target link
- `tests/test_holdings_translator.py::test_proportional_scaling_preserves_relative_weights` — no target link

### `tests/test_lp_solver.py`

- `tests/test_lp_solver.py` - file-level test container
- `tests/test_lp_solver.py::test_binding_constraints_reported_when_tilt_band_is_tight` — no target link
- `tests/test_lp_solver.py::test_feasible_returns_optimal_status` — no target link
- `tests/test_lp_solver.py::test_feasible_weights_are_long_only` — no target link
- `tests/test_lp_solver.py::test_feasible_weights_contain_all_bucket_ids` — no target link
- `tests/test_lp_solver.py::test_feasible_weights_sum_to_100` — no target link
- `tests/test_lp_solver.py::test_infeasible_when_floors_exceed_100` — no target link
- `tests/test_lp_solver.py::test_minimum_cash_floor_is_respected` — no target link
- `tests/test_lp_solver.py::test_minimum_short_duration_floor_is_respected` — no target link
- `tests/test_lp_solver.py::test_returns_lp_solve_result` — no target link
- `tests/test_lp_solver.py::test_scenario_floor_enforced_when_sensitivities_provided` — no target link
- `tests/test_lp_solver.py::test_scenario_sensitivities_accepted_without_error` — no target link
- `tests/test_lp_solver.py::test_score_tilts_weights_toward_preferred_bucket` — no target link
- `tests/test_lp_solver.py::test_turnover_limit_constrains_large_shift` — no target link

### `tests/test_lse_gilt_prices.py`

- `tests/test_lse_gilt_prices.py` - file-level test container
- `tests/test_lse_gilt_prices.py::test_gilt_price_cache_allows_price_rows_before_analytics_exist` — no target link
- `tests/test_lse_gilt_prices.py::test_lse_gilt_prices_handler_continues_after_per_instrument_failure` — no target link
- `tests/test_lse_gilt_prices.py::test_lse_gilt_prices_handler_persists_price_rows_for_known_gilts` — no target link
- `tests/test_lse_gilt_prices.py::test_lse_gilt_prices_handler_rejects_partial_snapshot_below_50_pct` — no target link

### `tests/test_narrative_explanation.py`

- `tests/test_narrative_explanation.py` - file-level test container
- `tests/test_narrative_explanation.py::test_approved_trades_returned` — no target link
- `tests/test_narrative_explanation.py::test_binding_constraints_read_from_diagnostics` — no target link
- `tests/test_narrative_explanation.py::test_empty_binding_constraint_details_returns_empty` — no target link
- `tests/test_narrative_explanation.py::test_empty_snapshot_returns_empty_collections` — no target link
- `tests/test_narrative_explanation.py::test_friction_blocked_separated` — no target link
- `tests/test_narrative_explanation.py::test_friction_blocked_takes_priority_over_risk` — no target link
- `tests/test_narrative_explanation.py::test_missing_diagnostics_key_returns_empty_constraints` — no target link
- `tests/test_narrative_explanation.py::test_no_prior_snapshot_headline_and_deltas_are_none` — no target link
- `tests/test_narrative_explanation.py::test_not_gated_sell_trade_is_approved` — no target link
- `tests/test_narrative_explanation.py::test_risk_blocked_separated` — no target link
- `tests/test_narrative_explanation.py::test_with_prior_snapshot_allocation_deltas_populated` — no target link
- `tests/test_narrative_explanation.py::test_with_prior_snapshot_headline_value_delta` — no target link
- `tests/test_narrative_explanation.py::test_with_prior_snapshot_no_change_returns_empty_deltas` — no target link

### `tests/test_non_gilt_reference.py`

- `tests/test_non_gilt_reference.py` - file-level test container
- `tests/test_non_gilt_reference.py::test_non_gilt_reference_handler_classifies_mutualfund_as_fund` — no target link
- `tests/test_non_gilt_reference.py::test_non_gilt_reference_handler_classifies_via_yahoo_quote_type` — no target link
- `tests/test_non_gilt_reference.py::test_non_gilt_reference_handler_falls_back_to_name_heuristic_when_yahoo_returns_empty` — no target link
- `tests/test_non_gilt_reference.py::test_non_gilt_reference_handler_reclassifies_existing_snapshot_rows` — no target link

### `tests/test_observed_inflation_resolver.py`

- `tests/test_observed_inflation_resolver.py` - file-level test container
- `tests/test_observed_inflation_resolver.py::test_effective_forward_rpi_blends_for_gilt_straddling_alignment_date` — no target link
- `tests/test_observed_inflation_resolver.py::test_effective_forward_rpi_uses_post_2030_when_settlement_is_after_alignment` — no target link
- `tests/test_observed_inflation_resolver.py::test_effective_forward_rpi_uses_pre_2030_for_gilt_maturing_before_alignment` — no target link
- `tests/test_observed_inflation_resolver.py::test_resolve_fails_closed_when_observed_row_is_none` — no target link
- `tests/test_observed_inflation_resolver.py::test_resolve_fails_closed_when_post_2030_is_none` — no target link
- `tests/test_observed_inflation_resolver.py::test_resolve_fails_closed_when_pre_2030_is_none` — no target link
- `tests/test_observed_inflation_resolver.py::test_resolve_fails_closed_when_pre_2030_is_zero` — no target link
- `tests/test_observed_inflation_resolver.py::test_resolve_returns_contract_when_all_inputs_present` — no target link

### `tests/test_policy_pack.py`

- `tests/test_policy_pack.py` - file-level test container
- `tests/test_policy_pack.py::test_dump_policy_pack_json_is_canonical_and_round_trips` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_defaults_to_active_v2_contract` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_reads_current_pack_contents_each_time` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_rejects_unknown_version` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_v1_exposes_frozen_contract` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_v1_exposes_user_facing_bucket_labels` — no target link
- `tests/test_policy_pack.py::test_load_policy_pack_v2_exposes_split_forward_inflation_contract` — no target link

### `tests/test_portfolio_import.py`

- `tests/test_portfolio_import.py` - file-level test container
- `tests/test_portfolio_import.py::test_gilt_maturity_date_stored_and_round_trips` — no target link
- `tests/test_portfolio_import.py::test_import_ii_portfolio_snapshot_classifies_assets_and_persists_warnings` — no target link
- `tests/test_portfolio_import.py::test_import_ii_portfolio_snapshot_classifies_non_gilt_symbols_from_reference_data` — no target link
- `tests/test_portfolio_import.py::test_import_ii_portfolio_snapshot_returns_warning_summary_and_persists` — no target link
- `tests/test_portfolio_import.py::test_load_ii_holdings_accepts_real_ii_headers_and_currency_formats` — no target link
- `tests/test_portfolio_import.py::test_load_ii_holdings_keeps_good_rows_and_attaches_parse_warnings` — no target link
- `tests/test_portfolio_import.py::test_load_ii_holdings_rejects_missing_required_columns` — no target link
- `tests/test_portfolio_import.py::test_load_ii_holdings_uses_symbol_overrides_before_name_heuristics` — no target link
- `tests/test_portfolio_import.py::test_replace_portfolio_snapshot_round_trips_persisted_holdings` — no target link

### `tests/test_portfolio_kpis.py`

- `tests/test_portfolio_kpis.py` - file-level test container
- `tests/test_portfolio_kpis.py::test_calculate_portfolio_kpis_uses_persisted_holdings_values` — no target link

### `tests/test_recommendation_change_summary.py`

- `tests/test_recommendation_change_summary.py` - file-level test container
- `tests/test_recommendation_change_summary.py::test_build_allocation_change_df_detects_shift` — no target link
- `tests/test_recommendation_change_summary.py::test_build_allocation_change_df_handles_new_bucket` — no target link
- `tests/test_recommendation_change_summary.py::test_build_allocation_change_df_no_change` — no target link
- `tests/test_recommendation_change_summary.py::test_build_headline_metrics_no_change` — no target link
- `tests/test_recommendation_change_summary.py::test_build_headline_metrics_regime_change` — no target link
- `tests/test_recommendation_change_summary.py::test_build_headline_metrics_trade_count` — no target link
- `tests/test_recommendation_change_summary.py::test_build_headline_metrics_value_delta` — no target link

### `tests/test_refresh.py`

- `tests/test_refresh.py` - file-level test container
- `tests/test_refresh.py::test_refresh_imports_saved_portfolio_csv_before_source_refresh` — no target link
- `tests/test_refresh.py::test_refresh_logs_non_gilt_reference_source` — no target link
- `tests/test_refresh.py::test_refresh_logs_terminal_rows_and_rolls_back_failed_source_writes` — no target link
- `tests/test_refresh.py::test_refresh_market_data_does_not_import_portfolio_snapshot` — no target link
- `tests/test_refresh.py::test_refresh_rejects_concurrent_attempts_with_plain_english_message` — no target link
- `tests/test_refresh.py::test_refresh_returns_source_warning_messages_on_success` — no target link

### `tests/test_risk_gate.py`

- `tests/test_risk_gate.py` - file-level test container
- `tests/test_risk_gate.py::test_apply_risk_gate_leaves_passing_trades_unchanged` — no target link
- `tests/test_risk_gate.py::test_apply_risk_gate_reverts_blocked_and_frees_to_liquidity` — no target link
- `tests/test_risk_gate.py::test_buy_exceeding_concentration_cap_blocked` — no target link
- `tests/test_risk_gate.py::test_buy_under_concentration_cap_passes` — no target link
- `tests/test_risk_gate.py::test_buy_with_none_maturity_not_blocked_for_maturity` — no target link
- `tests/test_risk_gate.py::test_concentration_blocks_before_maturity` — no target link
- `tests/test_risk_gate.py::test_friction_red_trade_is_not_gated` — no target link
- `tests/test_risk_gate.py::test_gilt_buy_exceeding_maturity_ceiling_blocked` — no target link
- `tests/test_risk_gate.py::test_gilt_buy_under_maturity_ceiling_passes` — no target link
- `tests/test_risk_gate.py::test_insufficient_liquidity_blocks_all_buys` — no target link
- `tests/test_risk_gate.py::test_sell_trade_is_not_gated` — no target link
- `tests/test_risk_gate.py::test_sufficient_liquidity_buy_passes` — no target link

### `tests/test_scenario_comparison.py`

- `tests/test_scenario_comparison.py` - file-level test container
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary` - class collector
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_columns_present` — no target link
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_counts_are_correct` — no target link
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_empty_records_returns_empty_dataframe` — no target link
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_filters_to_named_scenario` — no target link
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_held_flat_counted` — no target link
- `tests/test_scenario_comparison.py::TestBuildCoverageSummary::test_returns_dataframe` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf` - class collector
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_current_pnl_correct` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_empty_records_returns_empty_dataframe` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_executable_pnl_correct` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_filters_to_named_scenario` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_has_flattened_columns_for_both_states` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_missing_executable_state_fills_zero` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_no_scenario_name_column_in_output` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_returns_dataframe` — no target link
- `tests/test_scenario_comparison.py::TestBuildScenarioComparisonDf::test_unknown_scenario_returns_empty_dataframe` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals` - class collector
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_current_total_is_sum_of_pnl` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_empty_records_returns_empty_dict` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_executable_total_present_when_data_exists` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_filters_to_named_scenario` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_returns_dict` — no target link
- `tests/test_scenario_comparison.py::TestComputeScenarioTotals::test_unknown_scenario_returns_empty_dict` — no target link

### `tests/test_scenario_engine.py`

- `tests/test_scenario_engine.py` - file-level test container
- `tests/test_scenario_engine.py::TestCleanPriceFromGry` - class collector
- `tests/test_scenario_engine.py::TestCleanPriceFromGry::test_higher_yield_gives_lower_price` — no target link
- `tests/test_scenario_engine.py::TestCleanPriceFromGry::test_maturity_in_past_returns_none` — no target link
- `tests/test_scenario_engine.py::TestCleanPriceFromGry::test_roundtrip_long_dated_gilt` — no target link
- `tests/test_scenario_engine.py::TestCleanPriceFromGry::test_roundtrip_typical_gilt` — no target link
- `tests/test_scenario_engine.py::TestCoverageDisclosure` - class collector
- `tests/test_scenario_engine.py::TestCoverageDisclosure::test_all_four_asset_types_produce_correct_status` — no target link
- `tests/test_scenario_engine.py::TestCoverageDisclosure::test_empty_holdings_returns_empty_list` — no target link
- `tests/test_scenario_engine.py::TestCoverageDisclosure::test_model_status_field_present_on_every_record` — no target link
- `tests/test_scenario_engine.py::TestGiltRepricing` - class collector
- `tests/test_scenario_engine.py::TestGiltRepricing::test_gilt_not_in_ref_becomes_unmodelled` — no target link
- `tests/test_scenario_engine.py::TestGiltRepricing::test_magnitude_scales_shock` — no target link
- `tests/test_scenario_engine.py::TestGiltRepricing::test_rates_down_increases_gilt_value` — no target link
- `tests/test_scenario_engine.py::TestGiltRepricing::test_rates_up_reduces_gilt_value` — no target link
- `tests/test_scenario_engine.py::TestNonGiltRepricing` - class collector
- `tests/test_scenario_engine.py::TestNonGiltRepricing::test_equity_drawdown_applies_price_shock` — no target link
- `tests/test_scenario_engine.py::TestNonGiltRepricing::test_etf_uses_listed_risk_shock` — no target link
- `tests/test_scenario_engine.py::TestNonGiltRepricing::test_il_gilt_is_unmodelled_held_flat` — no target link
- `tests/test_scenario_engine.py::TestNonGiltRepricing::test_mmf_is_capital_flat` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape` - class collector
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_canonical_fields_present` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_one_record_per_holding_per_scenario_per_state` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_only_current_state_when_executable_empty` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_pnl_equals_scenario_minus_current` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_returns_list_of_dicts` — no target link
- `tests/test_scenario_engine.py::TestRunScenariosShape::test_two_portfolio_states_when_executable_provided` — no target link

### `tests/test_signal_persistence.py`

- `tests/test_signal_persistence.py` - file-level test container
- `tests/test_signal_persistence.py::test_reconcile_clear_when_no_longer_firing` — no target link
- `tests/test_signal_persistence.py::test_reconcile_insert_on_first_fire` — no target link
- `tests/test_signal_persistence.py::test_reconcile_noop_when_not_firing_and_no_active_row` — no target link
- `tests/test_signal_persistence.py::test_reconcile_update_last_seen_when_already_active` — no target link
- `tests/test_signal_persistence.py::test_run_signal_persistence_creates_readings_and_events` — no target link
- `tests/test_signal_persistence.py::test_write_signal_readings_upsert` — no target link

### `tests/test_strategic_baseline.py`

- `tests/test_strategic_baseline.py` - file-level test container
- `tests/test_strategic_baseline.py::test_fetch_current_baseline_returns_none_when_empty` — no target link
- `tests/test_strategic_baseline.py::test_fetch_current_returns_latest_when_multiple` — no target link
- `tests/test_strategic_baseline.py::test_insert_and_fetch_round_trip` — no target link
- `tests/test_strategic_baseline.py::test_insert_rejects_invalid_weights` — no target link
- `tests/test_strategic_baseline.py::test_validate_weights_extra_bucket` — no target link
- `tests/test_strategic_baseline.py::test_validate_weights_missing_bucket` — no target link
- `tests/test_strategic_baseline.py::test_validate_weights_negative` — no target link
- `tests/test_strategic_baseline.py::test_validate_weights_valid` — no target link
- `tests/test_strategic_baseline.py::test_validate_weights_wrong_sum` — no target link

### `tests/test_tidm.py`

- `tests/test_tidm.py` - file-level test container
- `tests/test_tidm.py::test_parse_coupon_decimal` — no target link
- `tests/test_tidm.py::test_parse_coupon_fractional` — no target link
- `tests/test_tidm.py::test_parse_coupon_whole_number` — no target link
- `tests/test_tidm.py::test_parse_dividenddata_html_extracts_rows` — no target link
- `tests/test_tidm.py::test_parse_dividenddata_html_skips_header_row` — no target link
- `tests/test_tidm.py::test_parse_dividenddata_html_skips_short_rows` — no target link
- `tests/test_tidm.py::test_parse_dividenddata_html_skips_unparseable_coupon` — no target link
- `tests/test_tidm.py::test_parse_dividenddata_html_skips_unparseable_maturity` — no target link
- `tests/test_tidm.py::test_parse_maturity` — no target link
- `tests/test_tidm.py::test_tidm_handler_does_nothing_when_live_lookup_fails` — no target link
- `tests/test_tidm.py::test_tidm_handler_live_is_idempotent` — no target link
- `tests/test_tidm.py::test_tidm_handler_skips_gilt_not_in_lookup` — no target link
- `tests/test_tidm.py::test_tidm_handler_updates_from_live_lookup` — no target link

### `tests/test_trade_construction.py`

- `tests/test_trade_construction.py` - file-level test container
- `tests/test_trade_construction.py::test_gilt_buy_is_rounded_toward_zero` — no target link
- `tests/test_trade_construction.py::test_gilt_sell_is_rounded_toward_zero` — no target link
- `tests/test_trade_construction.py::test_gilt_with_missing_price_emits_warning_and_skips_rounding` — no target link
- `tests/test_trade_construction.py::test_non_gilt_passes_through_with_no_rounding` — no target link
- `tests/test_trade_construction.py::test_proposed_state_reflects_rounded_gilt_and_full_non_gilt` — no target link
- `tests/test_trade_construction.py::test_residual_added_to_existing_liquidity_reserve` — no target link
- `tests/test_trade_construction.py::test_residual_creates_liquidity_reserve_row_when_absent` — no target link
- `tests/test_trade_construction.py::test_sentinel_row_excluded_with_warning` — no target link

### `tests/test_yfinance_equities.py`

- `tests/test_yfinance_equities.py` - file-level test container
- `tests/test_yfinance_equities.py::test_yfinance_equities_handler_persists_benchmark_pe` — no target link
- `tests/test_yfinance_equities.py::test_yfinance_equities_handler_persists_usable_rows_and_returns_warnings` — no target link
- `tests/test_yfinance_equities.py::test_yfinance_equities_handler_prefers_live_quote_over_daily_bar` — no target link

## Footer

Generated by repodocs.
