from __future__ import annotations

from pathlib import Path
import sqlite3

from investment_optimiser.db import initialize_database
from investment_optimiser.non_gilt_reference import non_gilt_reference_handler
from investment_optimiser.portfolio_import import Holding, replace_portfolio_snapshot


def _make_db(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "investment_optimiser.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)
    return db_path, database_url


def test_non_gilt_reference_handler_classifies_via_yahoo_quote_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, database_url = _make_db(tmp_path)

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
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
                symbol="SMT",
                name="Scottish Mortgage Investment Trust PLC",
                asset_type="other",
                qty=100.0,
                clean_price_gbp=8.50,
                market_value_gbp=850.0,
                book_cost_gbp=700.0,
            ),
            Holding(
                symbol="LAND",
                name="Land Securities Group PLC",
                asset_type="other",
                qty=50.0,
                clean_price_gbp=6.50,
                market_value_gbp=325.0,
                book_cost_gbp=300.0,
            ),
            Holding(
                symbol="REL",
                name="RELX PLC",
                asset_type="other",
                qty=10.0,
                clean_price_gbp=24.62,
                market_value_gbp=246.2,
                book_cost_gbp=200.0,
            ),
        ],
    )

    yahoo_info: dict[str, dict] = {
        "VUAG.L": {"quoteType": "ETF", "longName": "Vanguard S&P 500 UCITS ETF"},
        "SMT.L": {
            "quoteType": "EQUITY",
            "longName": "Scottish Mortgage Investment Trust PLC",
            "sector": "Financial Services",
            "industry": "Asset Management",
        },
        "LAND.L": {
            "quoteType": "EQUITY",
            "longName": "Land Securities Group PLC",
            "sector": "Real Estate",
            "industry": "REIT—Diversified",
        },
        "REL.L": {
            "quoteType": "EQUITY",
            "longName": "RELX PLC",
            "sector": "Industrials",
            "industry": "Specialty Business Services",
        },
    }

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_yahoo_info",
        lambda symbol: yahoo_info.get(symbol, {}),
    )

    with sqlite3.connect(db_path) as connection:
        non_gilt_reference_handler(connection)
        rows = connection.execute(
            """
            SELECT symbol, asset_type, source_name, source_label
            FROM non_gilt_reference
            ORDER BY symbol ASC
            """
        ).fetchall()

    assert rows == [
        ("LAND", "reit", "yahoo_finance", "EQUITY"),
        ("REL", "equity", "yahoo_finance", "EQUITY"),
        ("SMT", "investment_trust", "yahoo_finance", "EQUITY"),
        ("VUAG", "etf", "yahoo_finance", "ETF"),
    ]


def test_non_gilt_reference_handler_classifies_mutualfund_as_fund(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, database_url = _make_db(tmp_path)

    replace_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-19",
        holdings=[
            Holding(
                symbol="RLAM",
                name="Royal London Asset Management Fund",
                asset_type="other",
                qty=100.0,
                clean_price_gbp=1.20,
                market_value_gbp=120.0,
                book_cost_gbp=100.0,
            ),
        ],
    )

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_yahoo_info",
        lambda _symbol: {
            "quoteType": "MUTUALFUND",
            "longName": "Royal London Asset Management Fund",
        },
    )

    with sqlite3.connect(db_path) as connection:
        non_gilt_reference_handler(connection)
        row = connection.execute(
            "SELECT asset_type, source_name FROM non_gilt_reference"
        ).fetchone()

    assert row == ("fund", "yahoo_finance")


def test_non_gilt_reference_handler_reclassifies_existing_snapshot_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, database_url = _make_db(tmp_path)

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
        "investment_optimiser.non_gilt_reference._fetch_yahoo_info",
        lambda _symbol: {
            "quoteType": "EQUITY",
            "longName": "RELX PLC",
            "sector": "Industrials",
            "industry": "Publishing",
        },
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


def test_non_gilt_reference_handler_falls_back_to_name_heuristic_when_yahoo_returns_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, database_url = _make_db(tmp_path)

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

    monkeypatch.setattr(
        "investment_optimiser.non_gilt_reference._fetch_yahoo_info",
        lambda _symbol: {},
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
