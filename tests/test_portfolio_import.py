from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sqlite3

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import (
    ASSET_TYPE_OVERRIDES,
    Holding,
    IngestionError,
    fetch_portfolio_snapshot,
    import_ii_portfolio_snapshot,
    load_ii_holdings,
    replace_portfolio_snapshot,
)


def test_load_ii_holdings_rejects_missing_required_columns() -> None:
    uploaded_csv = BytesIO(
        "Symbol,Name,Quantity,Value\n"
        "TR68,Treasury 2068,100,1234.56\n".encode("utf-8")
    )

    with pytest.raises(IngestionError, match="missing"):
        load_ii_holdings(uploaded_csv)


def test_load_ii_holdings_keeps_good_rows_and_attaches_parse_warnings() -> None:
    uploaded_csv = BytesIO(
        (
            "Symbol,Name,Quantity,Price,Value,Book Cost\n"
            "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
            "CSH2,Royal London Short Term Money Market,250,bad,250.00,250.00\n"
            ",Totals,,,\"10,162.00\", \n"
        ).encode("utf-8")
    )

    holdings = load_ii_holdings(uploaded_csv)

    assert holdings == [
        Holding(
            symbol="TR68",
            name="Treasury 2068",
            asset_type="other",
            qty=100.0,
            clean_price_gbp=99.12,
            market_value_gbp=9912.0,
            book_cost_gbp=10000.0,
            import_warning=(
                "Possible gilt holding could not be matched in gilt reference data; "
                "defaulted to 'other'."
            ),
        ),
        Holding(
            symbol="CSH2",
            name="Royal London Short Term Money Market",
            asset_type="mmf",
            qty=250.0,
            clean_price_gbp=None,
            market_value_gbp=250.0,
            book_cost_gbp=250.0,
            import_warning="Price could not be parsed from 'bad'.",
        ),
    ]


def test_replace_portfolio_snapshot_round_trips_persisted_holdings(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "portfolio_snapshots.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    holdings = [
        Holding(
            symbol="TR68",
            name="Treasury 2068",
            asset_type="other",
            qty=100.0,
            clean_price_gbp=99.12,
            market_value_gbp=9912.0,
            book_cost_gbp=10000.0,
            import_warning=None,
        ),
        Holding(
            symbol="CSH2",
            name="Royal London Short Term Money Market",
            asset_type="mmf",
            qty=250.0,
            clean_price_gbp=None,
            market_value_gbp=250.0,
            book_cost_gbp=250.0,
            import_warning="Price could not be parsed from 'bad'.",
        ),
    ]

    replace_portfolio_snapshot(
        f"sqlite:///{db_path.as_posix()}",
        snapshot_date="2026-05-18",
        holdings=holdings,
    )

    assert fetch_portfolio_snapshot(
        f"sqlite:///{db_path.as_posix()}",
        snapshot_date="2026-05-18",
    ) == holdings


def test_import_ii_portfolio_snapshot_returns_warning_summary_and_persists(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "portfolio_snapshots.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    uploaded_csv = BytesIO(
        (
            "Symbol,Name,Quantity,Price,Value,Book Cost\n"
            "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
            "CSH2,Royal London Short Term Money Market,250,bad,250.00,250.00\n"
        ).encode("utf-8")
    )

    result = import_ii_portfolio_snapshot(
        f"sqlite:///{db_path.as_posix()}",
        uploaded_csv,
        snapshot_date="2026-05-18",
    )

    assert result.snapshot_date == "2026-05-18"
    assert result.imported_count == 2
    assert result.warning_messages == [
        "TR68: Possible gilt holding could not be matched in gilt reference data; defaulted to 'other'.",
        "CSH2: Price could not be parsed from 'bad'.",
    ]
    assert len(
        fetch_portfolio_snapshot(
            f"sqlite:///{db_path.as_posix()}",
            snapshot_date="2026-05-18",
        )
    ) == 2


def test_import_ii_portfolio_snapshot_classifies_assets_and_persists_warnings(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "portfolio_snapshots.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO gilt_reference (
                isin,
                tidm,
                instrument_name,
                coupon_pct,
                maturity_date,
                dividend_months,
                dividend_day,
                ex_div_date,
                instrument_type,
                maturity_bracket,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "GB00BMF9LJ15",
                "TR27",
                "Treasury 2027",
                4.25,
                "2027-03-07",
                "03,09",
                7,
                "2026-08-27",
                "Conventional",
                "0-5y",
                "2026-05-19T09:00:00Z",
            ),
        )

    uploaded_csv = BytesIO(
        (
            "Symbol,Name,Quantity,Price,Value,Book Cost\n"
            "TR27,4¼% Treasury Gilt 2027,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
            "CSH2,Royal London Short Term Money Market,250,1.00,250.00,250.00\n"
            "VUAG,Vanguard S&P 500 UCITS ETF,10,100.00,1000.00,900.00\n"
            "MYST,Unmapped Asset,5,10.00,50.00,45.00\n"
        ).encode("utf-8")
    )

    result = import_ii_portfolio_snapshot(
        database_url,
        uploaded_csv,
        snapshot_date="2026-05-18",
    )

    assert result.warning_messages == [
        "MYST: Asset type could not be classified confidently; defaulted to 'other'."
    ]
    assert fetch_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-18",
    ) == [
        Holding(
            symbol="TR27",
            name="4¼% Treasury Gilt 2027",
            asset_type="gilt_conventional",
            qty=100.0,
            clean_price_gbp=99.12,
            market_value_gbp=9912.0,
            book_cost_gbp=10000.0,
            import_warning=None,
            maturity_date="2027-03-07",
        ),
        Holding(
            symbol="VUAG",
            name="Vanguard S&P 500 UCITS ETF",
            asset_type="etf",
            qty=10.0,
            clean_price_gbp=100.0,
            market_value_gbp=1000.0,
            book_cost_gbp=900.0,
            import_warning=None,
        ),
        Holding(
            symbol="CSH2",
            name="Royal London Short Term Money Market",
            asset_type="mmf",
            qty=250.0,
            clean_price_gbp=1.0,
            market_value_gbp=250.0,
            book_cost_gbp=250.0,
            import_warning=None,
        ),
        Holding(
            symbol="MYST",
            name="Unmapped Asset",
            asset_type="other",
            qty=5.0,
            clean_price_gbp=10.0,
            market_value_gbp=50.0,
            book_cost_gbp=45.0,
            import_warning="Asset type could not be classified confidently; defaulted to 'other'.",
        ),
    ]


