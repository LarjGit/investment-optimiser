from __future__ import annotations

from pathlib import Path
import sqlite3
import threading

from investment_optimiser.db import initialize_database
from investment_optimiser.refresh import REFRESH_SOURCE_ORDER, RefreshCoordinator
from investment_optimiser.portfolio_import import fetch_portfolio_snapshot


def test_refresh_rejects_concurrent_attempts_with_plain_english_message(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    entered_handler = threading.Event()
    release_handler = threading.Event()

    def blocking_handler(_connection: object) -> None:
        entered_handler.set()
        assert release_handler.wait(timeout=2)

    source_handlers = {source: (lambda _connection: None) for source in REFRESH_SOURCE_ORDER}
    source_handlers["boe"] = blocking_handler

    coordinator = RefreshCoordinator(source_handlers=source_handlers)
    thread_result: dict[str, object] = {}

    def run_first_refresh() -> None:
        thread_result["result"] = coordinator.run_refresh(
            database_url,
            snapshot_date="2026-05-18",
            sources=["boe"],
        )

    first_refresh = threading.Thread(target=run_first_refresh)
    first_refresh.start()

    assert entered_handler.wait(timeout=2)

    second_result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-18",
        sources=["boe"],
    )

    release_handler.set()
    first_refresh.join(timeout=2)

    assert second_result.status == "already_running"
    assert "already running" in second_result.message.lower()
    assert thread_result["result"].status == "completed"


def test_refresh_logs_terminal_rows_and_rolls_back_failed_source_writes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    def boe_handler(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO yield_curve_cache (
                cache_date,
                curve_key,
                maturity_years,
                rate_pct,
                series_code,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026-05-18", "base_rate", None, 4.25, "BANKRATE", "2026-05-18T08:00:00Z"),
        )

    def dmo_handler(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO yield_curve_cache (
                cache_date,
                curve_key,
                maturity_years,
                rate_pct,
                series_code,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026-05-18", "2y", 2.0, 4.0, "IUDSOIA", "2026-05-18T08:00:00Z"),
        )
        raise RuntimeError("DMO reference not implemented yet.")

    coordinator = RefreshCoordinator(
        source_handlers={
            "boe": boe_handler,
            "dmo_reference": dmo_handler,
        }
    )

    result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-18",
        sources=["boe", "dmo_reference"],
    )

    with sqlite3.connect(db_path) as connection:
        refresh_rows = connection.execute(
            """
            SELECT source, status, error_msg
            FROM refresh_log
            ORDER BY id ASC
            """
        ).fetchall()
        curve_rows = connection.execute(
            """
            SELECT curve_key
            FROM yield_curve_cache
            ORDER BY curve_key ASC
            """
        ).fetchall()

    assert result.status == "completed"
    assert refresh_rows == [
        ("boe", "completed", None),
        ("dmo_reference", "failed", "DMO reference not implemented yet."),
    ]
    assert curve_rows == [("base_rate",)]


def test_refresh_imports_saved_portfolio_csv_before_source_refresh(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    csv_path = tmp_path / "portfolio_latest.csv"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    csv_path.write_text(
        "Symbol,Name,Quantity,Price,Value,Book Cost\n"
        "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
        "CSH2,Royal London Short Term Money Market,250,bad,250.00,250.00\n",
        encoding="utf-8",
    )

    coordinator = RefreshCoordinator(portfolio_csv_path=csv_path)

    result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-18",
        sources=[],
    )

    holdings = fetch_portfolio_snapshot(database_url, snapshot_date="2026-05-18")

    assert result.status == "completed"
    assert [holding.symbol for holding in holdings] == ["TR68", "CSH2"]
    assert holdings[1].import_warning == "Price could not be parsed from 'bad'."


def test_refresh_market_data_does_not_import_portfolio_snapshot(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    csv_path = tmp_path / "portfolio_latest.csv"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    csv_path.write_text(
        "Symbol,Name,Quantity,Price,Value,Book Cost\n"
        "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n",
        encoding="utf-8",
    )

    coordinator = RefreshCoordinator(portfolio_csv_path=csv_path)

    result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-18",
        sources=[],
        include_portfolio_import=False,
    )

    holdings = fetch_portfolio_snapshot(database_url, snapshot_date="2026-05-18")

    assert result.status == "completed"
    assert holdings == []


def test_refresh_logs_non_gilt_reference_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    def non_gilt_handler(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO non_gilt_reference (
                symbol,
                instrument_name,
                asset_type,
                source_name,
                source_label,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "REL",
                "RELX PLC",
                "equity",
                "lse_company_page",
                "Equity shares (commercial companies)",
                "2026-05-19T09:00:00Z",
            ),
        )

    coordinator = RefreshCoordinator(
        source_handlers={"non_gilt_reference": non_gilt_handler}
    )

    result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-19",
        sources=["non_gilt_reference"],
        include_portfolio_import=False,
    )

    with sqlite3.connect(db_path) as connection:
        refresh_rows = connection.execute(
            """
            SELECT source, status, error_msg
            FROM refresh_log
            ORDER BY id ASC
            """
        ).fetchall()

    assert result.status == "completed"
    assert refresh_rows == [
        ("non_gilt_reference", "completed", None),
    ]


def test_refresh_returns_source_warning_messages_on_success(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    def lse_gilt_prices_handler(_connection: sqlite3.Connection) -> list[str]:
        return ["BAD1 (GB00BAD00001) price refresh failed: 404 not found"]

    coordinator = RefreshCoordinator(
        source_handlers={"lse_gilt_prices": lse_gilt_prices_handler}
    )

    result = coordinator.run_refresh(
        database_url,
        snapshot_date="2026-05-19",
        sources=["lse_gilt_prices"],
        include_portfolio_import=False,
    )

    assert result.status == "completed"
    assert result.warning_messages == [
        "BAD1 (GB00BAD00001) price refresh failed: 404 not found"
    ]
