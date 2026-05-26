from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from investment_optimiser.db import initialize_database
from investment_optimiser.tidm import (
    _parse_coupon,
    _parse_dividenddata_html,
    _parse_maturity,
    tidm_handler,
)


def _setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    initialize_database(f"sqlite:///{db_path.as_posix()}")
    return db_path


def _insert_gilt(
    conn: sqlite3.Connection,
    isin: str,
    *,
    coupon_pct: float = 4.0,
    maturity_date: str = "2030-01-22",
) -> None:
    conn.execute(
        """
        INSERT INTO gilt_reference (
            isin, tidm, instrument_name, coupon_pct, maturity_date,
            dividend_months, dividend_day, instrument_type, last_updated
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
        """,
        (isin, "Test Gilt", coupon_pct, maturity_date, "Jan,Jul", 22, "Conventional", "2026-01-01T00:00:00Z"),
    )


_SAMPLE_HTML = """\
<html><body>
<table>
<tr><th>EPIC</th><th>Name</th><th>Coupon</th><th>Maturity Date</th><th>TTM</th></tr>
<tr>
  <td><a href="gilts.py?ticker=TG26">TG26</a></td>
  <td>1 1/2% Treasury Gilt 2026</td>
  <td>1 1/2%</td>
  <td>22-Jul-2026</td>
  <td>63 days</td>
</tr>
<tr>
  <td><a href="gilts.py?ticker=T27">T27</a></td>
  <td>1 1/4% Index-Linked Treasury Gilt 2027</td>
  <td>1.25%</td>
  <td>22-Nov-2027</td>
  <td>1 yr</td>
</tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# _parse_coupon
# ---------------------------------------------------------------------------

def test_parse_coupon_fractional() -> None:
    assert _parse_coupon("1 1/2%") == 1.5
    assert _parse_coupon("0 3/8%") == 0.375
    assert _parse_coupon("4 1/8%") == 4.125
    assert _parse_coupon("3 3/4%") == 3.75


def test_parse_coupon_decimal() -> None:
    assert _parse_coupon("1.25%") == 1.25
    assert _parse_coupon("0.125%") == 0.125


def test_parse_coupon_whole_number() -> None:
    assert _parse_coupon("4%") == 4.0


# ---------------------------------------------------------------------------
# _parse_maturity
# ---------------------------------------------------------------------------

def test_parse_maturity() -> None:
    assert _parse_maturity("22-Jul-2026") == "2026-07-22"
    assert _parse_maturity("10-Aug-2028") == "2028-08-10"
    assert _parse_maturity("22-Nov-2027") == "2027-11-22"


# ---------------------------------------------------------------------------
# _parse_dividenddata_html
# ---------------------------------------------------------------------------

def test_parse_dividenddata_html_extracts_rows() -> None:
    result = _parse_dividenddata_html(_SAMPLE_HTML)
    assert result == {
        (1.5, "2026-07-22"): "TG26",
        (1.25, "2027-11-22"): "T27",
    }


def test_parse_dividenddata_html_skips_header_row() -> None:
    # The <th> header row produces no <td> cells so is not included
    result = _parse_dividenddata_html(_SAMPLE_HTML)
    assert all(isinstance(k[0], float) for k in result)


def test_parse_dividenddata_html_skips_short_rows() -> None:
    html = "<table><tr><td>TG26</td><td>Name</td><td>1%</td></tr></table>"
    assert _parse_dividenddata_html(html) == {}


def test_parse_dividenddata_html_skips_unparseable_coupon() -> None:
    html = (
        "<table><tr>"
        "<td>TG26</td><td>Name</td><td>N/A</td><td>22-Jul-2026</td><td>x</td>"
        "</tr></table>"
    )
    assert _parse_dividenddata_html(html) == {}


def test_parse_dividenddata_html_skips_unparseable_maturity() -> None:
    html = (
        "<table><tr>"
        "<td>TG26</td><td>Name</td><td>1 1/2%</td><td>not-a-date</td><td>x</td>"
        "</tr></table>"
    )
    assert _parse_dividenddata_html(html) == {}


# ---------------------------------------------------------------------------
# tidm_handler — live path
# ---------------------------------------------------------------------------

def test_tidm_handler_updates_from_live_lookup(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        _insert_gilt(conn, "GB00TEST0001", coupon_pct=1.5, maturity_date="2026-07-22")

    lookup = {(1.5, "2026-07-22"): "TG26"}
    with patch("investment_optimiser.tidm._build_live_lookup", return_value=lookup):
        with sqlite3.connect(db_path) as conn:
            tidm_handler(conn)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tidm FROM gilt_reference WHERE isin = ?", ("GB00TEST0001",)
        ).fetchone()
    assert row[0] == "TG26"


def test_tidm_handler_skips_gilt_not_in_lookup(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        _insert_gilt(conn, "GB00TEST0001", coupon_pct=4.0, maturity_date="2030-01-22")

    lookup = {(1.5, "2026-07-22"): "TG26"}  # different gilt
    with patch("investment_optimiser.tidm._build_live_lookup", return_value=lookup):
        with sqlite3.connect(db_path) as conn:
            tidm_handler(conn)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tidm FROM gilt_reference WHERE isin = ?", ("GB00TEST0001",)
        ).fetchone()
    assert row[0] is None


def test_tidm_handler_live_is_idempotent(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        _insert_gilt(conn, "GB00TEST0001", coupon_pct=1.5, maturity_date="2026-07-22")

    lookup = {(1.5, "2026-07-22"): "TG26"}
    with patch("investment_optimiser.tidm._build_live_lookup", return_value=lookup):
        with sqlite3.connect(db_path) as conn:
            tidm_handler(conn)
        with sqlite3.connect(db_path) as conn:
            tidm_handler(conn)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tidm FROM gilt_reference WHERE isin = ?", ("GB00TEST0001",)
        ).fetchone()
    assert row[0] == "TG26"


# ---------------------------------------------------------------------------
# tidm_handler — live lookup failure
# ---------------------------------------------------------------------------

def test_tidm_handler_does_nothing_when_live_lookup_fails(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        _insert_gilt(conn, "GB00TEST0001")

    with patch("investment_optimiser.tidm._build_live_lookup", side_effect=Exception("network error")):
        with sqlite3.connect(db_path) as conn:
            tidm_handler(conn)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT tidm FROM gilt_reference WHERE isin = ?", ("GB00TEST0001",)
        ).fetchone()
    assert row[0] is None
