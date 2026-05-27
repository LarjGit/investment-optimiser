# V2 Policy Pack

This document explains the active v2 policy pack in [src/investment_optimiser/policy_pack_v2.json](/C:/workbench/code/investment-optimiser/src/investment_optimiser/policy_pack_v2.json).

The JSON artifact remains the machine-readable source of truth. This page highlights what changed from v1 and what stayed deliberately stable.

## What Changed From V1

The bucket model, named scenarios, and default portfolio constraints are unchanged from v1.

The material v2 change is the shared forward-inflation assumption contract:

- `expected_rpi_pct` has been removed from the active contract
- `rpi_assumption_pre_2030_pct` now captures the investor's forward inflation view up to January 2030
- `rpi_assumption_post_2030_pct` now captures the investor's forward inflation view for the post-2030 regime

Both assumptions remain user-authored policy inputs. They do not represent observed inflation data and they do not replace future sourced inflation mechanics.

## Why The Split Exists

The February 2030 RPI-to-CPIH alignment is structurally material for long-dated index-linked gilts. A single scalar inflation assumption is not an adequate long-run policy contract once the product needs to distinguish:

- forward inflation before the methodology change
- forward inflation after the methodology change

V2 makes that distinction explicit and versioned without widening this slice into observed-inflation refresh or resolver work.

## Shared Assumptions

The active v2 sidebar assumption schema still includes the same broader portfolio controls as v1:

- active scenario and scenario magnitude
- GRY improvement threshold
- duration floor and ceiling
- concentration and maturity limits
- minimum cash or MMF floor
- minimum short-duration floor
- Interactive Investor trade fee
- expected hold period
- benchmark ticker
- ERP threshold
- asset-class spread assumptions

The inflation section is the only user-facing schema change in this revision.

## Versioning Expectations

- `v1` remains frozen and loadable for replay and historical interpretation
- `v2` is the active default contract for the app
- Later slices should consume the policy pack through [src/investment_optimiser/policy_pack.py](/C:/workbench/code/investment-optimiser/src/investment_optimiser/policy_pack.py) rather than reading JSON files directly
