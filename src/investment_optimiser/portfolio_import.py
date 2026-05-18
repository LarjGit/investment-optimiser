from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import BinaryIO

import pandas as pd

from investment_optimiser.db import sqlite_path_from_url


II_COLUMN_MAP = {
    "symbol": ("Symbol",),
    "name": ("Name",),
    "qty": ("Qty", "Quantity"),
    "clean_price_gbp": ("Price",),
    "market_value_gbp": ("Market Value", "Value", "Market Value £"),
    "book_cost_gbp": ("Book Cost",),
}
II_REQUIRED_COLUMNS = {
    "Symbol",
    "Name",
    "Qty or Quantity",
    "Price",
    "Market Value or Value",
    "Book Cost",
}


class IngestionError(ValueError):
    """Raised when the broker file cannot be imported safely."""


@dataclass(frozen=True)
class Holding:
    symbol: str
    name: str
    asset_type: str
    qty: float
    clean_price_gbp: float | None
    market_value_gbp: float
    book_cost_gbp: float | None
    import_warning: str | None = None


@dataclass(frozen=True)
class PortfolioImportResult:
    snapshot_date: str
    imported_count: int
    warning_messages: list[str]


def load_ii_holdings(uploaded_file: BinaryIO) -> list[Holding]:
    header_frame = pd.read_csv(uploaded_file, encoding="utf-8-sig", nrows=0)
    normalized_columns = [_normalize_column_name(column) for column in header_frame.columns]
    column_names = _resolve_column_names(normalized_columns)

    uploaded_file.seek(0)
    frame = pd.read_csv(
        uploaded_file,
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
    )
    frame.columns = normalized_columns
    frame = frame.rename(columns=column_names)

    holdings: list[Holding] = []
    for _, row in frame.iterrows():
        if _is_totals_row(row):
            continue

        holdings.append(_normalize_holding(row))

    return holdings


def import_ii_portfolio_snapshot(
    database_url: str,
    uploaded_file: BinaryIO,
    snapshot_date: str,
) -> PortfolioImportResult:
    holdings = load_ii_holdings(uploaded_file)
    replace_portfolio_snapshot(database_url, snapshot_date, holdings)
    return PortfolioImportResult(
        snapshot_date=snapshot_date,
        imported_count=len(holdings),
        warning_messages=[
            f"{holding.symbol}: {holding.import_warning}"
            for holding in holdings
            if holding.import_warning
        ],
    )


def replace_portfolio_snapshot(
    database_url: str,
    snapshot_date: str,
    holdings: list[Holding],
) -> None:
    database_path = sqlite_path_from_url(database_url)
    total_market_value = sum(holding.market_value_gbp for holding in holdings)

    with _connect_database(database_path) as connection:
        with connection:
            connection.execute(
                "DELETE FROM portfolio_snapshots WHERE snapshot_date = ?",
                (snapshot_date,),
            )
            connection.executemany(
                """
                INSERT INTO portfolio_snapshots (
                    snapshot_date,
                    symbol,
                    isin,
                    instrument_name,
                    asset_type,
                    quantity,
                    clean_price_gbp,
                    market_value_gbp,
                    book_cost_gbp,
                    import_warning,
                    weight_pct
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_date,
                        holding.symbol,
                        holding.name,
                        holding.asset_type,
                        holding.qty,
                        holding.clean_price_gbp,
                        holding.market_value_gbp,
                        holding.book_cost_gbp,
                        holding.import_warning,
                        _weight_pct(holding.market_value_gbp, total_market_value),
                    )
                    for holding in holdings
                ],
            )


def fetch_portfolio_snapshot(
    database_url: str,
    snapshot_date: str,
) -> list[Holding]:
    database_path = sqlite_path_from_url(database_url)
    with _connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                symbol,
                instrument_name,
                asset_type,
                quantity,
                clean_price_gbp,
                market_value_gbp,
                book_cost_gbp,
                import_warning
            FROM portfolio_snapshots
            WHERE snapshot_date = ?
            ORDER BY market_value_gbp DESC, symbol ASC
            """,
            (snapshot_date,),
        ).fetchall()

    return [
        Holding(
            symbol=row[0],
            name=row[1],
            asset_type=row[2],
            qty=row[3],
            clean_price_gbp=row[4],
            market_value_gbp=row[5],
            book_cost_gbp=row[6],
            import_warning=row[7],
        )
        for row in rows
    ]


