from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd
from streamlit.testing.v1 import AppTest

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import (
    Holding,
    fetch_portfolio_snapshot,
    replace_portfolio_snapshot,
)


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

    assert user_version == 7
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
        "non_gilt_reference",
        "allocation_runs",
        "strategic_baseline",
    } <= tables


def test_app_uploads_csv_and_immediately_updates_authoritative_snapshot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    saved_csv_path = tmp_path / "portfolio_latest.csv"
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
    app.run(timeout=10)

    assert not app.exception
    assert saved_csv_path.exists()
    assert len(
        fetch_portfolio_snapshot(
            f"sqlite:///{db_path.as_posix()}",
            snapshot_date=date.today().isoformat(),
        )
    ) == 2
    assert "Refresh market data" in {button.label for button in app.button}
    assert "Upload Interactive Investor CSV" not in {button.label for button in app.button}


def test_portfolio_tab_renders_kpis_from_latest_persisted_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-17",
        holdings=[
            Holding(
                symbol="OLD1",
                name="Older Holding",
                asset_type="other",
                qty=10.0,
                clean_price_gbp=10.0,
                market_value_gbp=100.0,
                book_cost_gbp=95.0,
            )
        ],
    )
    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-18",
        holdings=[
            Holding(
                symbol="TR68",
                name="Treasury 2068",
                asset_type="other",
                qty=100.0,
                clean_price_gbp=99.12,
                market_value_gbp=9912.0,
                book_cost_gbp=10000.0,
            ),
            Holding(
                symbol="CSH2",
                name="Royal London Short Term Money Market",
                asset_type="mmf",
                qty=250.0,
                clean_price_gbp=None,
                market_value_gbp=250.0,
                book_cost_gbp=250.0,
            ),
        ],
    )

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {"db": {"url": database_url}}

    app.run(timeout=10)

    assert not app.exception
    portfolio_metrics = {
        metric.label: metric.value
        for metric in app.metric
    }
    assert portfolio_metrics["Current Portfolio Value"] == "GBP 10,162"
    assert portfolio_metrics["Snapshot Portfolio Value"] == "GBP 10,162"
    assert portfolio_metrics["Holdings"] == "2"
    assert portfolio_metrics["Cash & MMF Share"] == "2.5%"


def test_portfolio_tab_reads_persisted_non_gilt_prices_from_equity_cache(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
            Holding(
                symbol="REL",
                name="RELX PLC",
                asset_type="equity",
                qty=10.0,
                clean_price_gbp=24.0,
                market_value_gbp=240.0,
                book_cost_gbp=200.0,
            ),
            Holding(
                symbol="CSH2",
                name="Royal London Short Term Money Market",
                asset_type="mmf",
                qty=250.0,
                clean_price_gbp=1.0,
                market_value_gbp=250.0,
                book_cost_gbp=250.0,
            ),
        ],
    )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO equity_price_cache (
                cache_date,
                ticker,
                close_price_gbp,
                volume,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-05-19", "REL.L", 24.80, 1500, "2026-05-19T09:00:00Z"),
        )
        connection.commit()

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {"db": {"url": database_url}}

    app.run(timeout=10)

    assert not app.exception
    portfolio_metrics = {
        metric.label: metric.value
        for metric in app.metric
    }
    holdings_frame = app.dataframe[0].value
    rel_row = holdings_frame.loc[holdings_frame["symbol"] == "REL"].iloc[0]
    mmf_row = holdings_frame.loc[holdings_frame["symbol"] == "CSH2"].iloc[0]

    assert portfolio_metrics["Current Portfolio Value"] == "GBP 498"
    assert portfolio_metrics["Snapshot Portfolio Value"] == "GBP 490"
    assert portfolio_metrics["Cash & MMF Share"] == "50.2%"
    assert "refreshed_price_gbp" not in holdings_frame.columns
    assert rel_row["refreshed_market_value_gbp"] == 248.0
    assert rel_row["refreshed_price_date"] == "2026-05-19"
    assert pd.isna(mmf_row["refreshed_market_value_gbp"])


def test_portfolio_tab_prefers_most_recently_fetched_equity_price_row(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-20",
        holdings=[
            Holding(
                symbol="IGG",
                name="IG Group Holdings",
                asset_type="equity",
                qty=541.0,
                clean_price_gbp=15.76,
                market_value_gbp=8526.16,
                book_cost_gbp=8000.0,
            ),
        ],
    )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO equity_price_cache (
                cache_date,
                ticker,
                close_price_gbp,
                volume,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-05-20", "IGG.L", 15.76, 2856732, "2026-05-20T00:11:56Z"),
        )
        connection.execute(
            """
            INSERT INTO equity_price_cache (
                cache_date,
                ticker,
                close_price_gbp,
                volume,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-05-19", "IGG.L", 17.42, 327282, "2026-05-20T00:27:17Z"),
        )
        connection.commit()

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {"db": {"url": database_url}}

    app.run(timeout=10)

    assert not app.exception
    holdings_frame = app.dataframe[0].value
    igg_row = holdings_frame.loc[holdings_frame["symbol"] == "IGG"].iloc[0]

    assert round(float(igg_row["refreshed_market_value_gbp"]), 2) == 9424.22
    assert igg_row["refreshed_price_date"] == "2026-05-19"


def test_signals_tab_renders_gilt_ranking_with_seeded_analytics(tmp_path: Path) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO gilt_reference (
                isin, instrument_name, coupon_pct, maturity_date,
                dividend_months, dividend_day, instrument_type, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("GB00B54HL0K3", "Treasury 4% 2031", 4.0, "2031-06-07",
             "Jun,Dec", 7, "Conventional", "2026-05-19T08:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO gilt_price_cache (
                cache_date, isin, clean_price_gbp, gry_pct, modified_duration_years,
                coupon_pct, maturity_date, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-05-19", "GB00B54HL0K3", 98.50, 0.0435, 4.2,
             4.0, "2031-06-07", "2026-05-19T08:00:00Z"),
        )
        connection.commit()

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {"db": {"url": database_url}}

    app.run(timeout=10)

    assert not app.exception


def test_portfolio_tab_shows_last_successful_market_refresh_after_failure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    app_path = Path(__file__).resolve().parent.parent / "app.py"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO refresh_log (
                source,
                run_started_at,
                finished_at,
                status,
                error_msg
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "boe",
                "2026-05-18T08:59:00Z",
                "2026-05-18T09:00:00Z",
                "completed",
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO refresh_log (
                source,
                run_started_at,
                finished_at,
                status,
                error_msg
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "boe",
                "2026-05-18T09:59:00Z",
                "2026-05-18T10:00:00Z",
                "failed",
                "Example failure",
            ),
        )
        connection.commit()

    app = AppTest.from_file(str(app_path))
    app.secrets["connections"] = {"db": {"url": database_url}}

    app.run(timeout=10)

    assert not app.exception
    caption_values = [element.value for element in app.caption]
    assert any(
        "Last refresh" in value and "2026-05-18 09:00 UTC" in value
        for value in caption_values
    )
