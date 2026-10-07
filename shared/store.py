# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         shared/store.py
# Date:         27-09-2026
# Description:  SQLite tables and insert helpers.
# Usage:        from shared import store
"""SQLite tables and insert helpers.

TODO: T01 (see docs/TICKETS.md).
"""

import sqlite3
from datetime import datetime, timezone

from shared import config


DB_PATH = config.DATA_DIR / "gtfs.db"

def connect():
    """Opens the SQL database

    Returns:
        sqlite3.Connection configured to return rows by column name.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    return conn


def initialise_database(conn):
    """Creates the database tables required by the ingestion pipeline."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_stop_times (
            gtfs_version TEXT NOT NULL,

            route TEXT NOT NULL,
            route_id TEXT NOT NULL,
            route_short_name TEXT NOT NULL,

            service_id TEXT NOT NULL,
            trip_id TEXT NOT NULL,

            direction_id TEXT,
            shape_id TEXT,

            stop_id TEXT NOT NULL,
            stop_sequence INTEGER NOT NULL,

            scheduled_arrival TEXT,
            scheduled_departure TEXT,

            arrival_seconds INTEGER,
            departure_seconds INTEGER,

            pickup_type TEXT,
            drop_off_type TEXT,
            timepoint TEXT,

            PRIMARY KEY (
                gtfs_version,
                trip_id,
                stop_sequence
            )
        );

        CREATE INDEX IF NOT EXISTS idx_scheduled_trip
            ON scheduled_stop_times (trip_id);

        CREATE INDEX IF NOT EXISTS idx_scheduled_trip_stop
            ON scheduled_stop_times (trip_id, stop_id);

        CREATE INDEX IF NOT EXISTS idx_scheduled_stop
            ON scheduled_stop_times (stop_id);

        CREATE INDEX IF NOT EXISTS idx_scheduled_route
            ON scheduled_stop_times (route);

        CREATE TABLE IF NOT EXISTS quarantine (
        quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,

        quarantined_at INTEGER NOT NULL,

        entity_id TEXT,
        vehicle_id TEXT,
        trip_id TEXT,
        route_id TEXT,

        timestamp INTEGER,
        latitude REAL,
        longitude REAL,

        reason TEXT NOT NULL,
        details TEXT,

        raw_record TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_quarantine_reason
        ON quarantine (reason);

    CREATE INDEX IF NOT EXISTS idx_quarantine_trip
        ON quarantine (trip_id);

    CREATE INDEX IF NOT EXISTS idx_quarantine_timestamp
        ON quarantine (timestamp);
        """
    )

    conn.commit()


def get_state(conn, key, default=None):
    """Reads a value from pipeline_state."""
    row = conn.execute(
        "SELECT value FROM pipeline_state WHERE key = ?",
        (key,),
    ).fetchone()

    if row is None:
        return default

    return row["value"]


def set_state(conn, key, value):
    """Creates or updates a pipeline state value."""
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO pipeline_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, str(value), now),
    )