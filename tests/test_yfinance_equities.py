from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import Holding, replace_portfolio_snapshot
from investment_optimiser.yfinance_equities import yfinance_equities_handler


def test_yfinance_equities_handler_persists_usable_rows_and_returns_warnings(
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
                asset_type="equity",
                qty=10.0,
                clean_price_gbp=24.0,
                market_value_gbp=240.0,
                book_cost_gbp=200.0,
            ),
            Holding(
                symbol="VUAG",
                name="Vanguard S&P 500 UCITS ETF",
                asset_type="etf",
                qty=5.0,
                clean_price_gbp=100.0,
                market_value_gbp=500.0,
                book_cost_gbp=450.0,
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

    class FakeDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 5, 19)

    price_frame = pd.DataFrame(
        {
            ("Close", "REL.L"): [24.62, 24.80],
            ("Close", "VUAG.L"): [None, None],
            ("Volume", "REL.L"): [1200, 1500],
            ("Volume", "VUAG.L"): [None, None],
        },
        index=pd.Index(
            [pd.Timestamp("2026-05-18"), pd.Timestamp("2026-05-19")],
            name="Date",
        ),
    )

    monkeypatch.setattr("investment_optimiser.yfinance_equities.date", FakeDate)
    monkeypatch.setattr(
        "investment_optimiser.yfinance_equities._download_price_frame",
        lambda _tickers: price_frame,
    )
    monkeypatch.setattr(
        "investment_optimiser.yfinance_equities._download_errors",
        lambda: {"VUAG.L": "No price data found"},
    )
    monkeypatch.setattr(
        "investment_optimiser.yfinance_equities._fetch_quote_currency",
        lambda ticker: "GBp" if ticker == "REL.L" else "GBP",
    )

    with sqlite3.connect(db_path) as connection:
        warning_messages = yfinance_equities_handler(connection)
        rows = connection.execute(
            """
            SELECT cache_date, ticker, close_price_gbp, volume
            FROM equity_price_cache
            ORDER BY ticker ASC
            """
        ).fetchall()

    assert rows == [
        ("2026-05-19", "REL.L", 0.248, 1500),
    ]
    assert warning_messages == [
        "VUAG.L price refresh failed: No price data found",
    ]
