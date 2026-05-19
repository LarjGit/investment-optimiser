from __future__ import annotations

import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

_DMO_URL = "https://www.dmo.gov.uk/data/XmlDataReport?reportCode=D1A"

_VULGAR_FRACTIONS: dict[str, float] = {
    "½": 0.5,
    "¼": 0.25,
    "¾": 0.75,
    "⅛": 0.125,
    "⅜": 0.375,
    "⅝": 0.625,
    "⅞": 0.875,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
}


def _parse_coupon(name: str) -> float | None:
    for ch, frac_val in _VULGAR_FRACTIONS.items():
        m = re.search(r"(\d*)" + re.escape(ch) + r"%", name)
        if m:
            return (int(m.group(1)) if m.group(1) else 0) + frac_val

    m = re.search(r"(\d+)\s+(\d+)/(\d+)%", name)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))

    m = re.search(r"(\d+\.\d+)%", name)
    if m:
        return float(m.group(1))

    m = re.search(r"(\d+)%", name)
    if m:
        return float(m.group(1))

    return None


def _parse_dividend_dates(dates_str: str) -> tuple[str, int] | None:
    m = re.match(r"(\d+)\s+(\w+)/(\w+)$", dates_str.strip())
    if not m:
        return None
    return (f"{m.group(2)},{m.group(3)}", int(m.group(1)))


def _normalize_type(raw: str) -> str | None:
    stripped = raw.strip()
    if stripped == "Conventional":
        return "Conventional"
    if stripped.startswith("Index-linked"):
        return "Index-linked"
    return None


def _parse_isodate(dt_str: str) -> str | None:
    return dt_str[:10] if dt_str else None


def _fetch_xml() -> bytes:
    req = urllib.request.Request(
        _DMO_URL,
        headers={"User-Agent": "investment-optimiser/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _parse_rows(content: bytes) -> list[tuple]:
    root = ET.fromstring(content)
    last_updated = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rows = []
    for elem in root.iter("View_GILTS_IN_ISSUE"):
        isin = elem.get("ISIN_CODE", "").strip()
        if not isin:
            continue

        instrument_name = elem.get("INSTRUMENT_NAME", "").strip()
        instrument_type = _normalize_type(elem.get("INSTRUMENT_TYPE", ""))
        if instrument_type is None:
            continue

        coupon_pct = _parse_coupon(instrument_name)
        if coupon_pct is None:
            continue

        maturity_date = _parse_isodate(elem.get("REDEMPTION_DATE", ""))
        if not maturity_date:
            continue

        dividend_result = _parse_dividend_dates(elem.get("DIVIDEND_DATES", ""))
        if dividend_result is None:
            continue
        dividend_months, dividend_day = dividend_result

        ex_div_date = _parse_isodate(elem.get("CURRENT_EX_DIV_DATE", ""))
        maturity_bracket = elem.get("MATURITY_BRACKET", "").strip() or None

        rows.append((
            isin,
            None,  # tidm — populated by TIDM bridge (issue #11)
            instrument_name,
            coupon_pct,
            maturity_date,
            dividend_months,
            dividend_day,
            ex_div_date,
            instrument_type,
            maturity_bracket,
            last_updated,
        ))
    return rows


def dmo_handler(connection: sqlite3.Connection) -> None:
    content = _fetch_xml()
    rows = _parse_rows(content)
    connection.execute("DELETE FROM gilt_reference")
    connection.executemany(
        """
        INSERT INTO gilt_reference (
            isin, tidm, instrument_name, coupon_pct, maturity_date,
            dividend_months, dividend_day, ex_div_date,
            instrument_type, maturity_bracket, last_updated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
