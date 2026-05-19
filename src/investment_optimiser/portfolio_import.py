from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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


@dataclass(frozen=True)
class _ClassifiedAsset:
    asset_type: str
    isin: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class _PersistedHolding:
    holding: Holding
    isin: str | None = None


@dataclass(frozen=True)
class _GiltReference:
    isin: str
    instrument_type: str


@dataclass(frozen=True)
class _NonGiltReference:
    asset_type: str


ASSET_TYPE_OVERRIDES: dict[str, str] = {}
NON_GILT_SYMBOL_TO_ASSET_TYPE = {
    "VUAG": "etf",
    "VWRP": "etf",
    "INRG": "etf",
    "SMT": "investment_trust",
    "LAND": "reit",
}

_ETF_NAME_PATTERN = re.compile(r"\betf\b|exchange traded fund")
_INVESTMENT_TRUST_NAME_PATTERN = re.compile(r"\binvestment trust\b")
_REIT_NAME_PATTERN = re.compile(r"\breit\b|real estate investment trust")
_FUND_NAME_PATTERN = re.compile(r"\bfund\b|\boeic\b|\bunit trust\b")
_EQUITY_NAME_PATTERN = re.compile(r"\bplc\b|\bordinary shares?\b|\bord\b")


def load_ii_holdings(
    uploaded_file: BinaryIO,
    database_url: str | None = None,
) -> list[Holding]:
    frame = _load_ii_frame(uploaded_file)
    gilt_reference_by_tidm = _fetch_gilt_reference_by_tidm(database_url)
    non_gilt_reference_by_symbol = _fetch_non_gilt_reference_by_symbol(database_url)

    return [
        persisted_holding.holding
        for persisted_holding in _normalize_holdings(
            frame,
            gilt_reference_by_tidm,
            non_gilt_reference_by_symbol,
        )
    ]


def import_ii_portfolio_snapshot(
    database_url: str,
    uploaded_file: BinaryIO,
    snapshot_date: str,
) -> PortfolioImportResult:
    persisted_holdings = _load_persisted_holdings(uploaded_file, database_url)
    replace_portfolio_snapshot(
        database_url,
        snapshot_date,
        [persisted_holding.holding for persisted_holding in persisted_holdings],
        persisted_holdings=persisted_holdings,
    )
    return PortfolioImportResult(
        snapshot_date=snapshot_date,
        imported_count=len(persisted_holdings),
        warning_messages=[
            f"{persisted_holding.holding.symbol}: {persisted_holding.holding.import_warning}"
            for persisted_holding in persisted_holdings
            if persisted_holding.holding.import_warning
        ],
    )


def replace_portfolio_snapshot(
    database_url: str,
    snapshot_date: str,
    holdings: list[Holding],
    *,
    persisted_holdings: list[_PersistedHolding] | None = None,
) -> None:
    database_path = sqlite_path_from_url(database_url)
    persisted_rows = persisted_holdings or [
        _PersistedHolding(holding=holding)
        for holding in holdings
    ]
    total_market_value = sum(
        persisted_holding.holding.market_value_gbp
        for persisted_holding in persisted_rows
    )

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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_date,
                        persisted_holding.holding.symbol,
                        persisted_holding.isin,
                        persisted_holding.holding.name,
                        persisted_holding.holding.asset_type,
                        persisted_holding.holding.qty,
                        persisted_holding.holding.clean_price_gbp,
                        persisted_holding.holding.market_value_gbp,
                        persisted_holding.holding.book_cost_gbp,
                        persisted_holding.holding.import_warning,
                        _weight_pct(
                            persisted_holding.holding.market_value_gbp,
                            total_market_value,
                        ),
                    )
                    for persisted_holding in persisted_rows
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


def _load_persisted_holdings(
    uploaded_file: BinaryIO,
    database_url: str | None,
) -> list[_PersistedHolding]:
    frame = _load_ii_frame(uploaded_file)
    gilt_reference_by_tidm = _fetch_gilt_reference_by_tidm(database_url)
    non_gilt_reference_by_symbol = _fetch_non_gilt_reference_by_symbol(database_url)

    return _normalize_holdings(
        frame,
        gilt_reference_by_tidm,
        non_gilt_reference_by_symbol,
    )


def _load_ii_frame(uploaded_file: BinaryIO) -> pd.DataFrame:
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
    return frame.rename(columns=column_names)


def _normalize_holdings(
    frame: pd.DataFrame,
    gilt_reference_by_tidm: dict[str, _GiltReference],
    non_gilt_reference_by_symbol: dict[str, _NonGiltReference],
) -> list[_PersistedHolding]:
    persisted_holdings: list[_PersistedHolding] = []
    for _, row in frame.iterrows():
        if _is_totals_row(row):
            continue
        persisted_holdings.append(
            _normalize_holding(
                row,
                gilt_reference_by_tidm,
                non_gilt_reference_by_symbol,
            )
        )

    return persisted_holdings


