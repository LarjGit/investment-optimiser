---
title: "Freeze shared policy defaults in a packaged JSON artifact"
tags: [policy-pack, streamlit, configuration, testing]
date: 2026-05-18
---

## Problem
The design doc already described bucket models, scenarios, constraints, and shared
assumptions, but those decisions were only implicit in prose. Later allocator and
recommendation slices needed a machine-consumable contract. Leaving the policy
pack in `docs/` alone or moving it into Streamlit config would have made versioning,
testing, and reuse weaker.

## Solution
Store the shared v1 policy pack as a packaged JSON file under
`src/investment_optimiser/`, and expose it through a small Python loader. That
keeps the artifact immutable, source-controlled, easy to diff, and directly usable
by later slices without coupling business policy to Streamlit runtime config.
