from __future__ import annotations

from collections.abc import Callable
import sqlite3


Migration = Callable[[sqlite3.Connection], None]


def create_initial_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            snapshot_date    TEXT NOT NULL,
            symbol           TEXT NOT NULL,
            isin             TEXT,
            instrument_name  TEXT NOT NULL,
            asset_type       TEXT NOT NULL CHECK (
                asset_type IN (
                    'gilt_conventional',
                    'gilt_index_linked',
                    'mmf',
                    'equity',
                    'etf',
                    'investment_trust',
                    'reit',
                    'fund',
                    'other'
                )
            ),
            quantity         REAL NOT NULL,
            clean_price_gbp  REAL,
            market_value_gbp REAL NOT NULL,
            book_cost_gbp    REAL,
            import_warning   TEXT,
            weight_pct       REAL NOT NULL,
            PRIMARY KEY (snapshot_date, symbol)
        ) STRICT, WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS signal_readings (
            reading_date TEXT NOT NULL,
            signal_name  TEXT NOT NULL,
            metric_name  TEXT NOT NULL,
            value        REAL NOT NULL,
            unit         TEXT NOT NULL,
            PRIMARY KEY (reading_date, signal_name, metric_name)
        ) STRICT, WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_signal_readings_metric_history
        ON signal_readings(signal_name, metric_name, reading_date DESC);

        CREATE TABLE IF NOT EXISTS signal_events (
            id           INTEGER PRIMARY KEY,
            alert_type   TEXT NOT NULL,
            scope_key    TEXT NOT NULL,
            severity     TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
            started_at   TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            cleared_at   TEXT,
            message      TEXT NOT NULL,
            details_json TEXT NOT NULL CHECK (json_valid(details_json))
        ) STRICT;

        CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_events_active
        ON signal_events(alert_type, scope_key)
        WHERE cleared_at IS NULL;

        CREATE INDEX IF NOT EXISTS ix_signal_events_active_lookup
        ON signal_events(alert_type, scope_key, started_at)
        WHERE cleared_at IS NULL;

        CREATE INDEX IF NOT EXISTS ix_signal_events_history
        ON signal_events(started_at DESC);

        CREATE TABLE IF NOT EXISTS decision_log (
            id                   INTEGER PRIMARY KEY,
            decision_date        TEXT NOT NULL,
            signal_event_id      INTEGER REFERENCES signal_events(id) ON DELETE SET NULL,
            action               TEXT NOT NULL CHECK (action IN ('acted', 'passed', 'deferred')),
            instruments_affected TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(instruments_affected)),
            notes                TEXT NOT NULL DEFAULT '',
            created_at           TEXT NOT NULL
        ) STRICT;

        CREATE INDEX IF NOT EXISTS ix_decision_log_created_at
        ON decision_log(created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_decision_log_signal_event
        ON decision_log(signal_event_id);

        CREATE TABLE IF NOT EXISTS yield_curve_cache (
            cache_date      TEXT NOT NULL,
            curve_key       TEXT NOT NULL,
            maturity_years  REAL,
            rate_pct        REAL NOT NULL,
            series_code     TEXT,
            fetched_at      TEXT NOT NULL,
            PRIMARY KEY (cache_date, curve_key)
        ) STRICT, WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_yield_curve_cache_history
        ON yield_curve_cache(curve_key, cache_date DESC);

        CREATE TABLE IF NOT EXISTS gilt_price_cache (
            cache_date              TEXT NOT NULL,
            isin                    TEXT NOT NULL,
            clean_price_gbp         REAL NOT NULL,
            gry_pct                 REAL,
            modified_duration_years REAL,
            coupon_pct              REAL NOT NULL,
            maturity_date           TEXT NOT NULL,
            fetched_at              TEXT NOT NULL,
            PRIMARY KEY (cache_date, isin)
        ) STRICT, WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_gilt_price_cache_history
        ON gilt_price_cache(isin, cache_date DESC);

        CREATE TABLE IF NOT EXISTS equity_price_cache (
            cache_date      TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            close_price_gbp REAL NOT NULL,
            volume          INTEGER,
            fetched_at      TEXT NOT NULL,
            PRIMARY KEY (cache_date, ticker)
        ) STRICT, WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_equity_price_cache_history
        ON equity_price_cache(ticker, cache_date DESC);

        CREATE TABLE IF NOT EXISTS equity_valuation_cache (
            cache_date  TEXT NOT NULL,
            source_name TEXT NOT NULL,
            pe_ratio    REAL NOT NULL,
            pe_as_of    TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (cache_date, source_name)
        ) STRICT, WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_equity_valuation_cache_history
        ON equity_valuation_cache(source_name, cache_date DESC);

        CREATE TABLE IF NOT EXISTS refresh_log (
            id             INTEGER PRIMARY KEY,
            source         TEXT NOT NULL CHECK (
                source IN (
                    'boe',
                    'dmo_reference',
                    'blackrock_ftse_pe',
                    'lse_gilt_prices',
                    'lse_tidm_bridge',
                    'non_gilt_reference',
                    'yfinance_equities'
                )
            ),
            run_started_at TEXT NOT NULL,
            finished_at    TEXT NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
            error_msg      TEXT
        ) STRICT;

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_finished
        ON refresh_log(source, finished_at DESC);

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_success
        ON refresh_log(source, finished_at DESC)
        WHERE status = 'completed';

        CREATE TABLE IF NOT EXISTS gilt_reference (
            isin             TEXT PRIMARY KEY,
            tidm             TEXT UNIQUE,
            instrument_name  TEXT NOT NULL,
            coupon_pct       REAL NOT NULL,
            maturity_date    TEXT NOT NULL,
            dividend_months  TEXT NOT NULL,
            dividend_day     INTEGER NOT NULL,
            ex_div_date      TEXT,
            instrument_type  TEXT NOT NULL CHECK (instrument_type IN ('Conventional', 'Index-linked')),
            maturity_bracket TEXT,
            last_updated     TEXT NOT NULL
        ) STRICT;

        CREATE INDEX IF NOT EXISTS ix_gilt_reference_tidm
        ON gilt_reference(tidm);

        CREATE INDEX IF NOT EXISTS ix_gilt_reference_maturity
        ON gilt_reference(maturity_date);

        CREATE TABLE IF NOT EXISTS allocation_runs (
            id                    INTEGER PRIMARY KEY,
            created_at            TEXT NOT NULL,
            policy_version        TEXT NOT NULL,
            baseline_version      TEXT NOT NULL,
            current_snapshot_date TEXT NOT NULL,
            regime_state          TEXT NOT NULL,
            scenario_set_name     TEXT NOT NULL,
            solver_status         TEXT NOT NULL,
            fallback_path         TEXT,
            snapshot_json         TEXT NOT NULL CHECK (json_valid(snapshot_json))
        ) STRICT;

        CREATE INDEX IF NOT EXISTS ix_allocation_runs_created_at
        ON allocation_runs(created_at DESC);

        CREATE INDEX IF NOT EXISTS ix_allocation_runs_policy_version
        ON allocation_runs(policy_version, created_at DESC);
        """
    )


def add_portfolio_snapshot_import_warning(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(portfolio_snapshots)")
    }
    if "import_warning" in existing_columns:
        return

    connection.execute(
        "ALTER TABLE portfolio_snapshots ADD COLUMN import_warning TEXT"
    )


def create_non_gilt_reference_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS non_gilt_reference (
            symbol          TEXT PRIMARY KEY,
            instrument_name TEXT NOT NULL,
            asset_type      TEXT NOT NULL CHECK (
                asset_type IN (
                    'equity',
                    'etf',
                    'investment_trust',
                    'reit',
                    'fund',
                    'other'
                )
            ),
            source_name     TEXT NOT NULL,
            source_label    TEXT NOT NULL,
            last_updated    TEXT NOT NULL
        ) STRICT, WITHOUT ROWID
        """
    )