def _normalize_holding(
    row: pd.Series,
    gilt_reference_by_tidm: dict[str, _GiltReference],
    non_gilt_reference_by_symbol: dict[str, _NonGiltReference],
) -> _PersistedHolding:
    symbol = str(row["symbol"]).strip()
    name = str(row["name"]).strip()
    raw_price = str(row["clean_price_gbp"]).strip()
    clean_price_gbp = parse_price(raw_price)
    warnings: list[str] = []
    if clean_price_gbp is None and raw_price:
        warnings.append(f"Price could not be parsed from {raw_price!r}.")
    classified_asset = _classify_asset_type(
        symbol,
        name,
        gilt_reference_by_tidm,
        non_gilt_reference_by_symbol,
    )
    if classified_asset.warning:
        warnings.append(classified_asset.warning)

    return _PersistedHolding(
        holding=Holding(
            symbol=symbol,
            name=name,
            asset_type=classified_asset.asset_type,
            qty=_parse_number(str(row["qty"]).strip()),
            clean_price_gbp=clean_price_gbp,
            market_value_gbp=_parse_number(str(row["market_value_gbp"]).strip()),
            book_cost_gbp=_parse_optional_number(str(row["book_cost_gbp"]).strip()),
            import_warning=" ".join(warnings) or None,
        ),
        isin=classified_asset.isin,
    )


def _classify_asset_type(
    symbol: str,
    name: str,
    gilt_reference_by_tidm: dict[str, _GiltReference],
    non_gilt_reference_by_symbol: dict[str, _NonGiltReference],
) -> _ClassifiedAsset:
    normalized_symbol = symbol.strip().upper()
    normalized_name = name.lower()

    override = ASSET_TYPE_OVERRIDES.get(normalized_symbol)
    if override is not None:
        return _ClassifiedAsset(asset_type=override)

    if (
        "money market" in normalized_name
        or "money mkt" in normalized_name
        or "mmf" in normalized_name
    ):
        return _ClassifiedAsset(asset_type="mmf")

    gilt_reference = gilt_reference_by_tidm.get(normalized_symbol)
    if gilt_reference is not None:
        if gilt_reference.instrument_type == "Conventional":
            return _ClassifiedAsset(
                asset_type="gilt_conventional",
                isin=gilt_reference.isin,
            )
        return _ClassifiedAsset(
            asset_type="gilt_index_linked",
            isin=gilt_reference.isin,
        )

    non_gilt_reference = non_gilt_reference_by_symbol.get(normalized_symbol)
    if non_gilt_reference is not None:
        return _ClassifiedAsset(asset_type=non_gilt_reference.asset_type)

    mapped_asset_type = NON_GILT_SYMBOL_TO_ASSET_TYPE.get(normalized_symbol)
    if mapped_asset_type is not None:
        return _ClassifiedAsset(asset_type=mapped_asset_type)

    heuristic_asset_type = _classify_asset_type_from_name(normalized_name)
    if heuristic_asset_type is not None:
        return _ClassifiedAsset(asset_type=heuristic_asset_type)

    if "gilt" in normalized_name or "treasury" in normalized_name:
        return _ClassifiedAsset(
            asset_type="other",
            warning=(
                "Possible gilt holding could not be matched in gilt reference data; "
                "defaulted to 'other'."
            ),
        )

    return _ClassifiedAsset(
        asset_type="other",
        warning="Asset type could not be classified confidently; defaulted to 'other'.",
    )


def _classify_asset_type_from_name(name: str) -> str | None:
    if _ETF_NAME_PATTERN.search(name):
        return "etf"
    if _INVESTMENT_TRUST_NAME_PATTERN.search(name):
        return "investment_trust"
    if _REIT_NAME_PATTERN.search(name):
        return "reit"
    if _FUND_NAME_PATTERN.search(name):
        return "fund"
    if _EQUITY_NAME_PATTERN.search(name):
        return "equity"
    return None


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


def _fetch_gilt_reference_by_tidm(
    database_url: str | None,
) -> dict[str, _GiltReference]:
    if database_url is None:
        return {}

    database_path = sqlite_path_from_url(database_url)
    with _connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT tidm, isin, instrument_type
            FROM gilt_reference
            WHERE tidm IS NOT NULL
            """
        ).fetchall()

    return {
        tidm: _GiltReference(isin=isin, instrument_type=instrument_type)
        for tidm, isin, instrument_type in rows
    }


def _fetch_non_gilt_reference_by_symbol(
    database_url: str | None,
) -> dict[str, _NonGiltReference]:
    if database_url is None:
        return {}

    database_path = sqlite_path_from_url(database_url)
    with _connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT symbol, asset_type
            FROM non_gilt_reference
            """
        ).fetchall()

    return {
        symbol: _NonGiltReference(asset_type=asset_type)
        for symbol, asset_type in rows
    }


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
