---
title: "Prefer native Streamlit elements for dashboard KPIs and shell status"
tags: [streamlit, dashboard, testing, ui]
date: 2026-05-19
---

## Problem
The UI redesign replaced native `st.metric` and header/caption elements with raw
HTML rendered through `st.markdown(..., unsafe_allow_html=True)`. That looked
clean visually, but it removed those KPIs from Streamlit's element tree, made the
dashboard more dependent on custom DOM/CSS structure, and broke `AppTest` checks
that inspect `app.metric`.

## Solution
Keep layout and controls in native Streamlit primitives wherever the app is
communicating application state: use `st.title`, `st.caption`, `st.metric`,
`st.columns`, `st.sidebar`, and `st.expander` for the shell, and reserve custom
HTML/CSS for light styling only. For pure CSS injection, prefer `st.html` over
`st.markdown(..., unsafe_allow_html=True)`. This preserves native behaviour,
testing visibility, and resilience across Streamlit upgrades.
