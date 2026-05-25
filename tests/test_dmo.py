from __future__ import annotations

import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from investment_optimiser.db import initialize_database
from investment_optimiser.dmo import _parse_coupon, _parse_dividend_dates, dmo_handler


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
# _parse_coupon
# ---------------------------------------------------------------------------

def test_parse_coupon_whole_number() -> None:
    assert _parse_coupon("4% Treasury Gilt 2031") == 4.0


def test_parse_coupon_ascii_fraction() -> None:
    assert _parse_coupon("4 1/8% Treasury Gilt 2040") == pytest.approx(4.125)


def test_parse_coupon_ascii_fraction_zero_integer() -> None:
    assert _parse_coupon("0 3/8% Treasury Gilt 2028") == pytest.approx(0.375)


def test_parse_coupon_unicode_vulgar_fraction_with_integer() -> None:
    assert _parse_coupon("1½% Treasury Gilt 2026") == pytest.approx(1.5)


def test_parse_coupon_pure_vulgar_fraction() -> None:
    assert _parse_coupon("¾% Treasury Gilt 2025") == pytest.approx(0.75)


def test_parse_coupon_returns_none_when_no_coupon() -> None:
    assert _parse_coupon("No coupon here") is None


# ---------------------------------------------------------------------------
# _parse_dividend_dates
# ---------------------------------------------------------------------------

def test_parse_dividend_dates_jan_jul() -> None:
    assert _parse_dividend_dates("22 Jan/Jul") == ("Jan,Jul", 22)


def test_parse_dividend_dates_mar_sep() -> None:
    assert _parse_dividend_dates("7 Mar/Sep") == ("Mar,Sep", 7)


def test_parse_dividend_dates_empty_returns_none() -> None:
    assert _parse_dividend_dates("") is None


def test_parse_dividend_dates_garbled_returns_none() -> None:
    assert _parse_dividend_dates("not a date") is None


# ---------------------------------------------------------------------------
# dmo_handler round-trip
# ---------------------------------------------------------------------------

_CONVENTIONAL_ISIN = "GB00BYZW3G56"
_IL_ISIN = "GB0004893535"

_TWO_GILT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Data>
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB00BYZW3G56"
    INSTRUMENT_NAME="1½% Treasury Gilt 2026"
    INSTRUMENT_TYPE="Conventional "
    MATURITY_BRACKET="Ultra-Short"
    REDEMPTION_DATE="2026-07-22T00:00:00"
    DIVIDEND_DATES="22 Jan/Jul"
    CURRENT_EX_DIV_DATE="2026-07-13T00:00:00"
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB0004893535"
    INSTRUMENT_NAME="2½% Index-linked Treasury Gilt 2024"
    INSTRUMENT_TYPE="Index-linked 3 months"
    MATURITY_BRACKET="Short"
    REDEMPTION_DATE="2024-07-17T00:00:00"
    DIVIDEND_DATES="17 Jan/Jul"
    CURRENT_EX_DIV_DATE="2024-07-08T00:00:00"
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
</Data>
"""

_BAD_COUPON_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Data>
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB00BYZW3G56"
    INSTRUMENT_NAME="1½% Treasury Gilt 2026"
    INSTRUMENT_TYPE="Conventional "
    MATURITY_BRACKET="Ultra-Short"
    REDEMPTION_DATE="2026-07-22T00:00:00"
    DIVIDEND_DATES="22 Jan/Jul"
    CURRENT_EX_DIV_DATE="2026-07-13T00:00:00"
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB9999999999"
    INSTRUMENT_NAME="No coupon Treasury Gilt 2030"
    INSTRUMENT_TYPE="Conventional "
    MATURITY_BRACKET="Medium"
    REDEMPTION_DATE="2030-01-01T00:00:00"
    DIVIDEND_DATES="1 Jan/Jul"
    CURRENT_EX_DIV_DATE=""
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB0004893535"
    INSTRUMENT_NAME="2½% Index-linked Treasury Gilt 2024"
    INSTRUMENT_TYPE="Index-linked 3 months"
    MATURITY_BRACKET="Short"
    REDEMPTION_DATE="2024-07-17T00:00:00"
    DIVIDEND_DATES="17 Jan/Jul"
    CURRENT_EX_DIV_DATE="2024-07-08T00:00:00"
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
</Data>
"""

_ONE_GILT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<Data>
  <View_GILTS_IN_ISSUE
    ISIN_CODE="GB00XNEW0001"
    INSTRUMENT_NAME="4% Treasury Gilt 2035"
    INSTRUMENT_TYPE="Conventional "
    MATURITY_BRACKET="Long"
    REDEMPTION_DATE="2035-03-07T00:00:00"
    DIVIDEND_DATES="7 Mar/Sep"
    CURRENT_EX_DIV_DATE="2035-02-26T00:00:00"
    CLOSE_OF_BUSINESS_DATE="2026-05-15T00:00:00"
  />
</Data>
"""


def test_dmo_handler_inserts_correct_rows(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT isin, instrument_type, coupon_pct, maturity_date, "
            "dividend_months, dividend_day, tidm "
            "FROM gilt_reference ORDER BY isin"
        ).fetchall()

    assert len(rows) == 2
    conv = next(r for r in rows if r[0] == _CONVENTIONAL_ISIN)
    assert conv[1] == "Conventional"
    assert conv[2] == pytest.approx(1.5)
    assert conv[3] == "2026-07-22"
    assert conv[4] == "Jan,Jul"
    assert conv[5] == 22
    assert conv[6] is None  # tidm not populated until issue #11

    il = next(r for r in rows if r[0] == _IL_ISIN)
    assert il[1] == "Index-linked"


def test_dmo_handler_skips_row_with_unparseable_coupon(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_BAD_COUPON_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM gilt_reference").fetchone()[0]

    assert count == 2  # bad-coupon row silently skipped


def test_dmo_handler_preserves_tidm_on_second_run(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    # Simulate TIDM bridge having populated the conventional gilt's TIDM.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE gilt_reference SET tidm = 'TG26' WHERE isin = ?",
            (_CONVENTIONAL_ISIN,),
        )

    # Second DMO run must not wipe the TIDM.
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tidm FROM gilt_reference WHERE isin = ?", (_CONVENTIONAL_ISIN,)
        ).fetchone()

    assert row[0] == "TG26", "TIDM must survive a dmo_handler re-run"


def test_dmo_handler_replaces_all_rows_on_second_run(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_TWO_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen(_ONE_GILT_XML)):
        with sqlite3.connect(db_path) as conn:
            dmo_handler(conn)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT isin FROM gilt_reference").fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "GB00XNEW0001"


def test_dmo_handler_propagates_http_error(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    http_error = urllib.error.URLError(reason="connection refused")

    with patch("urllib.request.urlopen", side_effect=http_error):
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(urllib.error.URLError):
                dmo_handler(conn)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM gilt_reference").fetchone()[0]
    assert count == 0
