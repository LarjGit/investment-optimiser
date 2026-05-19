from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
import re
import sqlite3
import urllib.parse
import urllib.request


_SEARCH_URL = "https://www.londonstockexchange.com/search"
_USER_AGENT = "investment-optimiser/1.0"
_UNCLASSIFIED_ASSET_WARNING = (
    "Asset type could not be classified confidently; defaulted to 'other'."
)
_STOCK_PAGE_PATTERN = re.compile(r'href="(?P<path>/stock/[^"]+)"', re.IGNORECASE)
_H1_PATTERN = re.compile(r"<h1[^>]*>(?P<value>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")


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
        raise ValueError("LSE non-gilt reference refresh produced no classified symbols.")

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


def _fetch_html(symbol: str) -> str:
    company_page_url = _resolve_company_page_url(symbol)
    request = urllib.request.Request(
        company_page_url,
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def _build_reference_row(
    symbol: str,
    instrument_name: str,
    last_updated: str,
) -> NonGiltReferenceRow | None:
    try:
        html = _fetch_html(symbol)
    except Exception:
        return _build_name_heuristic_row(symbol, instrument_name, last_updated)

    parsed_row = _parse_reference_row(symbol, html, last_updated)
    if parsed_row is not None:
        return parsed_row
    return _build_name_heuristic_row(symbol, instrument_name, last_updated)


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


def _resolve_company_page_url(symbol: str) -> str:
    query = urllib.parse.urlencode({"searchtype": "all", "q": symbol})
    request = urllib.request.Request(
        f"{_SEARCH_URL}?{query}",
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        search_html = response.read().decode("utf-8", errors="replace")

    return _extract_company_page_url(search_html, symbol)


def _extract_company_page_url(search_html: str, symbol: str) -> str:
    normalized_symbol = symbol.upper()
    fallback_path: str | None = None

    for match in _STOCK_PAGE_PATTERN.finditer(search_html):
        href = unescape(match.group("path"))
        parsed = urllib.parse.urlparse(href)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 3 or segments[0] != "stock":
            continue
        if segments[1].upper() != normalized_symbol:
            continue

        path_with_query = parsed.path
        if parsed.query:
            path_with_query = f"{path_with_query}?{parsed.query}"

        if len(segments) >= 4 and segments[3] == "company-page":
            return f"https://www.londonstockexchange.com{path_with_query}"
        if len(segments) == 3 and fallback_path is None:
            fallback_path = path_with_query

    if fallback_path is not None:
        return f"https://www.londonstockexchange.com{fallback_path}"
    raise ValueError(f"No LSE company page found for symbol {symbol}.")


def _parse_reference_row(
    symbol: str,
    html: str,
    last_updated: str,
) -> NonGiltReferenceRow | None:
    instrument_name = _extract_instrument_name(html)
    source_label = _extract_source_label(html, instrument_name)
    asset_type = _map_asset_type(instrument_name, source_label)
    if asset_type is None:
        return None

    return NonGiltReferenceRow(
        symbol=symbol,
        instrument_name=instrument_name,
        asset_type=asset_type,
        source_name="lse_company_page",
        source_label=source_label,
        last_updated=last_updated,
    )


def _extract_instrument_name(html: str) -> str:
    match = _H1_PATTERN.search(html)
    if match is None:
        raise ValueError("LSE company page did not contain a heading.")

    value = _strip_tags(match.group("value")).strip()
    if not value:
        raise ValueError("LSE company page heading was empty.")
    return value


def _extract_source_label(html: str, instrument_name: str) -> str:
    text = _normalized_text(html)
    candidate_labels = [
        "Closed-ended investment funds",
        "Equity shares (commercial companies)",
        "Real Estate Investment Trusts",
        "ETFs",
        "Equity",
    ]
    for label in candidate_labels:
        if label.lower() in text:
            return label

    if "reit" in instrument_name.lower():
        return "Real Estate Investment Trusts"

    raise ValueError("LSE company page did not expose a supported type label.")


def _map_asset_type(instrument_name: str, source_label: str) -> str | None:
    normalized_name = instrument_name.lower()
    normalized_label = source_label.lower()

    if "reit" in normalized_name or "real estate investment trust" in normalized_label:
        return "reit"
    if normalized_label == "etfs":
        return "etf"
    if normalized_label == "closed-ended investment funds":
        return "investment_trust"
    if normalized_label in {"equity", "equity shares (commercial companies)"}:
        return "equity"
    return None


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


def _normalized_text(html: str) -> str:
    text = _strip_tags(html)
    text = text.replace("\xa0", " ")
    return " ".join(text.lower().split())


def _strip_tags(value: str) -> str:
    return unescape(_TAG_PATTERN.sub(" ", value))


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
