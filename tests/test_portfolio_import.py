from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import (
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
        "CSH2: Price could not be parsed from 'bad'."
    ]
    assert len(
        fetch_portfolio_snapshot(
            f"sqlite:///{db_path.as_posix()}",
            snapshot_date="2026-05-18",
        )
    ) == 2


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
            import_warning=None,
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