def _is_totals_row(row: pd.Series) -> bool:
    name = str(row.get("name", "")).strip().lower()
    symbol = str(row.get("symbol", "")).strip()
    return not symbol or "totals" in name


def _normalize_holding(row: pd.Series) -> Holding:
    raw_price = str(row["clean_price_gbp"]).strip()
    clean_price_gbp = parse_price(raw_price)
    import_warning = None
    if clean_price_gbp is None and raw_price:
        import_warning = f"Price could not be parsed from {raw_price!r}."

    return Holding(
        symbol=str(row["symbol"]).strip(),
        name=str(row["name"]).strip(),
        asset_type=_classify_asset_type(str(row["name"]).strip()),
        qty=_parse_number(str(row["qty"]).strip()),
        clean_price_gbp=clean_price_gbp,
        market_value_gbp=_parse_number(str(row["market_value_gbp"]).strip()),
        book_cost_gbp=_parse_optional_number(str(row["book_cost_gbp"]).strip()),
        import_warning=import_warning,
    )


def _classify_asset_type(name: str) -> str:
    normalized_name = name.lower()
    if (
        "money market" in normalized_name
        or "money mkt" in normalized_name
        or "mmf" in normalized_name
    ):
        return "mmf"
    return "other"


def parse_price(raw_value: str) -> float | None:
    normalized = raw_value.strip()
    if not normalized:
        return None

    cleaned = normalized.replace(",", "")
    cleaned = cleaned.replace("£", "")
    if cleaned.upper().startswith("GBP"):
        cleaned = cleaned[3:]
    if cleaned.endswith("p"):
        pennies = _try_parse_float(cleaned[:-1])
        if pennies is None:
            return None
        return pennies / 100

    return _try_parse_float(cleaned)


def _parse_optional_number(raw_value: str) -> float | None:
    if not raw_value:
        return None
    return _parse_number(raw_value)


def _parse_number(raw_value: str) -> float:
    cleaned = raw_value.replace(",", "").replace("£", "")
    parsed_value = _try_parse_float(cleaned)
    if parsed_value is None:
        raise IngestionError(f"Numeric field could not be parsed from {raw_value!r}.")
    return parsed_value


def _try_parse_float(raw_value: str) -> float | None:
    try:
        return float(raw_value)
    except ValueError:
        return None


def _connect_database(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _weight_pct(market_value_gbp: float, total_market_value_gbp: float) -> float:
    if total_market_value_gbp == 0:
        return 0.0
    return market_value_gbp / total_market_value_gbp * 100


def _normalize_column_name(column_name: str) -> str:
    return str(column_name).lstrip("\ufeff").strip()


def _resolve_column_names(observed_columns: list[str]) -> dict[str, str]:
    resolved_columns: dict[str, str] = {}
    missing_columns: list[str] = []

    for canonical_name, aliases in II_COLUMN_MAP.items():
        matched_column = next(
            (alias for alias in aliases if alias in observed_columns),
            None,
        )
        if matched_column is None:
            missing_columns.append(_required_column_label(canonical_name))
            continue
        resolved_columns[matched_column] = canonical_name

    if missing_columns:
        raise IngestionError(
            "II CSV is missing required columns: "
            + ", ".join(missing_columns)
        )

    return resolved_columns


def _required_column_label(canonical_name: str) -> str:
    labels = {
        "symbol": "Symbol",
        "name": "Name",
        "qty": "Quantity",
        "clean_price_gbp": "Price",
        "market_value_gbp": "Value",
        "book_cost_gbp": "Book Cost",
    }
    return labels[canonical_name]
