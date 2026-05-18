from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import sqlite3
from typing import Any

from investment_optimiser.db import sqlite_path_from_url


@dataclass(frozen=True)
class PortfolioKpis:
    snapshot_date: str | None
    total_value_gbp: float
    holding_count: int
    mmf_weight_pct: float


def build_portfolio_kpis(
    holdings_rows: Iterable[Mapping[str, Any]],
    snapshot_date: str | None,
) -> PortfolioKpis:
    total_value_gbp = 0.0
    holding_count = 0
    mmf_value_gbp = 0.0

    for row in holdings_rows:
        market_value_gbp = float(row["market_value_gbp"] or 0.0)
        total_value_gbp += market_value_gbp
        holding_count += 1
        if row["asset_type"] == "mmf":
            mmf_value_gbp += market_value_gbp

    return _build_aggregate_portfolio_kpis(
        snapshot_date=snapshot_date,
        total_value_gbp=total_value_gbp,
        holding_count=holding_count,
        mmf_value_gbp=mmf_value_gbp,
    )


def calculate_portfolio_kpis(database_url: str) -> PortfolioKpis:
    database_path = sqlite_path_from_url(database_url)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            WITH latest_snapshot AS (
                SELECT MAX(snapshot_date) AS snapshot_date
                FROM portfolio_snapshots
            )
            SELECT
                latest_snapshot.snapshot_date,
                COUNT(portfolio_snapshots.symbol) AS holding_count,
                COALESCE(SUM(portfolio_snapshots.market_value_gbp), 0) AS total_value_gbp,
                COALESCE(
                    SUM(
                        CASE
                            WHEN portfolio_snapshots.asset_type = 'mmf'
                            THEN portfolio_snapshots.market_value_gbp
                            ELSE 0
                        END
                    ),
                    0
                ) AS mmf_value_gbp
            FROM latest_snapshot
            LEFT JOIN portfolio_snapshots
                ON portfolio_snapshots.snapshot_date = latest_snapshot.snapshot_date
            """
        ).fetchone()

    return _build_aggregate_portfolio_kpis(
        snapshot_date=row[0],
        total_value_gbp=float(row[2] or 0.0),
        holding_count=int(row[1] or 0),
        mmf_value_gbp=float(row[3] or 0.0),
    )


def _build_aggregate_portfolio_kpis(
    snapshot_date: str | None,
    total_value_gbp: float,
    holding_count: int,
    mmf_value_gbp: float,
) -> PortfolioKpis:
    return PortfolioKpis(
        snapshot_date=snapshot_date,
        total_value_gbp=total_value_gbp,
        holding_count=holding_count,
        mmf_weight_pct=_weight_pct(mmf_value_gbp, total_value_gbp),
    )


def _weight_pct(part_value_gbp: float, total_value_gbp: float) -> float:
    if total_value_gbp == 0:
        return 0.0
    return part_value_gbp / total_value_gbp * 100