def add_non_gilt_reference_refresh_source(connection: sqlite3.Connection) -> None:
    refresh_log_sql = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'refresh_log'
        """
    ).fetchone()
    if refresh_log_sql and "non_gilt_reference" in (refresh_log_sql[0] or ""):
        return

    connection.execute("ALTER TABLE refresh_log RENAME TO refresh_log_old")
    connection.executescript(
        """
        CREATE TABLE refresh_log (
            id             INTEGER PRIMARY KEY,
            source         TEXT NOT NULL CHECK (
                source IN (
                    'boe',
                    'dmo_reference',
                    'blackrock_ftse_pe',
                    'lse_gilt_prices',
                    'lse_tidm_bridge',
                    'non_gilt_reference',
                    'yfinance_equities'
                )
            ),
            run_started_at TEXT NOT NULL,
            finished_at    TEXT NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
            error_msg      TEXT
        ) STRICT;

        INSERT INTO refresh_log (
            id,
            source,
            run_started_at,
            finished_at,
            status,
            error_msg
        )
        SELECT
            id,
            source,
            run_started_at,
            finished_at,
            status,
            error_msg
        FROM refresh_log_old;

        DROP TABLE refresh_log_old;

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_finished
        ON refresh_log(source, finished_at DESC);

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_success
        ON refresh_log(source, finished_at DESC)
        WHERE status = 'completed';
        """
    )


def add_gilt_analytics_refresh_source(connection: sqlite3.Connection) -> None:
    refresh_log_sql = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'refresh_log'
        """
    ).fetchone()
    if refresh_log_sql and "gilt_analytics" in (refresh_log_sql[0] or ""):
        return

    connection.execute("ALTER TABLE refresh_log RENAME TO refresh_log_old")
    connection.executescript(
        """
        CREATE TABLE refresh_log (
            id             INTEGER PRIMARY KEY,
            source         TEXT NOT NULL CHECK (
                source IN (
                    'boe',
                    'dmo_reference',
                    'blackrock_ftse_pe',
                    'gilt_analytics',
                    'lse_gilt_prices',
                    'lse_tidm_bridge',
                    'non_gilt_reference',
                    'yfinance_equities'
                )
            ),
            run_started_at TEXT NOT NULL,
            finished_at    TEXT NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
            error_msg      TEXT
        ) STRICT;

        INSERT INTO refresh_log (
            id,
            source,
            run_started_at,
            finished_at,
            status,
            error_msg
        )
        SELECT
            id,
            source,
            run_started_at,
            finished_at,
            status,
            error_msg
        FROM refresh_log_old;

        DROP TABLE refresh_log_old;

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_finished
        ON refresh_log(source, finished_at DESC);

        CREATE INDEX IF NOT EXISTS ix_refresh_log_source_success
        ON refresh_log(source, finished_at DESC)
        WHERE status = 'completed';
        """
    )


