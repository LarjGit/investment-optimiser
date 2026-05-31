# Plan: Issue #54 — Record and explain inflation-driven recommendation changes

## What this delivers
Every "Generate recommendation" run saves the forward RPI assumptions (pre/post-2030 %)
and the effective date of the D10C observed inflation data into the snapshot.
The Change Summary panel then shows whether the recommendation shifted because
observed data refreshed, forward assumptions changed, both, or neither.

## Acceptance criteria (from issue)
- [ ] Persisted run context records the exact forward assumptions in force.
- [ ] Persisted context is sufficient to tell whether observed inflation data changed between runs.
- [ ] Explanation surfaces distinguish observed-data change, forward-assumption change, non-inflation change.
- [ ] Tests prove attribution does not collapse categories.
- [ ] Result is replayable from persisted state.

## Files to change

| File | Change |
|---|---|
| `src/investment_optimiser/lp_recommendation.py` | Add `forward_rpi_pre_2030_pct`, `forward_rpi_post_2030_pct`, `observed_inflation_inputs` keyword args to `build_lp_recommendation` and `_build_snapshot`; embed as `inflation_inputs` inside `policy_inputs` |
| `src/investment_optimiser/allocation_runs.py` | Add optional (non-breaking) validation for new `inflation_inputs` dict inside `policy_inputs`; NO schema version bump |
| `src/investment_optimiser/recommendation_change_summary.py` | Add `build_inflation_attribution(prior_snap, current_snap) -> dict` |
| `app.py` | (1) Add `MAX(settlement_date) AS as_of_date` to freshness query; (2) pass RPI session-state + freshness to `build_lp_recommendation` at button click; (3) extend `_render_recommendation_change_summary` |
| `tests/test_recommendation_change_summary.py` | New attribution tests (TDD — write failing first) |
| `tests/test_allocation_runs.py` | Round-trip test for snapshot with `inflation_inputs` |

## Key decisions
- No schema version bump — `inflation_inputs` is optional in `policy_inputs`; old records validate fine; attribution returns `"unknown"` when field absent.
- Change signal for observed data = `as_of_date` (MAX settlement_date), NOT `fetched_at` (changes on every idempotent rerun even if data unchanged).
- Float tolerance = `abs(a - b) > 1e-4` for RPI% comparisons (3.0 round-trips exactly but guard against slider drift).
- No AppTest for the expander — known Streamlit issue #8089 (expander contents not visible in ElementTree). Test pure functions; smoke-test that panel renders.

## Snapshot shape (new field)
Inside `policy_inputs`, add:
```json
"inflation_inputs": {
  "forward_rpi_pre_2030_pct": 3.0,
  "forward_rpi_post_2030_pct": 2.5,
  "observed_as_of_date": "2026-05-27",
  "observed_provider": "DMO_D10C",
  "observed_confidence_tier": "authoritative",
  "observed_is_degraded": false
}
```
All fields are nullable (None/null when no data available).

## `build_inflation_attribution` return shape
```python
{
  "change_category": "observed_data" | "forward_assumptions" | "both" | "non_inflation" | "unknown",
  "observed_data_changed": bool,
  "forward_assumptions_changed": bool,
  "prior_observed_as_of_date": str | None,
  "current_observed_as_of_date": str | None,
  "prior_forward_pre_2030_pct": float | None,
  "current_forward_pre_2030_pct": float | None,
  "prior_forward_post_2030_pct": float | None,
  "current_forward_post_2030_pct": float | None,
}
```

## Sub-skills
- /tdd: invoke
- /frontend-design: skip (functional display, not new component)
- /vercel-react-best-practices: skip
- /simplify-code: invoke after implementation

## Workflow phase on re-entry
Phase 5: Implementation — plan already approved.
Start with TDD red step: write failing tests for `build_inflation_attribution`.
