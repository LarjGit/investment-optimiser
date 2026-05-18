from __future__ import annotations

import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from investment_optimiser.boe import boe_handler
from investment_optimiser.db import initialize_database


_TWO_DATE_CSV = (
    "DATE,IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY\n"
    "01 Jan 2025,4.75,4.51,4.97,5.45\n"
    "02 Jan 2025,4.75,4.52,4.98,5.46\n"
)


def _mock_urlopen(text: str) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = text.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    return db_path


def test_boe_handler_handles_empty_response_without_error(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    header_only = "DATE,IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY\n"

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(header_only)):
        with sqlite3.connect(db_path) as conn:
            boe_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM yield_curve_cache").fetchone()[0]
    assert count == 0


def test_boe_handler_propagates_http_error(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    http_error = urllib.error.HTTPError(
        url="https://example.com", code=503, msg="Service Unavailable",
        hdrs=MagicMock(), fp=None,
    )

    with patch("urllib.request.urlopen", side_effect=http_error):
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(urllib.error.HTTPError):
                boe_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM yield_curve_cache").fetchone()[0]
    assert count == 0


def test_boe_handler_skips_missing_values_without_error(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    # IUDSNPY and IUDLNPY are missing for the first date
    csv_with_gaps = (
        "DATE,IUDBEDR,IUDSNPY,IUDMNPY,IUDLNPY\n"
        "01 Jan 2025,4.75,..,4.97,..\n"
        "02 Jan 2025,4.75,4.52,4.98,5.46\n"
    )

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(csv_with_gaps)):
        with sqlite3.connect(db_path) as conn:
            boe_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT cache_date, curve_key FROM yield_curve_cache ORDER BY cache_date, curve_key"
        ).fetchall()

    # date 1: only boe_base_rate and boe_10y (2 rows); date 2: all 4 (4 rows) = 6
    assert len(rows) == 6
    assert ("2025-01-01", "boe_5y") not in rows
    assert ("2025-01-01", "boe_20y") not in rows
    assert ("2025-01-01", "boe_base_rate") in rows
    assert ("2025-01-01", "boe_10y") in rows


def test_boe_handler_inserts_rows_for_each_series_and_date(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_DATE_CSV)):
        with sqlite3.connect(db_path) as conn:
            boe_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT cache_date, curve_key, maturity_years, rate_pct, series_code "
            "FROM yield_curve_cache "
            "ORDER BY cache_date, curve_key"
        ).fetchall()

    assert len(rows) == 8
    assert ("2025-01-01", "boe_base_rate", None, 4.75, "IUDBEDR") in rows
    assert ("2025-01-01", "boe_5y", 5.0, 4.51, "IUDSNPY") in rows
    assert ("2025-01-01", "boe_10y", 10.0, 4.97, "IUDMNPY") in rows
    assert ("2025-01-01", "boe_20y", 20.0, 5.45, "IUDLNPY") in rows
    assert ("2025-01-02", "boe_base_rate", None, 4.75, "IUDBEDR") in rows
