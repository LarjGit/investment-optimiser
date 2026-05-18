from __future__ import annotations

import csv
import io
import sqlite3
import urllib.request
from datetime import UTC, date, datetime, timedelta

_SERIES: dict[str, tuple[str, float | None]] = {
    "IUDBEDR": ("boe_base_rate", None),
    "IUDSNPY": ("boe_5y", 5.0),
    "IUDMNPY": ("boe_10y", 10.0),
    "IUDLNPY": ("boe_20y", 20.0),
}

_BOE_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
    "?csv.x=yes"
    "&SeriesCodes=IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY"
    "&UsingCodes=Y"
    "&CSVF=TN"
    "&Datefrom={datefrom}"
    "&Dateto=now"
)

_MONTHS = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _boe_date(d: date) -> str:
    return f"{d.day:02d}/{_MONTHS[d.month]}/{d.year}"


def _fetch_csv() -> str:
    datefrom = _boe_date(date.today() - timedelta(days=30))
    url = _BOE_URL.format(datefrom=datefrom)
    req = urllib.request.Request(url, headers={"User-Agent": "investment-optimiser/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _parse_rows(text: str) -> list[tuple[str, str, float | None, float, str, str]]:
    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rows: list[tuple[str, str, float | None, float, str, str]] = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # skip header
    for row in reader:
        if len(row) < 5:
            continue
        raw_date = row[0].strip()
        try:
            cache_date = datetime.strptime(raw_date, "%d %b %Y").date().isoformat()
        except ValueError:
            continue
        for col_idx, (series_code, (curve_key, maturity_years)) in enumerate(_SERIES.items(), start=1):
            val_str = row[col_idx].strip()
            if val_str == "..":
                continue
            try:
                rate_pct = float(val_str)
            except ValueError:
                continue
            rows.append((cache_date, curve_key, maturity_years, rate_pct, series_code, fetched_at))
    return rows


def boe_handler(connection: sqlite3.Connection) -> None:
    text = _fetch_csv()
    rows = _parse_rows(text)
    connection.executemany(
        """
        INSERT OR REPLACE INTO yield_curve_cache
            (cache_date, curve_key, maturity_years, rate_pct, series_code, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
