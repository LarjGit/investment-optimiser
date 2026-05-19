from io import BytesIO
from pathlib import Path

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.portfolio_import import import_ii_portfolio_snapshot
from investment_optimiser.portfolio_kpis import calculate_portfolio_kpis


def test_calculate_portfolio_kpis_uses_persisted_holdings_values(tmp_path: Path) -> None:
    db_path = tmp_path / "portfolio_kpis.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    initialize_database(database_url)

    import_ii_portfolio_snapshot(
        database_url,
        BytesIO(
            (
                "Symbol,Name,Quantity,Price,Value,Book Cost\n"
                "TR68,Treasury 2068,100,GBP99.12,\"9,912.00\",\"10,000.00\"\n"
                "CSH2,Royal London Short Term Money Market,250,bad,250.00,250.00\n"
            ).encode("utf-8")
        ),
        snapshot_date="2026-05-18",
    )

    kpis = calculate_portfolio_kpis(database_url)

    assert kpis.snapshot_date == "2026-05-18"
    assert kpis.current_total_value_gbp == pytest.approx(10162.0)
    assert kpis.snapshot_total_value_gbp == pytest.approx(10162.0)
    assert kpis.holding_count == 2
    assert kpis.mmf_weight_pct == pytest.approx(250.0 / 10162.0 * 100)
