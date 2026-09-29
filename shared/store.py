# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         shared/store.py
# Date:         28-09-2026
# Description:  SQLite tables and insert helpers.
# Usage:        from shared import store
"""SQLite tables and insert helpers.

One database (data/gtfs.db) holds every table in the project.  Tables built from
a file (gtfs_*, validations) take their columns from the file itself, so a new
Adelaide Metro feed version with an added or dropped column cannot break a load.
Those columns are TEXT unless COLUMN_TYPES names them, which keeps ids, codes
and GTFS times ("15:32:00") exactly as published.

A reload replaces a table wholesale (DROP, CREATE, INSERT), so running a stage
twice leaves one copy of the data.  Column names come from the file headers and
are quoted, since a feed could name a column in a way SQL would object to.
"""

import sqlite3
from pathlib import Path

import pandas as pd

from shared import config

# SQLite type per column, for the columns that are not text.  A name that the
# file does not have is ignored, so a new feed version is still loadable.
COLUMN_TYPES = {
    "gtfs_calendar": {
        "monday": "INTEGER", "tuesday": "INTEGER", "wednesday": "INTEGER",
        "thursday": "INTEGER", "friday": "INTEGER", "saturday": "INTEGER",
        "sunday": "INTEGER",
    },
    "gtfs_calendar_dates": {"exception_type": "INTEGER"},
    "gtfs_routes": {"route_type": "INTEGER"},
    "gtfs_stops": {
        "stop_lat": "REAL", "stop_lon": "REAL", "location_type": "INTEGER",
        "wheelchair_boarding": "INTEGER",
    },
    "gtfs_stop_times": {
        "stop_sequence": "INTEGER", "pickup_type": "INTEGER",
        "drop_off_type": "INTEGER", "shape_dist_traveled": "REAL",
        "timepoint": "INTEGER",
    },
    "gtfs_shapes": {
        "shape_pt_lat": "REAL", "shape_pt_lon": "REAL",
        "shape_pt_sequence": "INTEGER", "shape_dist_traveled": "REAL",
    },
    "gtfs_transfers": {"transfer_type": "INTEGER",
                       "min_transfer_time": "INTEGER"},
    "gtfs_trips": {"direction_id": "INTEGER",
                   "wheelchair_accessible": "INTEGER"},
    # GTFS_ID stays text: it is the stop key of the validations file, and a
    # number there must not turn into a float that misses a text stop id.
    "validations": {
        "NUM_MODE_TRANSPORT": "INTEGER", "ROUTE_DIRECTION": "INTEGER",
        "MEDIUM_TYPE": "INTEGER", "BAND_BOARDINGS_FLOOR": "INTEGER",
    },
    # Live realtime feed, flattened by get_gtfs_positions into snake_case
    # keys (entity_id, trip_trip_id, ...).  The trip and vehicle ids stay text
    # so they never lose a leading zero; only numbers known to be numbers are
    # converted.
    "gtfs_positions": {
        "position_bearing": "REAL",
        "position_latitude": "REAL",
        "position_longitude": "REAL",
        "position_speed": "REAL",
        "timestamp": "INTEGER",
        "trip_direction_id": "INTEGER",
    },
}

# Columns of the live vehicle_positions feed, flattened the way
# get_gtfs_positions flattens it, in the order the table should show them.
# Extra fields the feed emits (e.g. position_odometer, stop_id) are dropped by
# insert_rows until they are listed here.
GTFS_POSITIONS_COLUMNS = [
    "entity_id",
    "position_bearing",
    "position_latitude",
    "position_longitude",
    "position_speed",
    "timestamp",
    "trip_direction_id",
    "trip_route_id",
    "trip_schedule_relationship",
    "trip_start_date",
    "trip_trip_id",
    "vehicle_id",
    "vehicle_label",
]

# Indices for the joins the later stages do: trips by route, scheduled times by
# trip and stop, validations by route and stop, and live polls by their time.
INDEXES = [
    ("gtfs_trips", ["route_id"]),
    ("gtfs_stop_times", ["trip_id", "stop_sequence"]),
    ("gtfs_stop_times", ["stop_id"]),
    ("validations", ["ROUTE_CODE"]),
    ("validations", ["GTFS_ID"]),
    ("gtfs_positions", ["timestamp"]),
]

# Rows per INSERT batch, so a large file does not become one huge statement.
CHUNK_ROWS = 50_000

# Key/value notes written as part of a load, e.g. the timetable version and the
# validations quarter, with a timestamp of the last load.
META_DDL = """CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    loaded_at TEXT DEFAULT CURRENT_TIMESTAMP
)"""


