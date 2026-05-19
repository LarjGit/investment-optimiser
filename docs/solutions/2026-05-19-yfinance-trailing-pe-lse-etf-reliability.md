---
title: "trailingPE for LSE ETFs is unreliable via yfinance; unavailable is first-class"
tags: [yfinance, equity-signal, erp, pe-ratio]
date: 2026-05-19
---

## Problem

A reasonable assumption when implementing the ERP signal is that
`yf.Ticker('SWRD.L').info['trailingPE']` reliably returns a float. In practice,
LSE-listed ETFs get a reduced subset of the `.info` dict — `trailingPE` is absent
or `None` more often than it is present. There is also a precedent from mid-2025
where a structurally similar field (`pegRatio`) disappeared for all tickers with no
warning. Treating `None` as an edge case in the unavailable path produces a signal
card that looks broken in normal operation.

The design doc author verified that SWRD.L does currently return `trailingPE`, so
this is a live data-availability risk rather than a permanent blocker. The user
confirmed this is acceptable to build against.

## Solution

- Access via `info.get('trailingPE')` (never subscript directly — raises `KeyError`
  when the field is absent).
- Wrap the whole `.info` call in `try/except Exception` — yfinance can raise
  `YFRateLimitError` or network errors depending on version.
- Treat `None` as a first-class, expected state: the handler appends a warning to
  `warning_messages` but does not fail.
- The signal card "unavailable" state is rendered with a visible explanation, not
  suppressed.
- In tests, always monkeypatch `_fetch_benchmark_pe` so tests are not sensitive to
  network access or yfinance behaviour. Existing `yfinance_equities_handler` tests
  that predate the PE fetch must also patch it or they become non-deterministic.