def test_import_ii_portfolio_snapshot_classifies_non_gilt_symbols_from_reference_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "portfolio_snapshots.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
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

    uploaded_csv = BytesIO(
        (
            "Symbol,Name,Quantity,Price,Value,Book Cost\n"
            "REL,RELX PLC,10,24.62,246.20,200.00\n"
        ).encode("utf-8")
    )

    result = import_ii_portfolio_snapshot(
        database_url,
        uploaded_csv,
        snapshot_date="2026-05-18",
    )

    assert result.warning_messages == []
    assert fetch_portfolio_snapshot(
        database_url,
        snapshot_date="2026-05-18",
    ) == [
        Holding(
            symbol="REL",
            name="RELX PLC",
            asset_type="equity",
            qty=10.0,
            clean_price_gbp=24.62,
            market_value_gbp=246.2,
            book_cost_gbp=200.0,
            import_warning=None,
        )
    ]


def test_load_ii_holdings_accepts_real_ii_headers_and_currency_formats() -> None:
    uploaded_csv = BytesIO(
        (
            "\ufeff\ufeff\ufeffSymbol,Name,Qty,Price,Day Gain/Loss,Day Gain/Loss %,"
            "Market Value £,Market Value,Book Cost,Gain/Loss,Gain/Loss %,Average Price\n"
            'TR27,4¼% Treasury Gilt 2027,3447.63,£0.9964,£-5.52,-0.16%,"£3,435.22","£3,435.22","£3,481.98",£-46.76,-1.34%,£1.009963\n'
            'B8XYYQ8,Royal London Short Term Money Mkt Y Acc,32710.5671,120.905p,£5.89,0.02%,"£39,548.71","£39,548.71","£37,381.65","£2,167.06",5.80%,114.28p\n'
            '"",,,Totals,,,,,,,,\n'
        ).encode("utf-8")
    )

    holdings = load_ii_holdings(uploaded_csv)

    assert holdings == [
        Holding(
            symbol="TR27",
            name="4¼% Treasury Gilt 2027",
            asset_type="other",
            qty=3447.63,
            clean_price_gbp=0.9964,
            market_value_gbp=3435.22,
            book_cost_gbp=3481.98,
            import_warning=(
                "Possible gilt holding could not be matched in gilt reference data; "
                "defaulted to 'other'."
            ),
        ),
        Holding(
            symbol="B8XYYQ8",
            name="Royal London Short Term Money Mkt Y Acc",
            asset_type="mmf",
            qty=32710.5671,
            clean_price_gbp=1.20905,
            market_value_gbp=39548.71,
            book_cost_gbp=37381.65,
            import_warning=None,
        ),
    ]


def test_load_ii_holdings_uses_symbol_overrides_before_name_heuristics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(ASSET_TYPE_OVERRIDES, "OVRD", "reit")
    uploaded_csv = BytesIO(
        (
            "Symbol,Name,Quantity,Price,Value,Book Cost\n"
            "OVRD,Generic Income Fund,10,100.00,1000.00,900.00\n"
        ).encode("utf-8")
    )

    holdings = load_ii_holdings(uploaded_csv)

    assert holdings == [
        Holding(
            symbol="OVRD",
            name="Generic Income Fund",
            asset_type="reit",
            qty=10.0,
            clean_price_gbp=100.0,
            market_value_gbp=1000.0,
            book_cost_gbp=900.0,
            import_warning=None,
        )
    ]


def test_gilt_maturity_date_stored_and_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO gilt_reference (
                isin, tidm, instrument_name, coupon_pct, maturity_date,
                dividend_months, dividend_day, ex_div_date,
                instrument_type, maturity_bracket, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("GB00BMF9LJ15", "TR27", "Treasury 2027", 4.25, "2027-03-07",
             "03,09", 7, "2026-08-27", "Conventional", "0-5y", "2026-05-20T09:00:00Z"),
        )

    uploaded_csv = BytesIO(
        "Symbol,Name,Quantity,Price,Value,Book Cost\n"
        "TR27,4¼% Treasury Gilt 2027,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n".encode("utf-8")
    )
    import_ii_portfolio_snapshot(database_url, uploaded_csv, snapshot_date="2026-05-20")

    holdings = fetch_portfolio_snapshot(database_url, snapshot_date="2026-05-20")
    assert len(holdings) == 1
    assert holdings[0] == Holding(
        symbol="TR27",
        name="4¼% Treasury Gilt 2027",
        asset_type="gilt_conventional",
        qty=100.0,
        clean_price_gbp=99.12,
        market_value_gbp=9912.0,
        book_cost_gbp=10000.0,
        import_warning=None,
        maturity_date="2027-03-07",
    )
