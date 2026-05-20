---
title: "Audit function parameters against actual usage before finalising the API"
tags: [api-design, refactoring, simplification]
date: 2026-05-20
---

## Problem

When sketching a function interface upfront (e.g. in a TDD brief), it is easy to
include parameters that feel relevant to the domain but that the function body
never actually uses. In this case `compute_cash_deployment` was given a
`snapshot_date` parameter because the surrounding workflow needs a date — but the
function itself only computes a cash excess and pro-rata deployment split. The
date is only needed by `build_cash_run_record`, which writes the audit record.

The unused parameter survived the initial implementation and was only caught
during the simplify pass.

## Solution

Before writing any implementation, check each parameter in the planned signature
against the logic that the function will actually perform. If a parameter is only
needed by a *caller* (e.g. a persistence layer wrapping the pure function), keep
it in the caller, not the pure function.

In this case: remove `snapshot_date` from `compute_cash_deployment` and pass it
directly to `build_cash_run_record`. This keeps the pure computation function
free of context that belongs to persistence.
