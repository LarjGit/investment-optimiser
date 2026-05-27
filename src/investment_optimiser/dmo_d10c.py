from __future__ import annotations

import gzip
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

_DMO_D10C_URL = "https://dmo.gov.uk/data/XmlDataReport?reportCode=D10C"
_PROVIDER = "DMO_D10C"
_CONFIDENCE_TIER = "authoritative"


def _fetch_xml() -> ET.Element:
    req = urllib.request.Request(
        _DMO_D10C_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/xml,application/xml,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    if root.tag == "Error":
        details = root.find("ErrorDetails")
        msg = details.attrib.get("Message", "") if details is not None else ""
        raise RuntimeError(f"DMO D10C returned error: {msg}")
    return root


def _parse_rows(root: ET.Element, fetched_at: str) -> list[tuple]:
    rows = []
    for gilt in root.iter("GILTS"):
        isin = gilt.attrib.get("ISIN_CODE", "").strip()
        if not isin:
            continue
        instrument_name = gilt.attrib.get("INSTRUMENT_NAME", "").strip()
        settlement_raw = gilt.attrib.get("SETTLEMENT_DATE", "")
        settlement_date = settlement_raw[:10] if settlement_raw else None
        if not settlement_date:
            continue
        try:
            index_ratio = float(gilt.attrib["INDEX_RATIO_OR_RPI"])
        except (KeyError, ValueError):
            continue
        ref_rpi_el = gilt.find("REFERENCE_RPI")
        if ref_rpi_el is None:
            continue
        try:
            reference_rpi = float(ref_rpi_el.attrib["REFERENCE_RPI"])
        except (KeyError, ValueError):
            continue
        rows.append((
            isin,
            settlement_date,
            instrument_name,
            index_ratio,
            reference_rpi,
            _PROVIDER,
            fetched_at,
            _CONFIDENCE_TIER,
            0,  # is_degraded
        ))
    return rows


def dmo_d10c_handler(connection: sqlite3.Connection) -> None:
    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    root = _fetch_xml()
    rows = _parse_rows(root, fetched_at)
    connection.executemany(
        """
        INSERT OR REPLACE INTO observed_inflation_cache (
            isin, settlement_date, instrument_name,
            index_ratio, reference_rpi,
            provider, fetched_at, confidence_tier, is_degraded
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def get_latest_observed_inflation(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Return the most recent row per ISIN from observed_inflation_cache."""
    rows = connection.execute(
        """
        SELECT
            isin, settlement_date, instrument_name,
            index_ratio, reference_rpi,
            provider, fetched_at, confidence_tier, is_degraded
        FROM observed_inflation_cache
        WHERE (isin, settlement_date) IN (
            SELECT isin, MAX(settlement_date)
            FROM observed_inflation_cache
            GROUP BY isin
        )
        ORDER BY isin
        """
    ).fetchall()
    keys = (
        "isin", "settlement_date", "instrument_name",
        "index_ratio", "reference_rpi",
        "provider", "fetched_at", "confidence_tier", "is_degraded",
    )
    return [dict(zip(keys, row)) for row in rows]


def get_freshness(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Return provenance/freshness metadata for the latest D10C fetch, or None."""
    row = connection.execute(
        """
        SELECT
            MAX(settlement_date) AS as_of_date,
            fetched_at,
            provider,
            confidence_tier,
            is_degraded
        FROM observed_inflation_cache
        WHERE provider = ?
        """,
        (_PROVIDER,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return {
        "as_of_date": row[0],
        "fetched_at": row[1],
        "provider": row[2],
        "confidence_tier": row[3],
        "is_degraded": row[4],
    }
