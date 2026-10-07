# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         data_collection_setup/main.py
# Date:         06-10-2026
# Description:  Database setup driver: creates data/gtfs.db with routes, stops and positions.
# Usage:        python -m data_collection_setup [--reset]
"""Database setup driver: creates data/gtfs.db with routes, stops and positions.
  - Creates data/ if it is missing (shared/config.py)
  - Creates (or reuses) the SQLite file data/gtfs.db
  - Creates the three pipeline tables if they do not exist yet:
      routes    - the selected routes: demand, timetable, ranks, score and direction
      stops     - the chosen stops per route: boardings, quadrant and rank
      positions - the live vehicle pings collected by the polling loop
  - Re-runs are safe: existing tables and their rows are left untouched.
    --reset deletes data/gtfs.db (with its -wal and -shm sidecars) first, which
    also wipes every collected position; use it only to start a collection over.

Relationships (one-to-many; no junction tables needed):
  routes 1 --- n stops     stops.route  -> routes.route, NOT NULL: every stop row
                            belongs to exactly one route (a physical stop may still
                            be chosen by two routes, so the key is (route, stop_id)).
  routes 1 --- n positions positions.route -> routes.route: route is the base code
                            (e.g. "G10"); trip_route_id keeps the raw GTFS id from the
                            feed, which may be a variant such as "G10A", so it cannot be
                            the foreign key itself.

Writers should run "PRAGMA foreign_keys = ON" on their connection, SQLite only
enforces foreign keys per connection.
"""

import argparse
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
    boardings_rank  INTEGER,
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

# Live vehicle pings: one row per vehicle report.
# route is the base code of trip_route_id (strip_route_variants) and is the
# foreign key into routes; trip_route_id keeps the feed's raw (variant) id.
# A vehicle reports the same timestamp across polls until it moves on, so
# (vehicle_id, timestamp) is unique and the collector inserts with OR IGNORE.
POSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS positions (
    entity_id                  TEXT,
    position_bearing           REAL,
    position_latitude          REAL,
    position_longitude         REAL,
    position_speed             REAL,
    timestamp                  INTEGER,
    trip_direction_id          INTEGER,
    route                      TEXT REFERENCES routes(route),
    trip_route_id              TEXT,
    trip_schedule_relationship TEXT,
    trip_start_date            TEXT,
    trip_trip_id               TEXT,
    vehicle_id                 TEXT,
    vehicle_label              TEXT,
    UNIQUE (vehicle_id, timestamp)
)
"""

POSITIONS_TIMESTAMP_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_positions_timestamp ON positions (timestamp)")

POSITIONS_ROUTE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_positions_route ON positions (route)")


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


def create_database(db_path=DB_PATH, reset=False):
    """Creates the three pipeline tables in db_path if they do not exist yet.

    Existing tables and rows are kept, so a re-run never loses collected data.

    Args:
        db_path: Path of the SQLite file to create or reuse.
        reset: If True, delete db_path (and its sidecars) first.

    Returns:
        Path: the path of the database file.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        delete_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(ROUTES_DDL)
        conn.execute(STOPS_DDL)
        conn.execute(POSITIONS_DDL)
        conn.execute(POSITIONS_TIMESTAMP_INDEX)
        conn.execute(POSITIONS_ROUTE_INDEX)
    return db_path


def main():
    """Creates data/gtfs.db with the three pipeline tables (--reset wipes it first)."""
    parser = argparse.ArgumentParser(description="Create the pipeline database tables.")
    parser.add_argument("--reset", action="store_true",
                        help="delete data/gtfs.db first (wipes collected positions)")
    args = parser.parse_args()

    existed = DB_PATH.exists()
    db_path = create_database(reset=args.reset)
    with sqlite3.connect(db_path) as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('routes', 'stops', 'positions') ORDER BY name")]
    if args.reset and existed:
        action = "recreated"
    elif existed:
        action = "kept existing tables in"
    else:
        action = "created"
    print("%s %s" % (action, db_path))
    print("tables: %s" % ", ".join(tables))


if __name__ == "__main__":
    main()
