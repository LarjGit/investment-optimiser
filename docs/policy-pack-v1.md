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

Bucket assignment follows this priority:

1. Explicit bucket override
2. Derived metadata rule
3. Asset-type fallback

This means the frozen v1 contract is at the bucket level, while lower-level sleeves still decide how to express that budget in specific holdings.

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
