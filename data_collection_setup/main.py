# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         data_collection_setup/main.py
# Date:         06-10-2026
# Description:  Database setup driver: creates data/gtfs.db with routes, stops, positions and arrivals.
# Usage:        python -m data_collection_setup [--reset]
"""Database setup driver: creates data/gtfs.db with routes, stops, positions and arrivals.
  - Creates data/ if it is missing (shared/config.py)
  - Creates (or reuses) the SQLite file config.DB_PATH (data/gtfs.db)
  - Creates the four pipeline tables if they do not exist yet:
      routes    - the selected routes: demand, timetable, ranks, score and direction
      stops     - the chosen stops per route: boardings, quadrant and rank
      positions - the live vehicle pings collected by the polling loop
      arrivals  - observed (closest ping) vs scheduled arrival per trip, stop and date
  - Re-runs are safe: existing tables and their rows are left untouched.
  - route_selection and stop_selection write the routes and stops tables through
    replace_top_k_routes_in_database / replace_top_m_stops_in_database.
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
  arrivals                  derived from positions + the timetable; route_id holds the
                            base code, but there is no foreign key, so arrivals collected
                            under an earlier selection survive a new one.

Writers should run "PRAGMA foreign_keys = ON" on their connection, SQLite only
enforces foreign keys per connection. Replacing the selection therefore has a
fixed order: delete stops, then routes; insert routes, then stops. Positions
point at routes too, so a route that already has positions cannot be deleted;
reset the database (--reset) to start a collection with a new selection.
"""

import argparse
import sqlite3
from pathlib import Path

from shared import config

DB_PATH = config.DB_PATH

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
    trip_schedule_relationship INTEGER,
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

# Observed vs scheduled arrival per trip, stop and service date, filled by
# gtfs_position_collection.arrivals; a rerun replaces the row of the same key.
ARRIVALS_DDL = """
CREATE TABLE IF NOT EXISTS arrivals (
    trip_id           TEXT NOT NULL,
    stop_id           TEXT NOT NULL,
    service_date      TEXT NOT NULL,
    route_id          TEXT,
    observed_arrival  TEXT,
    scheduled_arrival TEXT,
    distance_m        REAL,
    PRIMARY KEY (trip_id, stop_id, service_date)
)
"""


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
    """Creates the four pipeline tables in db_path if they do not exist yet.

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
        conn.execute(ARRIVALS_DDL)
    return db_path


ROUTES_COLUMNS = ["route", "cbd_boardings", "gtfs_route_ids", "weekday_trips",
                  "boardings_rank", "trips_rank", "score", "direction"]
STOPS_COLUMNS = ["route", "stop_id", "stop_name", "stop_lat", "stop_lon", "stop_boardings",
                 "quadrant", "stop_rank_on_route", "chosen_by"]
POSITIONS_COLUMNS = ["entity_id", "position_bearing", "position_latitude", "position_longitude",
                     "position_speed", "timestamp", "trip_direction_id", "route", "trip_route_id",
                     "trip_schedule_relationship", "trip_start_date", "trip_trip_id",
                     "vehicle_id", "vehicle_label"]


def convert_to_database_rows(frame, columns):
    """Turns DataFrame rows into plain Python tuples sqlite3 can bind (NaN -> NULL)."""
    plain_frame = frame[columns].astype(object)
    return plain_frame.where(plain_frame.notna(), None).itertuples(index=False, name=None)


def replace_rows_in_database(table, frame, columns, tables_to_clear_first, db_path=DB_PATH):
    """Replaces every row of a selection table in one transaction.

    Creates the tables first if setup has not run yet. Foreign keys are on, so
    dependent tables (tables_to_clear_first) are emptied before the table itself.

    Raises:
        RuntimeError: if a foreign key fails, i.e. collected positions still point
            at the old selection, or a stop's route is not in the routes table.
    """
    create_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:  # One transaction: all of it, or none of it on an error.
            for dependent_table in tables_to_clear_first:
                conn.execute("DELETE FROM %s" % dependent_table)
            conn.execute("DELETE FROM %s" % table)
            conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (
                table, ", ".join(columns), ", ".join("?" * len(columns))),
                convert_to_database_rows(frame, columns))
    except sqlite3.IntegrityError as error:
        raise RuntimeError(
            "cannot replace %s in %s (%s): either collected positions still point at "
            "the old selection (run `python -m data_collection_setup --reset` to start "
            "a new collection), or a stop's route is not in the routes table (run "
            "`make route_selection` first)" % (table, db_path, error)) from error
    finally:
        conn.close()
    return len(frame)


def replace_top_k_routes_in_database(top_k_routes, db_path=DB_PATH):
    """Writes the top k routes to the routes table, replacing the old selection.

    The stops of the old routes are removed with them (stops point at routes), so
    stop selection has to run again afterwards; `make selection` does that.

    Args:
        top_k_routes: DataFrame with the ROUTES_COLUMNS (route_selection output).
        db_path: Path of the SQLite file.

    Returns:
        Number of routes written.
    """
    return replace_rows_in_database("routes", top_k_routes, ROUTES_COLUMNS,
                                    tables_to_clear_first=["stops"], db_path=db_path)


def replace_top_m_stops_in_database(top_m_stops, db_path=DB_PATH):
    """Writes the top m stops to the stops table, replacing the old selection.

    Args:
        top_m_stops: DataFrame with the STOPS_COLUMNS (stop_selection output); every
            route must already be in the routes table.
        db_path: Path of the SQLite file.

    Returns:
        Number of route x stop rows written.
    """
    return replace_rows_in_database("stops", top_m_stops, STOPS_COLUMNS,
                                    tables_to_clear_first=[], db_path=db_path)


def main():
    """Creates data/gtfs.db with the four pipeline tables (--reset wipes it first)."""
    parser = argparse.ArgumentParser(description="Create the pipeline database tables.")
    parser.add_argument("--reset", action="store_true",
                        help="delete data/gtfs.db first (wipes collected positions)")
    args = parser.parse_args()

    existed = DB_PATH.exists()
    db_path = create_database(reset=args.reset)
    with sqlite3.connect(db_path) as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('routes', 'stops', 'positions', 'arrivals') ORDER BY name")]
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
