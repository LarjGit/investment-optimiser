from __future__ import annotations

from datetime import UTC, date, datetime
import json
import sqlite3
import urllib.request


_PRICE_URL = "https://api.londonstockexchange.com/api/gw/lse/instruments/alldata/{tidm}"
_USER_AGENT = "investment-optimiser/1.0"


def lse_gilt_prices_handler(connection: sqlite3.Connection) -> list[str]:
    cache_date = date.today().isoformat()
    fetched_at = _utc_now()
    warnings: list[str] = []
    rows_to_upsert: list[tuple[str, str, float, float | None, float | None, float, str, str]] = []

    for isin, tidm, coupon_pct, maturity_date in connection.execute(
        """
        SELECT isin, tidm, coupon_pct, maturity_date
        FROM gilt_reference
        WHERE tidm IS NOT NULL
        ORDER BY maturity_date ASC, isin ASC
        """
    ).fetchall():
        try:
            payload = _fetch_instrument_data(tidm)
            _validate_payload(payload, expected_isin=isin)
            clean_price_gbp = _extract_clean_price(payload)
        except Exception as exc:
            warnings.append(f"{tidm} ({isin}) price refresh failed: {exc}")
            continue

        rows_to_upsert.append(
            (
                cache_date,
                isin,
                clean_price_gbp,
                None,
                None,
                coupon_pct,
                maturity_date,
                fetched_at,
            )
        )

    if not rows_to_upsert:
        raise ValueError("LSE gilt price refresh produced no usable rows.")

    connection.executemany(
        """
        INSERT INTO gilt_price_cache (
            cache_date,
            isin,
            clean_price_gbp,
            gry_pct,
            modified_duration_years,
            coupon_pct,
            maturity_date,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cache_date, isin) DO UPDATE SET
            clean_price_gbp = excluded.clean_price_gbp,
            gry_pct = NULL,
            modified_duration_years = NULL,
            coupon_pct = excluded.coupon_pct,
            maturity_date = excluded.maturity_date,
            fetched_at = excluded.fetched_at
        """,
        rows_to_upsert,
    )
    return warnings


def _fetch_instrument_data(tidm: str) -> dict[str, object]:
    request = urllib.request.Request(
        _PRICE_URL.format(tidm=tidm),
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_payload(payload: dict[str, object], *, expected_isin: str) -> None:
    currency = str(payload.get("currency") or "").strip().upper()
    if currency != "GBP":
        raise ValueError(f"unexpected currency {currency or 'missing'}")

    category = str(payload.get("category") or "").strip().upper()
    if category and category != "BONDS":
        raise ValueError(f"unexpected category {category}")

    segment = str(payload.get("segment") or "").strip().upper()
    if segment and segment != "UKGT":
        raise ValueError(f"unexpected segment {segment}")

    returned_isin = str(payload.get("isin") or "").strip().upper()
    if returned_isin and returned_isin != expected_isin.upper():
        raise ValueError(
            f"ISIN mismatch: expected {expected_isin}, got {returned_isin}"
        )


def _extract_clean_price(payload: dict[str, object]) -> float:
    mid_price = _coerce_float(payload.get("midPrice"))
    if mid_price is not None:
        return mid_price

    bid = _coerce_float(payload.get("bid"))
    offer = _coerce_float(payload.get("offer"))
    if bid is not None and offer is not None:
        return (bid + offer) / 2

    last_price = _coerce_float(payload.get("lastprice"))
    if last_price is not None:
        return last_price

    last_close = _coerce_float(payload.get("lastclose"))
    if last_close is not None:
        return last_close

    raise ValueError("no usable LSE price fields were present")


def _coerce_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
