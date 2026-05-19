from __future__ import annotations

from datetime import UTC, date, datetime
import sqlite3

import pandas as pd

from investment_optimiser.policy_pack import load_policy_pack


_DEFAULT_BENCHMARK_TICKER = "SWRD.L"

NON_GILT_PRICE_ASSET_TYPES = (
    "equity",
    "etf",
    "investment_trust",
    "reit",
    "fund",
)


def yfinance_equities_handler(connection: sqlite3.Connection) -> list[str]:
    cache_date = date.today().isoformat()
    fetched_at = _utc_now()
    tickers = _load_refresh_tickers(connection)
    if not tickers:
        raise ValueError("Yahoo Finance refresh found no non-gilt holdings to price.")

    price_frame = _download_price_frame(tickers)
    download_errors = _download_errors()
    latest_rows = _extract_latest_rows(price_frame, tickers)

    rows_to_upsert: list[tuple[str, str, float, int | None, str]] = []
    warning_messages: list[str] = []

    for ticker in tickers:
        latest_row = latest_rows.get(ticker)
        if latest_row is None:
            warning_messages.append(
                f"{ticker} price refresh failed: "
                f"{download_errors.get(ticker, 'No usable daily close was returned')}"
            )
            continue

        try:
            close_price_gbp = _normalize_close_price(
                float(latest_row["close"]),
                _fetch_quote_currency(ticker),
            )
        except Exception as exc:
            warning_messages.append(f"{ticker} price refresh failed: {exc}")
            continue

        rows_to_upsert.append(
            (
                cache_date,
                ticker,
                close_price_gbp,
                _coerce_int(latest_row["volume"]),
                fetched_at,
            )
        )

    if not rows_to_upsert:
        raise ValueError("Yahoo Finance refresh produced no usable rows.")

    connection.executemany(
        """
        INSERT INTO equity_price_cache (
            cache_date,
            ticker,
            close_price_gbp,
            volume,
            fetched_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cache_date, ticker) DO UPDATE SET
            close_price_gbp = excluded.close_price_gbp,
            volume = excluded.volume,
            fetched_at = excluded.fetched_at
        """,
        rows_to_upsert,
    )

    benchmark_ticker = _benchmark_ticker_from_policy()
    pe_ratio = _fetch_benchmark_pe(benchmark_ticker)
    if pe_ratio is not None:
        connection.execute(
            """
            INSERT INTO equity_valuation_cache (
                cache_date,
                source_name,
                pe_ratio,
                pe_as_of,
                fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_date, source_name) DO UPDATE SET
                pe_ratio = excluded.pe_ratio,
                pe_as_of = excluded.pe_as_of,
                fetched_at = excluded.fetched_at
            """,
            (cache_date, "yfinance_equities", pe_ratio, cache_date, fetched_at),
        )
    else:
        warning_messages.append(
            f"{benchmark_ticker} trailingPE unavailable from Yahoo Finance; "
            "equity_valuation_cache not updated."
        )

    return warning_messages


def to_yahoo_ticker(symbol: str) -> str:
    normalized_symbol = symbol.strip().upper()
    if "." in normalized_symbol:
        return normalized_symbol
    return f"{normalized_symbol}.L"


def _load_refresh_tickers(connection: sqlite3.Connection) -> list[str]:
    latest_snapshot_date = connection.execute(
        "SELECT MAX(snapshot_date) FROM portfolio_snapshots"
    ).fetchone()[0]
    if latest_snapshot_date is None:
        return []

    placeholders = ", ".join("?" for _ in NON_GILT_PRICE_ASSET_TYPES)
    rows = connection.execute(
        f"""
        SELECT symbol
        FROM portfolio_snapshots
        WHERE snapshot_date = ?
          AND asset_type IN ({placeholders})
        ORDER BY symbol ASC
        """,
        (latest_snapshot_date, *NON_GILT_PRICE_ASSET_TYPES),
    ).fetchall()

    return [to_yahoo_ticker(symbol) for (symbol,) in rows]


def _download_price_frame(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf

    return yf.download(
        tickers=tickers,
        period="2d",
        interval="1d",
        actions=False,
        auto_adjust=False,
        progress=False,
        threads=False,
        group_by="column",
        multi_level_index=True,
    )


def _download_errors() -> dict[str, str]:
    from yfinance import shared

    return {
        str(ticker): str(error)
        for ticker, error in getattr(shared, "_ERRORS", {}).items()
    }


def _fetch_quote_currency(ticker: str) -> str:
    import yfinance as yf

    ticker_object = yf.Ticker(ticker)
    fast_info = getattr(ticker_object, "fast_info", None)
    if fast_info is not None:
        currency = fast_info.get("currency")
        if currency:
            return str(currency)

    info = getattr(ticker_object, "info", {})
    currency = info.get("currency")
    if currency:
        return str(currency)
    raise ValueError("quote currency was unavailable")


def _extract_latest_rows(
    price_frame: pd.DataFrame,
    tickers: list[str],
) -> dict[str, dict[str, object]]:
    if price_frame.empty:
        return {}

    if isinstance(price_frame.columns, pd.MultiIndex):
        close_frame = _extract_field_frame(price_frame, "Close")
        volume_frame = _extract_field_frame(price_frame, "Volume")
    else:
        close_frame = price_frame[["Close"]].rename(columns={"Close": tickers[0]})
        volume_frame = None
        if "Volume" in price_frame.columns:
            volume_frame = price_frame[["Volume"]].rename(columns={"Volume": tickers[0]})

    latest_rows: dict[str, dict[str, object]] = {}
    for ticker in tickers:
        if ticker not in close_frame.columns:
            continue

        close_series = close_frame[ticker].dropna()
        if close_series.empty:
            continue

        latest_index = close_series.index[-1]
        volume_value: object = None
        if volume_frame is not None and ticker in volume_frame.columns:
            volume_value = volume_frame.at[latest_index, ticker]

        latest_rows[ticker] = {
            "close": close_series.iloc[-1],
            "volume": volume_value,
        }

    return latest_rows


def _extract_field_frame(price_frame: pd.DataFrame, field_name: str) -> pd.DataFrame:
    field_frame = price_frame[field_name]
    if isinstance(field_frame, pd.Series):
        return field_frame.to_frame()
    return field_frame


def _normalize_close_price(close_price: float, currency: str) -> float:
    normalized_currency = currency.strip()
    if normalized_currency == "GBp" or normalized_currency.upper() == "GBX":
        return close_price / 100
    if normalized_currency.upper() == "GBP":
        return close_price
    raise ValueError(f"unsupported quote currency {normalized_currency or 'missing'}")


def _coerce_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _benchmark_ticker_from_policy() -> str:
    fields = load_policy_pack().get("shared_assumption_schema", {}).get("fields", [])
    match = next((f for f in fields if f.get("key") == "benchmark_ticker"), None)
    return str(match["default"]) if match else _DEFAULT_BENCHMARK_TICKER


def _fetch_benchmark_pe(ticker: str) -> float | None:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        val = info.get("trailingPE")
        if val is None or not isinstance(val, (int, float)):
            return None
        return float(val)
    except Exception:
        return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
