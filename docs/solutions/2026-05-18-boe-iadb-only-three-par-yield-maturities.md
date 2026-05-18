---
title: "BoE IADB CSV API only exposes 5y, 10y, 20y nominal par yields"
tags: [boe, yield-curve, api, market-data]
date: 2026-05-18
---

## Problem

The system design specifies a 6-point nominal par yield curve (1y, 2y, 5y, 10y, 20y, 30y) sourced from the Bank of England. A reasonable assumption is that the BoE IADB CSV API exposes individual series codes for each maturity. It does not.

Exhaustive testing of all plausible series code patterns confirmed only three nominal par yield series exist in the IADB: IUDSNPY (5y), IUDMNPY (10y), IUDLNPY (20y). No codes exist for 1y, 2y, or 30y.

## Solution

The 5y/10y/20y points plus base rate (IUDBEDR) are fetched via the IADB CSV API in a single request. The 1y/2y/30y points require parsing the BoE's separately published Excel ZIP archive (~39MB), which needs `openpyxl`. That work is tracked in issue #38.

When implementing any BoE yield curve slice, do not assume the IADB covers the full design-specified curve — it covers only the three benchmark maturities.
