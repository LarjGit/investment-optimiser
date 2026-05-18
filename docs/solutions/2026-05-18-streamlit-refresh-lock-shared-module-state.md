---
title: "Keep the refresh lock in shared module state for Streamlit reruns"
tags: [streamlit, refresh, locking, sqlite]
date: 2026-05-18
---

## Problem
Issue `#8` sounds like a straightforward lock-and-log slice, but a lock attached to a
new coordinator instance per app rerun would not actually serialize concurrent refresh
attempts. Streamlit reruns the script on interaction, and `st.session_state` is scoped
to a user session rather than the whole local app process.

## Solution
Keep the refresh guard as shared module state in the refresh module and let coordinator
instances default to that one lock. This preserves the design doc's single-process
writer guarantee even though the app creates fresh coordinator objects during reruns,
and it avoids treating per-session Streamlit state as an authoritative concurrency
control.
