# V1 Policy Pack

This document explains the frozen v1 policy pack that now lives in [src/investment_optimiser/policy_pack_v1.json](/C:/workbench/code/investment-optimiser/src/investment_optimiser/policy_pack_v1.json).

The JSON file is the machine-consumable source of truth. This page exists to explain the decisions in plain English.

## What It Freezes

The v1 pack locks four things:

1. The baseline bucket model
2. The named deterministic scenario set
3. The default portfolio constraints
4. The shared dashboard assumption schema and defaults

It does not lock a user-specific strategic allocation. The user's actual baseline weights remain a separate versioned input that should conform to this bucket model.

## Baseline Bucket Model

The top-layer baseline is a bucket-weight vector that sums to 100 percent of the portfolio. The buckets are:

- `liquidity_reserve`
- `short_duration_nominal_gilts`
- `long_duration_nominal_gilts`
- `index_linked_gilts`
- `listed_risk_assets`
- `diversifiers_and_manual`

In the current UI, those bucket IDs render with these user-facing labels:

- `Liquidity reserve`
- `Short-duration nominal gilts`
- `Long-duration nominal gilts`
- `Index-linked gilts`
- `Equities`
- `Real Assets, Diversifiers & Other`

Bucket assignment follows this priority:

1. Explicit bucket override
2. Derived metadata rule
3. Name-keyword inference
4. Asset-type fallback

This means the frozen v1 contract is at the bucket level, while lower-level sleeves still decide how to express that budget in specific holdings.

### Assignment rules in plain English

**Priority 1 — Explicit override.** Any symbol registered in `SYMBOL_OVERRIDES` in `bucket_assignment.py` goes directly to the specified bucket. This wins unconditionally. In v1 the dict is empty; entries must be added in code.

**Priority 2 — Derived metadata.** Rules that use information beyond wrapper type:
- `mmf` → Liquidity reserve
- `gilt_index_linked` → Index-linked gilts
- `gilt_conventional` with known maturity ≤ 5 years → Short-duration nominal gilts
- `gilt_conventional` with known maturity > 5 years → Long-duration nominal gilts
- `gilt_conventional` with unknown maturity → defers to fallback (conservatively treated as long-duration)

**Priority 3 — Name-keyword inference.** Applied only to wrapper types whose economic exposure cannot be determined from `asset_type` alone (`etf`, `fund`, `investment_trust`, `other`). Keywords are matched case-insensitively against `instrument_name`, in this order:

| Matched keywords | Bucket |
|---|---|
| infrastructure, property, real estate, reit, commodity, gold, silver, natural resource, absolute return, hedge | Real Assets, Diversifiers & Other |
| index-linked, index linked, linker, inflation-linked | Index-linked gilts |
| gilt, government bond, uk bond | Long-duration nominal gilts (conservative; no maturity data) |
| money market, cash fund, liquidity, ultra short | Liquidity reserve |
| equity, equities, shares, stock | Equities |

This is the mechanism that routes a world-equity OEIC into Equities and a gold ETC or infrastructure investment trust into Real Assets, Diversifiers & Other — without relying on wrapper type alone.

**Priority 4 — Asset-type fallback.** When keywords yield nothing, the raw `asset_type` determines the bucket:
- `equity`, `etf`, `investment_trust` → Equities
- `reit`, `fund`, `other` → Real Assets, Diversifiers & Other

Note: plain investment trusts without recognisable keywords default to Equities. If a specific IT should land elsewhere, register a symbol override.

**Resolution method tagging.** `assign_bucket()` returns a `BucketResolution` with both `bucket_id` and `method` (`override`, `derived_metadata`, `name_keywords`, `asset_type_fallback`, `catch_all`). The view layer can use `method` to flag holdings classified by keywords or catch-all as requiring review.

**Future improvement.** IA sector codes would replace name-keyword inference as the primary exposure signal. No enrichment pipeline exists for them in v1.

## Named Scenarios

The fixed v1 scenario set is:

- `rates_up_parallel`
- `rates_down_parallel`
- `bear_steepener`
- `equity_drawdown`
- `inflation_surprise`

Scenario magnitude is a scalar applied to one of those named shock templates. That matches the existing design expectation that the sidebar exposes both a scenario selector and a scenario magnitude control.

## Default Constraints

The v1 defaults are conservative and explicit:

- Long-only and fully invested
- Baseline tilt band of `10%`
- Turnover limit of `10%` in constructive regimes, `15%` in normal regimes, and `25%` in defensive regimes
- Duration floor of `2` years and ceiling of `8` years
- `10y+` liquidity concentration threshold of `35%`
- Max maturity of `15` years
- Max single-position concentration of `12.5%`
- Minimum cash or MMF floor of `5%`
- Minimum short-duration floor of `10%`

Adverse-scenario floors are also frozen in the JSON pack as percentages of current portfolio value.

## Shared Assumptions

The shared sidebar assumption contract includes explicit keys for:

- active scenario
- scenario magnitude
- GRY improvement threshold
- duration floor and ceiling
- `10y+` liquidity concentration threshold
- max maturity
- max single-position concentration
- minimum cash or MMF floor
- minimum short-duration floor
- expected RPI
- Interactive Investor trade fee
- expected hold period
- spread assumptions by friction class

The current defaults include:

- trade fee: `GBP 3.99`
- expected hold period: `2` years
- spread assumptions from the design doc

## Fixed V1 Decisions

The pack also resolves a few design choices that would otherwise block allocator work:

- The shared policy pack defines bucket schema and defaults, not the user's actual baseline weights.
- Free cash and MMF share the same liquidity bucket in v1.
- Scenario magnitude scales named scenarios instead of selecting separate scenario families.
- Holdings without a credible scenario model remain `held_flat` with an explicit model-status label.
- Friction routing classes stay out of the core bucket taxonomy.

## How Later Slices Should Consume It

Later Python slices should use [src/investment_optimiser/policy_pack.py](/C:/workbench/code/investment-optimiser/src/investment_optimiser/policy_pack.py) rather than reading the JSON file ad hoc. That keeps version lookup and canonical serialization in one place.
