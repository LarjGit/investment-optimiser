from datetime import date
from pathlib import Path
import sqlite3

from streamlit.testing.v1 import AppTest

from investment_optimiser.portfolio_import import fetch_portfolio_snapshot


def test_app_boots_into_tab_shell_and_runs_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {
        "db": {"url": f"sqlite:///{db_path.as_posix()}"}
    }

    app.run(timeout=10)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Portfolio",
        "Signals",
        "Scenarios",
        "Decision Log",
    ]

    with sqlite3.connect(db_path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert user_version == 2
    assert journal_mode.lower() == "wal"
    assert {
        "portfolio_snapshots",
        "signal_readings",
        "signal_events",
        "decision_log",
        "yield_curve_cache",
        "gilt_price_cache",
        "equity_price_cache",
        "equity_valuation_cache",
        "refresh_log",
        "gilt_reference",
        "allocation_runs",
    } <= tables


def test_app_imports_ii_csv_and_surfaces_row_warnings(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {
        "db": {"url": f"sqlite:///{db_path.as_posix()}"}
    }

    app.run(timeout=10)
    app.file_uploader[0].set_value(
        (
            "portfolio.csv",
            (
                "Symbol,Name,Quantity,Price,Value,Book Cost\n"
                "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
                "CSH2,Royal London Short Term Money Market,250,bad,250.00,250.00\n"
            ).encode("utf-8"),
            "text/csv",
        )
    )
    app.button[0].click()
    app.run(timeout=10)

    assert not app.exception
    assert any("Price could not be parsed" in warning.value for warning in app.warning)
    assert len(
        fetch_portfolio_snapshot(
            f"sqlite:///{db_path.as_posix()}",
            snapshot_date=date.today().isoformat(),
        )
    ) == 2
