---
title: "Bucket keyword resolver: use a data-driven group list, not repeated if-blocks"
tags: [bucket-assignment, classification, refactoring, patterns]
date: 2026-05-20
---

## Problem

A name-keyword resolver for bucket assignment has 5 keyword groups checked in
priority order. The naive implementation writes one `if any(kw in name for kw
in _X_KEYWORDS): return BucketResolution(...)` block per group — five nearly
identical blocks that are repetitive and make the priority order implicit.

## Solution

Define a single `_KEYWORD_GROUPS: list[tuple[list[str], str]]` that pairs each
keyword list with its target bucket ID, in priority order. The resolver becomes
a single loop:

```python
for keywords, bucket_id in _KEYWORD_GROUPS:
    if any(kw in name for kw in keywords):
        return BucketResolution(bucket_id=bucket_id, method="name_keywords")
return None
```

Adding or reordering a keyword group is now a one-line data change, and the
priority is visible at a glance. Apply this pattern whenever a resolver checks
multiple ordered keyword sets against the same string field.
