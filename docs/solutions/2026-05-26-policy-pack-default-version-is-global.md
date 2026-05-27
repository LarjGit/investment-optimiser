---
title: "Policy-pack default version is a global app lever"
tags: [policy-pack, versioning, streamlit, testing]
date: 2026-05-26
---

## Problem
It is easy to plan a policy-pack revision as if only the sidebar contract needs
to change. In practice, many modules call `load_policy_pack()` without passing
an explicit version, so the default policy-pack version in `policy_pack.py`
controls much more than the visible app inputs.

Without noticing that up front, a future slice could patch the JSON artifact or
one caller in isolation and leave the app split between old and new contracts.

## Solution
Treat `DEFAULT_POLICY_PACK_VERSION` in `src/investment_optimiser/policy_pack.py`
as the rollout switch for active shared-policy revisions.

When adding a new policy-pack revision:
- keep older artifacts loadable for replay
- register the new artifact explicitly in `_POLICY_PACK_DATA_FILES`
- switch the default version only when the active app contract should move
- add regression tests for `load_policy_pack()` with no version, explicit old
  version loads, explicit new version loads, and unknown-version rejection

This keeps historical versions replayable while making the active contract
change deliberate and testable.
