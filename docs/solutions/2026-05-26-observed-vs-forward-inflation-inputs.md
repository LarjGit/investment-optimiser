---
title: "Separate observed inflation inputs from forward inflation assumptions"
tags: [inflation, index-linked-gilts, policy-pack, system-design]
date: 2026-05-26
---

## Problem

The research synthesis and the older system-design wording both tended to collapse
two different concepts into one "RPI assumption":

- observed inflation data used to reconstruct current IL gilt index ratios and
  interpret quoted prices
- forward inflation assumptions used to compare real IL gilt yields against
  nominal alternatives for decision-making

Treating those as one field leads to bad planning. It makes ONS CHAW or DMO D10C
look like replacements for the policy assumption, when they actually solve a
different problem.

## Solution

Keep observed inflation inputs and forward inflation assumptions as separate
design concepts.

- Observed inflation data should come from refreshed sources such as ONS CHAW
  and/or DMO D10C.
- Forward inflation should remain a user-authored policy input.
- For long-dated IL gilts, the forward input should be split into at least
  pre-2030 and post-2030 regimes because the RPI-to-CPIH alignment is
  structurally material.

## Near-term delivery choice

Use DMO D10C as the first observed-inflation source for this slice.

Reason: it is the more direct input for current IL gilt pricing-state mechanics
and keeps the near-term implementation smaller than adding both D10C and ONS
CHAW at the same time.

ONS CHAW remains relevant as a future source for validation, fallback, or a
more self-derived observed-inflation path. It is deferred from the near-term
slice, not removed from the design.

When updating research notes, system design, or implementation plans, do not
describe ONS/DMO inflation data as replacing the forward assumption. They
augment pricing mechanics; they do not remove the investor's forward view.
