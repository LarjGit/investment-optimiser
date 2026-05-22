from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3
import time

import yfinance as yf


_UNCLASSIFIED_ASSET_WARNING = (
    "Asset type could not be classified confidently; defaulted to 'other'."
)
_INVESTMENT_TRUST_SIGNALS = (
    "investment trust",
    "investment company",
    "trust plc",
    "it plc",
    "fund plc",
)
_INTER_REQUEST_DELAY = 2.0


@dataclass(frozen=True)
class NonGiltReferenceRow:
    symbol: str
    instrument_name: str
    asset_type: str
    source_name: str
    source_label: str
    last_updated: str


def non_gilt_reference_handler(connection: sqlite3.Connection) -> None:
    last_updated = _utc_now()
    symbols = _load_refresh_symbols(connection)
    rows: list[NonGiltReferenceRow] = []

    for symbol, instrument_name in symbols.items():
        parsed_row = _build_reference_row(symbol, instrument_name, last_updated)
        if parsed_row is not None:
            rows.append(parsed_row)

    if not rows:
        raise ValueError("Non-gilt reference refresh produced no classified symbols.")

    connection.execute("DELETE FROM non_gilt_reference")
    connection.executemany(
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
        [
            (
                row.symbol,
                row.instrument_name,
                row.asset_type,
                row.source_name,
                row.source_label,
                row.last_updated,
            )
            for row in rows
        ],
    )
    _reclassify_portfolio_snapshots(connection)


def _load_refresh_symbols(connection: sqlite3.Connection) -> dict[str, str]:
    latest_snapshot_date = connection.execute(
        "SELECT MAX(snapshot_date) FROM portfolio_snapshots"
    ).fetchone()[0]

    symbols: dict[str, str] = {
        symbol: instrument_name
        for symbol, instrument_name in connection.execute(
            "SELECT symbol, instrument_name FROM non_gilt_reference"
        ).fetchall()
    }
    if latest_snapshot_date is None:
        return dict(sorted(symbols.items()))

    symbols.update(
        {
            symbol: instrument_name
            for symbol, instrument_name in connection.execute(
                """
                SELECT symbol, instrument_name
                FROM portfolio_snapshots
                WHERE snapshot_date = ?
                  AND asset_type NOT IN ('gilt_conventional', 'gilt_index_linked', 'mmf')
                """,
                (latest_snapshot_date,),
            ).fetchall()
        }
    )
    return dict(sorted(symbols.items()))


def _build_reference_row(
    symbol: str,
    instrument_name: str,
    last_updated: str,
) -> NonGiltReferenceRow | None:
    yahoo_ticker = _to_yahoo_ticker(symbol)
    info = _fetch_yahoo_info(yahoo_ticker)
    asset_type, source_label = _classify_from_yahoo_info(info)

    if asset_type is not None:
        return NonGiltReferenceRow(
            symbol=symbol,
            instrument_name=instrument_name,
            asset_type=asset_type,
            source_name="yahoo_finance",
            source_label=source_label,
            last_updated=last_updated,
        )

    return _build_name_heuristic_row(symbol, instrument_name, last_updated)


def _to_yahoo_ticker(symbol: str) -> str:
    if "." in symbol:
        return symbol
    return f"{symbol}.L"


def _fetch_yahoo_info(yahoo_ticker: str) -> dict:
    try:
        info = yf.Ticker(yahoo_ticker).info
        time.sleep(_INTER_REQUEST_DELAY)
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _classify_from_yahoo_info(info: dict) -> tuple[str | None, str]:
    quote_type = info.get("quoteType", "")

    if quote_type == "ETF":
        return "etf", quote_type

    if quote_type == "MUTUALFUND":
        return "fund", quote_type

    if quote_type == "EQUITY":
        sector = info.get("sector", "")
        industry = info.get("industry", "")
        long_name = info.get("longName", "").lower()

        if sector == "Real Estate" and "REIT" in industry:
            return "reit", quote_type

        if any(signal in long_name for signal in _INVESTMENT_TRUST_SIGNALS):
            return "investment_trust", quote_type

        return "equity", quote_type

    return None, ""


def _build_name_heuristic_row(
    symbol: str,
    instrument_name: str,
    last_updated: str,
) -> NonGiltReferenceRow | None:
    source_label = _classify_name_label(instrument_name)
    if source_label is None:
        return None

    return NonGiltReferenceRow(
        symbol=symbol,
        instrument_name=instrument_name,
        asset_type=_map_name_label_to_asset_type(source_label),
        source_name="snapshot_name_heuristic",
        source_label=source_label,
        last_updated=last_updated,
    )


def _classify_name_label(instrument_name: str) -> str | None:
    normalized_name = instrument_name.lower()

    if "real estate investment trust" in normalized_name or "reit" in normalized_name:
        return "reit"
    if "investment trust" in normalized_name:
        return "investment_trust"
    if "etf" in normalized_name or "exchange traded fund" in normalized_name:
        return "etf"
    if "fund" in normalized_name or "oeic" in normalized_name or "unit trust" in normalized_name:
        return "fund"
    if "group" in normalized_name:
        return "group"
    if "holdings" in normalized_name:
        return "holdings"
    if "plc" in normalized_name or "ordinary shares" in normalized_name or " ord " in normalized_name:
        return "plc"
    return None


def _map_name_label_to_asset_type(source_label: str) -> str:
    if source_label == "reit":
        return "reit"
    if source_label == "investment_trust":
        return "investment_trust"
    if source_label == "etf":
        return "etf"
    if source_label == "fund":
        return "fund"
    return "equity"


def _reclassify_portfolio_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT
            snapshot_date,
            symbol,
            import_warning,
            non_gilt_reference.asset_type
        FROM portfolio_snapshots
        JOIN non_gilt_reference USING (symbol)
        WHERE portfolio_snapshots.asset_type = 'other'
          AND portfolio_snapshots.isin IS NULL
        """
    ).fetchall()

    for snapshot_date, symbol, import_warning, asset_type in rows:
        connection.execute(
            """
            UPDATE portfolio_snapshots
            SET asset_type = ?, import_warning = ?
            WHERE snapshot_date = ? AND symbol = ?
            """,
            (
                asset_type,
                _remove_unclassified_warning(import_warning),
                snapshot_date,
                symbol,
            ),
        )


def _remove_unclassified_warning(import_warning: str | None) -> str | None:
    if import_warning is None:
        return None
    if import_warning == _UNCLASSIFIED_ASSET_WARNING:
        return None

    cleaned = import_warning.replace(_UNCLASSIFIED_ASSET_WARNING, "").strip()
    return cleaned or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
