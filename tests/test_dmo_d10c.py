from __future__ import annotations

import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.dmo_d10c import (
    dmo_d10c_handler,
    get_freshness,
    get_latest_observed_inflation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(xml: str) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = xml.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    return db_path


# ---------------------------------------------------------------------------
# Sample XML fixtures
# ---------------------------------------------------------------------------

_TWO_GILT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Data>
  <GILTS
    INSTRUMENT_NAME="0 1/8% Index-linked Treasury Gilt 2028"
    ISIN_CODE="GB00BZ1NTB69"
    SETTLEMENT_DATE="2026-05-27T00:00:00"
    INDEX_RATIO_OR_RPI="1.46186">
    <REFERENCE_RPI REFERENCE_RPI="408.20000" />
  </GILTS>
  <GILTS
    INSTRUMENT_NAME="1&#188;% Index-linked Treasury Gilt 2032"
    ISIN_CODE="GB00B3LJWW56"
    SETTLEMENT_DATE="2026-05-27T00:00:00"
    INDEX_RATIO_OR_RPI="1.83241">
    <REFERENCE_RPI REFERENCE_RPI="408.20000" />
  </GILTS>
</Data>
"""

_SAME_ISIN_TWO_DATES_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Data>
  <GILTS
    INSTRUMENT_NAME="0 1/8% Index-linked Treasury Gilt 2028"
    ISIN_CODE="GB00BZ1NTB69"
    SETTLEMENT_DATE="2026-05-26T00:00:00"
    INDEX_RATIO_OR_RPI="1.46100">
    <REFERENCE_RPI REFERENCE_RPI="407.90000" />
  </GILTS>
  <GILTS
    INSTRUMENT_NAME="0 1/8% Index-linked Treasury Gilt 2028"
    ISIN_CODE="GB00BZ1NTB69"
    SETTLEMENT_DATE="2026-05-27T00:00:00"
    INDEX_RATIO_OR_RPI="1.46186">
    <REFERENCE_RPI REFERENCE_RPI="408.20000" />
  </GILTS>
</Data>
"""

_ERROR_ENVELOPE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Error>
  <ErrorDetails Message="bad request" />
</Error>
"""


# ---------------------------------------------------------------------------
# Test 1: handler inserts rows with correct field values
# ---------------------------------------------------------------------------

def test_dmo_d10c_handler_inserts_rows(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT isin, settlement_date, index_ratio, reference_rpi, "
            "provider, confidence_tier, is_degraded "
            "FROM observed_inflation_cache ORDER BY isin"
        ).fetchall()

    assert len(rows) == 2

    first = next(r for r in rows if r[0] == "GB00B3LJWW56")
    assert first[1] == "2026-05-27"
    assert first[2] == pytest.approx(1.83241)
    assert first[3] == pytest.approx(408.20000)
    assert first[4] == "DMO_D10C"
    assert first[5] == "authoritative"
    assert first[6] == 0

    second = next(r for r in rows if r[0] == "GB00BZ1NTB69")
    assert second[1] == "2026-05-27"
    assert second[2] == pytest.approx(1.46186)
    assert second[3] == pytest.approx(408.20000)
    assert second[4] == "DMO_D10C"
    assert second[5] == "authoritative"
    assert second[6] == 0


# ---------------------------------------------------------------------------
# Test 2: same-day rerun is idempotent (upsert, not duplicate)
# ---------------------------------------------------------------------------

def test_dmo_d10c_handler_idempotent_rerun(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM observed_inflation_cache").fetchone()[0]

    assert count == 2


# ---------------------------------------------------------------------------
# Test 3: HTTP error propagates; table stays empty
# ---------------------------------------------------------------------------

def test_dmo_d10c_handler_propagates_http_error(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    http_error = urllib.error.URLError(reason="connection refused")

    with patch("urllib.request.urlopen", side_effect=http_error):
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(urllib.error.URLError):
                dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM observed_inflation_cache").fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# Test 4: DMO error envelope raises RuntimeError
# ---------------------------------------------------------------------------

def test_dmo_d10c_handler_error_envelope_raises(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_ERROR_ENVELOPE_XML)):
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(RuntimeError, match="DMO D10C returned error"):
                dmo_d10c_handler(conn)


# ---------------------------------------------------------------------------
# Test 5: get_freshness returns None on empty DB
# ---------------------------------------------------------------------------

def test_get_freshness_returns_none_when_empty(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with sqlite3.connect(db_path) as conn:
        result = get_freshness(conn)

    assert result is None


# ---------------------------------------------------------------------------
# Test 6: get_freshness returns correct metadata after a handler run
# ---------------------------------------------------------------------------

def test_get_freshness_returns_correct_metadata(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        result = get_freshness(conn)

    assert result is not None
    assert result["as_of_date"] == "2026-05-27"
    assert result["provider"] == "DMO_D10C"
    assert result["confidence_tier"] == "authoritative"
    assert result["is_degraded"] == 0
    assert result["fetched_at"]  # non-empty UTC timestamp


# ---------------------------------------------------------------------------
# Test 7: get_latest_observed_inflation returns one row per ISIN (most recent)
# ---------------------------------------------------------------------------

def test_get_latest_observed_inflation_returns_one_row_per_isin(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAME_ISIN_TWO_DATES_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = get_latest_observed_inflation(conn)

    assert len(rows) == 1
    assert rows[0]["isin"] == "GB00BZ1NTB69"
    assert rows[0]["settlement_date"] == "2026-05-27"
    assert rows[0]["index_ratio"] == pytest.approx(1.46186)


# ---------------------------------------------------------------------------
# Test 8: multi-date XML stores all rows (full history preserved)
# ---------------------------------------------------------------------------

def test_dmo_d10c_handler_multi_date_stores_all_rows(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAME_ISIN_TWO_DATES_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_d10c_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM observed_inflation_cache").fetchone()[0]

    assert count == 2, "Both settlement dates for the same ISIN should be stored"
