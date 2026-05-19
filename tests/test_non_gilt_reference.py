from __future__ import annotations

from pathlib import Path
import sqlite3

from investment_optimiser.db import initialize_database
from investment_optimiser.non_gilt_reference import (
    _extract_company_page_url,
    non_gilt_reference_handler,
)
from investment_optimiser.portfolio_import import Holding, replace_portfolio_snapshot


def test_non_gilt_reference_handler_persists_classifications_for_latest_snapshot_symbols(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
            Holding(
                symbol="REL",
                name="RELX PLC",
                asset_type="other",
                qty=10.0,
                clean_price_gbp=24.62,
                market_value_gbp=246.2,
                book_cost_gbp=200.0,
            ),
            Holding(
                symbol="VUAG",
                name="Vanguard S&P 500 UCITS ETF",
                asset_type="other",
                qty=5.0,
                clean_price_gbp=104.44,
                market_value_gbp=522.2,
                book_cost_gbp=500.0,
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

    pages = {
        "REL": """
            <html><body>
            <h1>RELX PLC</h1>
            <div>FCA listing Category</div>
            <div>Equity shares (commercial companies)</div>
            </body></html>
        """,
        "VUAG": """
            <html><body>
            <h1>VANGUARD S&P 500 UCITS ETF</h1>
            <div>ETFs</div>
            </body></html>
        """,
    }

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_html",
        lambda symbol: pages[symbol],
    )

    with sqlite3.connect(db_path) as connection:
        non_gilt_reference_handler(connection)
        rows = connection.execute(
            """
            SELECT symbol, instrument_name, asset_type, source_name, source_label
            FROM non_gilt_reference
            ORDER BY symbol ASC
            """
        ).fetchall()

    assert rows == [
        (
            "REL",
            "RELX PLC",
            "equity",
            "lse_company_page",
            "Equity shares (commercial companies)",
        ),
        (
            "VUAG",
            "VANGUARD S&P 500 UCITS ETF",
            "etf",
            "lse_company_page",
            "ETFs",
        ),
    ]


def test_non_gilt_reference_handler_reclassifies_existing_snapshot_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
            Holding(
                symbol="REL",
                name="RELX PLC",
                asset_type="other",
                qty=10.0,
                clean_price_gbp=24.62,
                market_value_gbp=246.2,
                book_cost_gbp=200.0,
                import_warning=(
                    "Asset type could not be classified confidently; "
                    "defaulted to 'other'."
                ),
            ),
        ],
    )

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_html",
        lambda _symbol: """
            <html><body>
            <h1>RELX PLC</h1>
            <div>FCA listing Category</div>
            <div>Equity shares (commercial companies)</div>
            </body></html>
        """,
    )

    with sqlite3.connect(db_path) as connection:
        non_gilt_reference_handler(connection)
        row = connection.execute(
            """
            SELECT asset_type, import_warning
            FROM portfolio_snapshots
            WHERE snapshot_date = ? AND symbol = ?
            """,
            ("2026-05-19", "REL"),
        ).fetchone()

    assert row == ("equity", None)


def test_extract_company_page_url_accepts_root_stock_page_with_query_string() -> None:
    search_html = """
        <html><body>
        <a href="/stock/ADM/admiral-group-plc?lang=en">Admiral Group</a>
        </body></html>
    """

    assert _extract_company_page_url(search_html, "ADM") == (
        "https://www.londonstockexchange.com/stock/ADM/admiral-group-plc?lang=en"
    )


def test_non_gilt_reference_handler_falls_back_to_name_heuristic_when_fetch_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
            Holding(
                symbol="ADM",
                name="Admiral Group",
                asset_type="other",
                qty=10.0,
                clean_price_gbp=33.93,
                market_value_gbp=339.3,
                book_cost_gbp=300.0,
                import_warning=(
                    "Asset type could not be classified confidently; "
                    "defaulted to 'other'."
                ),
            ),
        ],
    )

    def raise_fetch_error(_symbol: str) -> str:
        raise ValueError("No LSE company page found.")

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_html",
        raise_fetch_error,
    )

    with sqlite3.connect(db_path) as connection:
        non_gilt_reference_handler(connection)
        ref_row = connection.execute(
            """
            SELECT symbol, asset_type, source_name, source_label
            FROM non_gilt_reference
            """
        ).fetchone()
        snapshot_row = connection.execute(
            """
            SELECT asset_type, import_warning
            FROM portfolio_snapshots
            WHERE snapshot_date = ? AND symbol = ?
            """,
            ("2026-05-19", "ADM"),
        ).fetchone()

    assert ref_row == ("ADM", "equity", "snapshot_name_heuristic", "group")
    assert snapshot_row == ("equity", None)
