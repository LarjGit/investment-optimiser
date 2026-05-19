---
title: "DMO D1A feed covers both gilt types; D1D has no XML export"
tags: [dmo, gilt-reference, xml, market-data]
date: 2026-05-19
---

## Problem

The system design specifies separate conventional (D1A) and index-linked (D1D) DMO feeds. A reasonable assumption is that both report codes export XML. Only D1A does. Requesting `XmlDataReport?reportCode=D1D` returns an error: `"Report code 'D1D' cannot be exported as an XML file."` The D1D report exists only as a PDF.

D1A already contains both conventional and index-linked gilts in a single feed. The `INSTRUMENT_TYPE` attribute distinguishes them, but it carries a trailing space on conventional records (`"Conventional "`) and a lag-type qualifier on index-linked records (`"Index-linked 3 months"`). The `gilt_reference` schema CHECK constraint requires bare `"Conventional"` or `"Index-linked"`.

## Solution

Fetch only D1A. Strip and normalise `INSTRUMENT_TYPE` before insertion: `.strip() == "Conventional"` → `"Conventional"`, `.startswith("Index-linked")` → `"Index-linked"`. Any other value causes the row to be skipped.

When implementing any DMO reference slice, do not request D1D as XML — it will always fail.