def connect(path=None):
    """Opens the project database, creating the folder if it is missing.

    Args:
        path: Optional path to a database file, e.g. a test copy.

    Returns:
        An open sqlite3 connection.
    """
    path = Path(config.DB_PATH if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def apply_types(frame, types):
    """Converts the columns named in types to numbers.

    SQLite keeps a whole float in an INTEGER column as an integer, so integer
    columns are converted the same way as the float ones.  Anything that is not
    a number becomes empty (NULL), which is how a blank cell is stored.

    Args:
        frame: DataFrame to convert.
        types: Dict of column name to SQLite type; a column the frame lacks is
            ignored.

    Returns:
        The frame with the named columns converted.
    """
    decoded = frame.copy()
    for column in (types or {}):
        if column in decoded.columns:
            decoded[column] = pd.to_numeric(decoded[column], errors="coerce")
    return decoded


def create_table(conn, table, columns, types=None):
    """Creates a table with one column per name, replacing any existing one.

    Args:
        conn: Open connection to the database.
        table: Name of the table to create.
        columns: Column names, in the order they should appear.
        types: Optional dict of column name to SQLite type; others are TEXT.

    Returns:
        The table name.
    """
    types = types or {}
    columns_sql = ", ".join('"%s" %s' % (name, types.get(name, "TEXT"))
                            for name in columns)
    conn.execute('DROP TABLE IF EXISTS "%s"' % table)
    conn.execute('CREATE TABLE "%s" (%s)' % (table, columns_sql))
    return table


def ensure_table(conn, table, columns, types=None):
    """Creates a table if it does not exist, leaving any rows untouched.

    Unlike create_table, this never drops an existing table, so a table that
    accumulates rows, such as gtfs_vehicle_positions, survives a setup re-run.

    Args:
        conn: Open connection to the database.
        table: Name of the table to create.
        columns: Column names, in the order they should appear.
        types: Optional dict of column name to SQLite type; other columns are
            TEXT and COLUMN_TYPES is used for the unnamed types.

    Returns:
        The table name.
    """
    if types is None:
        types = COLUMN_TYPES.get(table, {})
    columns_sql = ", ".join('"%s" %s' % (name, types.get(name, "TEXT"))
                            for name in columns)
    conn.execute('CREATE TABLE IF NOT EXISTS "%s" (%s)' % (table, columns_sql))
    return table


def insert_rows(conn, table, frame):
    """Appends the rows of a DataFrame to a table that already exists.

    The columns are converted with COLUMN_TYPES, and a column the table does
    not have is dropped, so a re-read of the same file still lines up.

    Args:
        conn: Open connection to the database.
        table: Name of an existing table.
        frame: DataFrame holding the rows to append.

    Returns:
        Number of rows appended.
    """
    if frame.empty:
        return 0
    columns = [row[1] for row in conn.execute('PRAGMA table_info("%s")' % table)]
    frame = frame[[name for name in frame.columns if name in columns]]
    frame = apply_types(frame, COLUMN_TYPES.get(table))
    frame.to_sql(table, conn, if_exists="append", index=False,
                 chunksize=CHUNK_ROWS)
    return len(frame)


def replace_table(conn, table, frame):
    """Loads a DataFrame into a fresh table, replacing the old contents.

    Args:
        conn: Open connection to the database.
        table: Name of the table to replace.
        frame: DataFrame whose columns become the table columns.

    Returns:
        Number of rows written.
    """
    create_table(conn, table, frame.columns, COLUMN_TYPES.get(table))
    return insert_rows(conn, table, frame)


def table_names(conn):
    """Lists the tables in the database, in alphabetical order.

    Args:
        conn: Open connection to the database.

    Returns:
        List of table names.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [name for (name,) in rows]


def row_counts(conn, tables=None):
    """Counts the rows of each table.

    Args:
        conn: Open connection to the database.
        tables: Optional list of tables to count; all of them by default.

    Returns:
        Dict of table name to row count.
    """
    return {table: conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
            for table in (table_names(conn) if tables is None else tables)}


def create_indexes(conn):
    """Creates the indices in INDEXES, skipping any whose table is absent.

    Args:
        conn: Open connection to the database.

    Returns:
        List of the index names that were created.
    """
    existing = set(table_names(conn))
    created = []
    for table, columns in INDEXES:
        if table not in existing:
            continue
        name = "idx_%s_%s" % (table, "_".join(columns))
        columns_sql = ", ".join('"%s"' % column for column in columns)
        conn.execute('CREATE INDEX IF NOT EXISTS "%s" ON "%s" (%s)'
                     % (name, table, columns_sql))
        created.append(name)
    return created


def create_meta(conn):
    """Creates the meta table if it is not there yet.

    Args:
        conn: Open connection to the database.
    """
    conn.execute(META_DDL)


def set_meta(conn, key, value):
    """Records one value in the meta table, e.g. the timetable version.

    Args:
        conn: Open connection to the database.
        key: Name of the value.
        value: Value to store; stored as text.
    """
    create_meta(conn)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 (key, str(value)))


def get_meta(conn, key):
    """Reads one value back from the meta table.

    Args:
        conn: Open connection to the database.
        key: Name of the value.

    Returns:
        The value as a string, or None if it was never recorded.
    """
    create_meta(conn)
    row = conn.execute("SELECT value FROM meta WHERE key = ?",
                       (key,)).fetchone()
    return None if row is None else row[0]
