from __future__ import annotations

from pathlib import Path
import sqlite3

from sqlalchemy.engine import make_url

from investment_optimiser.migrations import MIGRATIONS


def sqlite_path_from_url(database_url: str) -> Path:
    url = make_url(database_url)
    if url.drivername != "sqlite":
        raise ValueError("Only sqlite URLs are supported for the local app shell.")

    database = url.database
    if not database:
        raise ValueError("SQLite URL must include a database path.")

    return Path(database)


def initialize_database(database_url: str) -> int:
    database_path = sqlite_path_from_url(database_url)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

        current_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        for version, migration in enumerate(MIGRATIONS, start=1):
            if version <= current_version:
                continue

            with connection:
                migration(connection)
                connection.execute(f"PRAGMA user_version = {version}")

        return int(connection.execute("PRAGMA user_version").fetchone()[0])
