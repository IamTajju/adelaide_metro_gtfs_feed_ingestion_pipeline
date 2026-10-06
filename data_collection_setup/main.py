# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         data_collection_setup/main.py
# Date:         06-10-2026
# Description:  Database setup driver: creates data/gtfs.db with routes, stops and positions.
# Usage:        python -m data_collection_setup
"""Database setup driver: creates data/gtfs.db with routes, stops and positions.
  - Creates data/ if it is missing (shared/config.py)
  - Creates (or reuses) the SQLite file data/gtfs.db
  - Creates the three pipeline tables if they do not exist yet:
      routes    - the selected routes: demand, timetable, ranks, score and direction
      stops     - the chosen stops per route: boardings, quadrant and rank
      positions - the live vehicle pings collected by the polling loop
  - Deletes any previous data/gtfs.db (with its -wal and -shm sidecars) first, so
    every run starts from an empty database holding only these three tables.

Relationships (one-to-many; no junction tables needed):
  routes 1 --- n stops     stops.route  -> routes.route, NOT NULL: every stop row
                            belongs to exactly one route (a physical stop may still
                            be chosen by two routes, so the key is (route, stop_id)).
  routes 1 --- n positions positions.trip_route_id -> routes.route: a ping belongs
                            to at most one route, and trip_route_id already carries
                            that route code.

Writers should run "PRAGMA foreign_keys = ON" on their connection, SQLite only
enforces foreign keys per connection.
"""

import sqlite3
from pathlib import Path

from shared import config

DB_PATH = config.DATA_DIR / "gtfs.db"

# Chosen routes: demand (CBD boardings), timetable (weekday trips), ranks and score.
# route is the primary key the stops and positions foreign keys point at.
ROUTES_DDL = """
CREATE TABLE IF NOT EXISTS routes (
    route           TEXT PRIMARY KEY,
    cbd_boardings   INTEGER,
    gtfs_route_ids  TEXT,
    weekday_trips   INTEGER,
    boarding_rank   INTEGER,
    trips_rank      INTEGER,
    score           REAL,
    direction       TEXT
)
"""

# Chosen stops per route: boardings on that route and the N/S/E/W quadrant.
# Every row belongs to one route (route NOT NULL), a physical stop may still be
# chosen by another route, hence the (route, stop_id) key instead of stop_id alone.
STOPS_DDL = """
CREATE TABLE IF NOT EXISTS stops (
    route              TEXT NOT NULL REFERENCES routes(route),
    stop_id            TEXT,
    stop_name          TEXT,
    stop_lat           REAL,
    stop_lon           REAL,
    stop_boardings     INTEGER,
    quadrant           TEXT,
    stop_rank_on_route INTEGER,
    chosen_by          TEXT,
    PRIMARY KEY (route, stop_id)
)
"""

# Live vehicle pings: one row per polled vehicle entity per fetch.
# trip_route_id is the route of the ping, so it doubles as the foreign key into
# routes; it is left NULLable for pings that do not belong to a chosen route.
POSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS positions (
    entity_id                  TEXT,
    position_bearing           REAL,
    position_latitude          REAL,
    position_longitude         REAL,
    position_speed             REAL,
    timestamp                  INTEGER,
    trip_direction_id          INTEGER,
    trip_route_id              TEXT REFERENCES routes(route),
    trip_schedule_relationship TEXT,
    trip_start_date            TEXT,
    trip_trip_id               TEXT,
    vehicle_id                 TEXT,
    vehicle_label              TEXT
)
"""

POSITIONS_TIMESTAMP_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_positions_timestamp ON positions (timestamp)")

POSITIONS_ROUTE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_positions_trip_route_id ON positions (trip_route_id)")


def delete_database(db_path=DB_PATH):
    """Deletes db_path and its write-ahead log sidecars, if they exist.

    Args:
        db_path: Path of the SQLite file to delete.

    Returns:
        bool: True if a file was removed, False otherwise.
    """
    removed = False
    for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        path = Path(path)
        if path.exists():
            path.unlink()
            removed = True
    return removed


def create_database(db_path=DB_PATH):
    """Deletes db_path if it exists, then creates it with the three pipeline tables.

    Args:
        db_path: Path of the SQLite file to (re)create.

    Returns:
        Path: the path of the database file.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    delete_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(ROUTES_DDL)
        conn.execute(STOPS_DDL)
        conn.execute(POSITIONS_DDL)
        conn.execute(POSITIONS_TIMESTAMP_INDEX)
        conn.execute(POSITIONS_ROUTE_INDEX)
    return db_path


def main():
    """Recreates data/gtfs.db with the three pipeline tables and lists them."""
    replaced = DB_PATH.exists()
    db_path = create_database()
    with sqlite3.connect(db_path) as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('routes', 'stops', 'positions') ORDER BY name")]
    print("%s %s" % ("recreated" if replaced else "created", db_path))
    print("tables: %s" % ", ".join(tables))


if __name__ == "__main__":
    main()
