---
title: "Derive dashboard freshness from successful refresh-log rows"
tags: [streamlit, refresh, dashboard, sqlite]
date: 2026-05-18
---

## Problem
The dashboard already persisted market refresh history in `refresh_log`, but a naive
UI plan could treat the latest row overall as the freshness source or rely only on
`st.session_state` messages. That would make the visible freshness indicator fragile:
a failed refresh attempt could appear to erase the last usable market update, and a
browser reload would lose session-only status entirely.

## Solution
Render dashboard freshness from persisted `refresh_log` success rows. For the
Portfolio-tab market refresh control, use the latest successful `finished_at`
timestamp as the durable "last refreshed" indicator and keep transient success or
warning messages in `st.session_state` only for immediate post-click feedback.
