---
title: "govuk-bank-holidays latest version is 0.19, not a 1.x series"
tags: [dependencies, govuk-bank-holidays, pyproject]
date: 2026-05-19
---

## Problem

The grill-session design doc refers to `govuk-bank-holidays` and a plausible assumption is that it follows semver with a 1.x stable release. It does not. The package has never reached 1.0 — the latest PyPI version is 0.19. Specifying `>=1.1` in `pyproject.toml` causes `uv sync` to fail with no-solution.

## Solution

Use `govuk-bank-holidays>=0.19` in `pyproject.toml`. The 0.x API is stable for the use case here (fetching England and Wales bank holidays via `BankHolidays(division="england-and-wales").get_holidays()`).
