from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import threading
from typing import Callable, Mapping, Sequence

from investment_optimiser.db import sqlite_path_from_url
from investment_optimiser.portfolio_import import (
    PortfolioImportResult,
    import_ii_portfolio_snapshot,
)
from investment_optimiser.signal_persistence import run_signal_persistence


REFRESH_SOURCE_ORDER = (
    "boe",
    "dmo_reference",
    "lse_tidm_bridge",
    "non_gilt_reference",
    "lse_gilt_prices",
    "gilt_analytics",
    "yfinance_equities",
    "blackrock_ftse_pe",
)

SourceHandler = Callable[[sqlite3.Connection], list[str] | None]
_REFRESH_LOCK = threading.Lock()


@dataclass(frozen=True)
class RefreshResult:
    status: str
    message: str
    warning_messages: list[str] = field(default_factory=list)
    imported_count: int = 0
    source_failures: int = 0


class RefreshCoordinator:
    def __init__(
        self,
        *,
        portfolio_csv_path: Path | None = None,
        source_handlers: Mapping[str, SourceHandler] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self._lock = lock or _REFRESH_LOCK
        self._portfolio_csv_path = portfolio_csv_path
        self._source_handlers = dict(source_handlers or {})

    def run_refresh(
        self,
        database_url: str,
        *,
        snapshot_date: str,
        sources: Sequence[str] | None = None,
        include_portfolio_import: bool = True,
    ) -> RefreshResult:
        if not self._lock.acquire(blocking=False):
            return RefreshResult(
                status="already_running",
                message="Refresh already running. Try again when the current run finishes.",
            )

        try:
            import_result = None
            if include_portfolio_import:
                import_result = self._import_saved_portfolio_snapshot(
                    database_url,
                    snapshot_date=snapshot_date,
                )
            database_path = sqlite_path_from_url(database_url)
            active_sources = list(sources or REFRESH_SOURCE_ORDER)
            source_failures = 0
            source_warning_messages: list[str] = []
            for source in active_sources:
                source_succeeded, warning_messages = self._run_source(
                    database_path, source
                )
                source_warning_messages.extend(warning_messages)
                if not source_succeeded:
                    source_failures += 1

            signal_succeeded, signal_warnings = self._run_signal_persistence_step(
                database_path, snapshot_date
            )
            source_warning_messages.extend(signal_warnings)
            if not signal_succeeded:
                source_failures += 1
        except Exception as exc:
            return RefreshResult(
                status="failed",
                message=f"Refresh failed: {exc}",
            )
        finally:
            self._lock.release()

        return RefreshResult(
            status="completed",
            message=_build_refresh_message(
                import_result,
                source_failures,
                include_portfolio_import=include_portfolio_import,
            ),
            warning_messages=[
                *([] if import_result is None else import_result.warning_messages),
                *source_warning_messages,
            ],
            imported_count=0 if import_result is None else import_result.imported_count,
            source_failures=source_failures,
        )

    def _import_saved_portfolio_snapshot(
        self,
        database_url: str,
        *,
        snapshot_date: str,
    ) -> PortfolioImportResult | None:
        if self._portfolio_csv_path is None or not self._portfolio_csv_path.exists():
            return None

        with self._portfolio_csv_path.open("rb") as uploaded_file:
            return import_ii_portfolio_snapshot(
                database_url,
                uploaded_file,
                snapshot_date=snapshot_date,
            )

    def _run_signal_persistence_step(
        self, database_path: Path, reading_date: str
    ) -> tuple[bool, list[str]]:
        try:
            with _connect_writer(database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                run_signal_persistence(connection, reading_date=reading_date, now=_utc_now())
                connection.commit()
                return True, []
        except Exception as exc:
            return False, [f"Signal persistence failed: {exc}"]

    def _run_source(self, database_path: Path, source: str) -> tuple[bool, list[str]]:
        handler = self._source_handlers.get(source, _not_implemented_handler(source))

        run_started_at = _utc_now()
        try:
            with _connect_writer(database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                warning_messages = handler(connection) or []
                _insert_refresh_log(
                    connection,
                    source=source,
                    run_started_at=run_started_at,
                    status="completed",
                    error_message=None,
                )
                connection.commit()
                return True, warning_messages
        except Exception as exc:
            with _connect_writer(database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                _insert_refresh_log(
                    connection,
                    source=source,
                    run_started_at=run_started_at,
                    status="failed",
                    error_message=str(exc),
                )
                connection.commit()
            return False, []


def _connect_writer(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _insert_refresh_log(
    connection: sqlite3.Connection,
    *,
    source: str,
    run_started_at: str,
    status: str,
    error_message: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO refresh_log (
            source,
            run_started_at,
            finished_at,
            status,
            error_msg
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            source,
            run_started_at,
            _utc_now(),
            status,
            error_message,
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _not_implemented_handler(source: str) -> SourceHandler:
    def handler(_connection: sqlite3.Connection) -> None:
        raise NotImplementedError(f"{source} refresh is not implemented yet.")

    return handler


def _build_refresh_message(
    import_result: PortfolioImportResult | None,
    source_failures: int,
    *,
    include_portfolio_import: bool,
) -> str:
    if not include_portfolio_import:
        portfolio_message = "Market data refresh"
    elif import_result is None:
        portfolio_message = "No saved portfolio CSV was available"
    else:
        portfolio_message = (
            f"Imported {import_result.imported_count} holdings from the saved portfolio CSV"
        )

    if source_failures == 0:
        if not include_portfolio_import:
            return f"{portfolio_message} completed."
        return f"{portfolio_message}. Refresh completed."

    if source_failures == 1:
        failure_message = "1 source failed"
    else:
        failure_message = f"{source_failures} sources failed"

    if not include_portfolio_import:
        return f"{portfolio_message} completed with {failure_message}."
    return f"{portfolio_message}. Refresh completed with {failure_message}."
