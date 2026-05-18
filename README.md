# investment-optimiser

A holistic portfolio optimisation tool for a UK SIPP, combining fixed income relative value analysis with macro signals for equity allocation.

## Current app shell

The first runnable slice is in place:

- `app.py` boots a four-tab Streamlit shell
- startup runs SQLite schema migrations with `PRAGMA user_version`
- the app reads real persisted state from the local database instead of hardcoded demo content

The local database lives at `data/investment_optimiser.db` by default and is configured through `.streamlit/secrets.toml`.

## Run locally

```bash
uv run streamlit run app.py
```

On first boot this creates the SQLite database, enables WAL mode, and applies the initial schema migration.

## Test

```bash
uv run pytest tests/test_app_smoke.py
```

## Documentation

- [System design](docs/system-design.md)
- [V1 policy pack](docs/policy-pack-v1.md)