def allow_gilt_price_cache_rows_without_analytics(
    connection: sqlite3.Connection,
) -> None:
    # Price refresh lands before the shared GRY/duration engine, so cache rows
    # must be able to exist in an intermediate price-only state.
    columns = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info(gilt_price_cache)")
    }
    if not columns:
        return
    if columns["gry_pct"][3] == 0 and columns["modified_duration_years"][3] == 0:
        return

    connection.execute("ALTER TABLE gilt_price_cache RENAME TO gilt_price_cache_old")
    connection.executescript(
        """
        CREATE TABLE gilt_price_cache (
            cache_date              TEXT NOT NULL,
            isin                    TEXT NOT NULL,
            clean_price_gbp         REAL NOT NULL,
            gry_pct                 REAL,
            modified_duration_years REAL,
            coupon_pct              REAL NOT NULL,
            maturity_date           TEXT NOT NULL,
            fetched_at              TEXT NOT NULL,
            PRIMARY KEY (cache_date, isin)
        ) STRICT, WITHOUT ROWID;

        INSERT INTO gilt_price_cache (
            cache_date,
            isin,
            clean_price_gbp,
            gry_pct,
            modified_duration_years,
            coupon_pct,
            maturity_date,
            fetched_at
        )
        SELECT
            cache_date,
            isin,
            clean_price_gbp,
            gry_pct,
            modified_duration_years,
            coupon_pct,
            maturity_date,
            fetched_at
        FROM gilt_price_cache_old;

        DROP TABLE gilt_price_cache_old;

        CREATE INDEX IF NOT EXISTS ix_gilt_price_cache_history
        ON gilt_price_cache(isin, cache_date DESC);
        """
    )


def add_portfolio_snapshot_maturity_date(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(portfolio_snapshots)")
    }
    if "maturity_date" in existing_columns:
        return
    connection.execute(
        "ALTER TABLE portfolio_snapshots ADD COLUMN maturity_date TEXT"
    )


def create_strategic_baseline_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategic_baseline (
            id             INTEGER PRIMARY KEY,
            created_at     TEXT    NOT NULL,
            label          TEXT    NOT NULL,
            policy_version TEXT    NOT NULL,
            weights_json   TEXT    NOT NULL CHECK (json_valid(weights_json)),
            notes          TEXT
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_strategic_baseline_created_at
        ON strategic_baseline(created_at DESC)
        """
    )


def add_il_gilt_gry_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(gilt_price_cache)")
    }
    if "real_gry_pct" not in existing_columns:
        connection.execute("ALTER TABLE gilt_price_cache ADD COLUMN real_gry_pct REAL")
    if "nominal_equivalent_gry_pct" not in existing_columns:
        connection.execute(
            "ALTER TABLE gilt_price_cache ADD COLUMN nominal_equivalent_gry_pct REAL"
        )


def create_equity_benchmark_prices_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS equity_benchmark_prices (
            price_date   TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            close_price  REAL NOT NULL,
            volume       INTEGER,
            fetched_at   TEXT NOT NULL,
            PRIMARY KEY (price_date, ticker)
        ) STRICT, WITHOUT ROWID
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_equity_benchmark_prices_ticker_date
        ON equity_benchmark_prices(ticker, price_date DESC)
        """
    )


MIGRATIONS: list[Migration] = [
    create_initial_schema,
    add_portfolio_snapshot_import_warning,
    create_non_gilt_reference_table,
    add_non_gilt_reference_refresh_source,
    allow_gilt_price_cache_rows_without_analytics,
    add_gilt_analytics_refresh_source,
    create_strategic_baseline_table,
    add_portfolio_snapshot_maturity_date,
    add_il_gilt_gry_columns,
    create_equity_benchmark_prices_table,
]
