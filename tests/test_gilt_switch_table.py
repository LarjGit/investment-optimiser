"""Tests for _build_switch_rows in app.py."""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with patch.object(st, "set_page_config"):
    import app


def _make_ranking_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "isin": "GB0000000001",
        "instrument_name": "Test Gilt",
        "instrument_type": "Conventional",
        "maturity_date": "2033-01-01",
        "gry_pct": 0.045,
        "held": False,
        "maturity_bracket": None,
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def test_returns_empty_when_no_held_isins():
    df = _make_ranking_df([{"isin": "GB0001", "gry_pct": 0.045, "held": False}])
    rows = app._build_switch_rows(df, set(), {}, 3.99, 5.0, 2.0)
    assert rows == []


def test_returns_empty_when_df_is_empty():
    rows = app._build_switch_rows(pd.DataFrame(), {"GB0001"}, {}, 3.99, 5.0, 2.0)
    assert rows == []


def test_il_gilt_excluded_from_rows():
    df = _make_ranking_df([
        {"isin": "GB0001", "instrument_type": "Index-linked", "gry_pct": 0.045, "held": True},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {}, 3.99, 5.0, 2.0)
    assert rows == []


def test_already_best_when_no_other_gilts_in_bracket():
    df = _make_ranking_df([
        {"isin": "GB0001", "gry_pct": 0.045, "held": True},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {"GB0001": 8000.0}, 3.99, 5.0, 2.0)
    assert len(rows) == 1
    row = rows[0]
    assert row["Best Available (same bracket)"] == "— already best in bracket —"
    assert row["Gap (bps)"] is None
    assert row["Break-even (mo)"] is None
    assert row["Signal"] == "✓"


def test_already_best_when_gap_at_threshold():
    # 5 bps gap → below 10 bps threshold
    df = _make_ranking_df([
        {"isin": "GB0001", "gry_pct": 0.045, "held": True},
        {"isin": "GB0002", "gry_pct": 0.04550, "held": False},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {"GB0001": 8000.0}, 3.99, 5.0, 2.0)
    assert len(rows) == 1
    assert rows[0]["Signal"] == "✓"
    assert rows[0]["Gap (bps)"] is None


def test_switch_opportunity_above_threshold():
    df = _make_ranking_df([
        {"isin": "GB0001", "instrument_name": "Held Gilt", "gry_pct": 0.045, "held": True},
        {"isin": "GB0002", "instrument_name": "Market Gilt", "gry_pct": 0.050, "held": False},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {"GB0001": 10000.0}, 3.99, 5.0, 2.0)
    assert len(rows) == 1
    row = rows[0]
    assert row["Held Gilt"] == "Held Gilt"
    assert abs(row["Held GRY"] - 4.5) < 0.001
    assert "Market Gilt" in row["Best Available (same bracket)"]
    assert abs(row["Gap (bps)"] - 50.0) < 0.5
    assert row["Break-even (mo)"] is not None
    assert row["Signal"] in ("🟢", "🟡", "🔴")


def test_position_in_row():
    df = _make_ranking_df([
        {"isin": "GB0001", "gry_pct": 0.045, "held": True},
        {"isin": "GB0002", "gry_pct": 0.050, "held": False},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {"GB0001": 12500.0}, 3.99, 5.0, 2.0)
    assert rows[0]["Position"] == 12500.0


def test_position_none_when_no_held_values():
    df = _make_ranking_df([
        {"isin": "GB0001", "gry_pct": 0.045, "held": True},
        {"isin": "GB0002", "gry_pct": 0.050, "held": False},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {}, 3.99, 5.0, 2.0)
    assert rows[0]["Position"] is None


def test_multiple_held_gilts_in_different_brackets():
    df = _make_ranking_df([
        {"isin": "GB0001", "instrument_name": "Short Held", "maturity_date": "2028-01-01", "gry_pct": 0.043, "held": True},
        {"isin": "GB0002", "instrument_name": "Medium Held", "maturity_date": "2034-01-01", "gry_pct": 0.045, "held": True},
        {"isin": "GB0003", "instrument_name": "Short Market", "maturity_date": "2028-06-01", "gry_pct": 0.048, "held": False},
        {"isin": "GB0004", "instrument_name": "Medium Market", "maturity_date": "2034-06-01", "gry_pct": 0.047, "held": False},
    ])
    rows = app._build_switch_rows(
        df, {"GB0001", "GB0002"}, {"GB0001": 8000.0, "GB0002": 12000.0}, 3.99, 5.0, 2.0
    )
    assert len(rows) == 2
    held_names = {r["Held Gilt"] for r in rows}
    assert "Short Held" in held_names
    assert "Medium Held" in held_names


def test_held_gilt_not_considered_as_its_own_best_alternative():
    # The held gilt should NOT appear as a candidate for itself
    df = _make_ranking_df([
        {"isin": "GB0001", "instrument_name": "Held Gilt", "gry_pct": 0.050, "held": True},
        {"isin": "GB0002", "instrument_name": "Market Gilt", "gry_pct": 0.045, "held": False},
    ])
    rows = app._build_switch_rows(df, {"GB0001"}, {"GB0001": 8000.0}, 3.99, 5.0, 2.0)
    assert len(rows) == 1
    # Market gilt has LOWER yield — held gilt is already best
    assert rows[0]["Signal"] == "✓"
