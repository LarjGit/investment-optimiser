---
title: "Pass the SQLite URL directly to st.connection in tests"
tags: [streamlit, sqlite, testing]
date: 2026-05-17
---

## Problem
`AppTest.secrets` was enough for `st.secrets` reads inside the app, but the named
`st.connection("db", type="sql")` path was still brittle in the smoke test. The
app created the SQLite file successfully through raw `sqlite3`, then the Streamlit
SQL connection failed to open the test database reliably through the secret-based
configuration path.

## Solution
Keep the named Streamlit SQL connection, but pass `url=database_url` directly when
creating it: `st.connection("db", type="sql", url=database_url)`. That preserves
the intended `st.connection` usage for the app while making the smoke test stable
and explicit about which SQLite file the app should read.
