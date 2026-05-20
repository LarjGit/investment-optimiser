---
title: "st.data_editor state cannot be reset by writing to session_state — change the key"
tags: [streamlit, data-editor, session-state, ui]
date: 2026-05-20
---

## Problem

After a user saves or cancels an `st.data_editor` form, the widget's internal diff
state persists in Streamlit's session state. Writing back to
`st.session_state[widget_key]` does not clear it — the editor re-renders with stale
edits on the next run. This is a known open bug (GitHub #6540 as of mid-2026).

## Solution

Store an integer counter in session state alongside the editing flag. Include the
counter in the widget `key` string (e.g. `f"baseline_editor_{counter}"`). On save
or cancel, increment the counter before calling `st.rerun()`. The changed key forces
Streamlit to mount a fresh editor with no prior diff state.

```python
editor_counter = st.session_state.get(EDITOR_KEY_COUNTER, 0)
# ... on save or cancel:
st.session_state[EDITOR_KEY_COUNTER] = editor_counter + 1
st.rerun()
```

Always validate the returned DataFrame in Python — `NumberColumn` min/max bounds
are enforced in the UI but can be bypassed by copy-paste.
