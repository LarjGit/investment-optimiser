---
title: "AppTest.from_function cannot capture outer-scope closure variables"
tags: [streamlit, testing, apptest]
date: 2026-05-27
---

## Problem

`AppTest.from_function(func)` serialises the function with cloudpickle and
re-executes it in a fresh Streamlit context. If `func` is a closure that
references outer-scope variables (e.g. a `freshness` dict passed in from
the test), those variables are **not** available when the function runs —
the result is a `NameError` at test time even though the variable appears
to be in scope when the function is defined.

This contradicts the reasonable assumption that closures work the same way
inside AppTest as they do in plain Python.

## Solution

Pass test data through `session_state` instead of closure variables.
Define the app stub as a **module-level function** (not a nested closure),
and inject values before calling `.run()`:

```python
def _my_app() -> None:
    import streamlit as _st
    from mymodule import my_function

    data = _st.session_state.get("_test_data")
    my_function(data)

def test_something():
    at = AppTest.from_function(_my_app)
    at.session_state["_test_data"] = {"key": "value"}
    at.run()
    assert ...
```

Two rules:
1. The stub must be a **module-level** function (not defined inside the test
   or a helper), so cloudpickle can serialise it cleanly.
2. Imports inside the stub should use local aliases (e.g. `import streamlit
   as _st`) to avoid collisions with module-level names in the test file.
