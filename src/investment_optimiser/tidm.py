from __future__ import annotations

import sqlite3
import urllib.request
from datetime import UTC, datetime
from fractions import Fraction
from html.parser import HTMLParser


_CONVENTIONAL_URL = "https://www.dividenddata.co.uk/uk-gilts-prices-yields.py"
_INDEX_LINKED_URL = "https://www.dividenddata.co.uk/index-linked-gilts-prices-yields.py"


class _RowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "td":
            self._in_td = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._row.append("".join(self._cell).strip())
            self._in_td = False
        elif tag == "tr":
            if self._row:
                self._rows.append(self._row[:])
            self._row = []

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._cell.append(data)

    @property
    def rows(self) -> list[list[str]]:
        return self._rows


def _parse_coupon(text: str) -> float:
    """Parse '1 1/2%' -> 1.5 or '0.125%' -> 0.125."""
    text = text.strip().rstrip("%").strip()
    if " " in text:
        whole, frac = text.split(" ", 1)
        return int(whole) + float(Fraction(frac))
    return float(text)


def _parse_maturity(text: str) -> str:
    """Parse '22-Jul-2026' -> '2026-07-22'."""
    return datetime.strptime(text.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")


def _parse_dividenddata_html(html: str) -> dict[tuple[float, str], str]:
    """Return {(coupon_pct, maturity_date): tidm} from a dividenddata gilt page."""
    parser = _RowParser()
    parser.feed(html)
    lookup: dict[tuple[float, str], str] = {}
    for row in parser.rows:
        if len(row) < 4:
            continue
        tidm = row[0]
        if not tidm:
            continue
        try:
            coupon = round(_parse_coupon(row[2]), 3)
            maturity = _parse_maturity(row[3])
        except (ValueError, ZeroDivisionError):
            continue
        lookup[(coupon, maturity)] = tidm
    return lookup


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "investment-optimiser/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _build_live_lookup() -> dict[tuple[float, str], str]:
    lookup: dict[tuple[float, str], str] = {}
    lookup.update(_parse_dividenddata_html(_fetch_html(_CONVENTIONAL_URL)))
    lookup.update(_parse_dividenddata_html(_fetch_html(_INDEX_LINKED_URL)))
    if not lookup:
        raise ValueError("dividenddata returned no parseable gilt data")
    return lookup


def tidm_handler(connection: sqlite3.Connection) -> None:
    last_updated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        lookup = _build_live_lookup()
    except Exception:
        return

    for isin, coupon_pct, maturity_date in connection.execute(
        "SELECT isin, coupon_pct, maturity_date FROM gilt_reference"
    ).fetchall():
        tidm = lookup.get((round(coupon_pct, 3), maturity_date))
        if tidm:
            connection.execute(
                "UPDATE gilt_reference SET tidm = ?, last_updated = ? WHERE isin = ?",
                (tidm, last_updated, isin),
            )
