# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         data_collection_setup/main.py
# Date:         28-09-2026
# Description:  Full static GTFS and validations load into the SQLite database.
# Usage:        python -m data_collection_setup
"""Full static GTFS and validations load into the SQLite database.

The whole static feed is stored, not just the chosen routes and stops: every
text file of the timetable becomes a gtfs_<name> table, and the newest
quarterly validations file becomes the validations table.  The collection stages
then filter those tables down to what they need.

Fetching is left to the helpers that already do it, so the downloads and the
caching rules live in one place: shared.timetable keeps the timetable at the
current version, and select_routes.validations picks the newest quarter.  This
stage only reads what is already on disk and writes it to data/gtfs.db.
"""

import pandas as pd

from shared import config, store
from shared import timetable
from select_routes import validations

# Validations are read a slice at a time: a quarter is around 60 MB of CSV.
VALIDATIONS_CHUNK_ROWS = 100_000

# The text files of the static feed, in the order they are stored.  Everything
# else in the timetable folder is ours, not GTFS: the version marker we wrote
# and the release notes Adelaide Metro ships with the zip.
GTFS_FILES = [
    "agency", "booking_rules", "calendar", "calendar_dates", "feed_info",
    "routes", "shapes", "stops", "stop_times", "transfers", "trips",
]


def load_gtfs(conn):
    """Loads every text file of the current static timetable into the database.

    Downloads the timetable if version.txt has moved on, then replaces one
    gtfs_<name> table per file, e.g. gtfs_stop_times.

    Args:
        conn: Open connection to the database.

    Returns:
        The timetable version that was loaded.
    """
    version = timetable.get_timetable_version()
    timetable.download_timetable(version)

    for name in GTFS_FILES:
        path = config.TIMETABLE_DIR / (name + ".txt")
        if not path.exists():
            print("%-24s not in this feed, skipped" % path.name)
            continue
        frame = pd.read_csv(path, dtype=str)
        rows = store.replace_table(conn, "gtfs_" + name, frame)
        conn.commit()
        print("%-24s %8d rows" % (path.name, rows))

    store.set_meta(conn, "timetable_version", version)
    conn.commit()
    return version


def load_validations(conn):
    """Loads the newest quarterly validations file into the validations table.

    The file is read in chunks, so a full quarter costs a slice of memory at a
    time.  Values are kept as published: dates stay DD/MM/YYYY and the boarding
    band keeps its range, e.g. "10-19".  Sum BAND_BOARDINGS_FLOOR for counts,
    the same column the route selection uses.

    Args:
        conn: Open connection to the database.

    Returns:
        Tuple of (path, rows) for the quarter that was loaded.
    """
    path = validations.download_latest_validations()

    rows = 0
    chunks = pd.read_csv(path, dtype=str, encoding="utf-8-sig",
                         chunksize=VALIDATIONS_CHUNK_ROWS)
    for chunk in chunks:
        if rows:
            written = store.insert_rows(conn, "validations", chunk)
        else:
            written = store.replace_table(conn, "validations", chunk)
        rows += written
        conn.commit()
        print("%-24s %8d rows" % (path.name, rows))

    store.set_meta(conn, "validations_quarter", path.stem)
    conn.commit()
    return path, rows


def main():
    """Loads both sources into the database and prints what was stored."""
    conn = store.connect()
    try:
        version = load_gtfs(conn)
        path, _ = load_validations(conn)
        # The live collector appends to this table, so it is only created, never
        # replaced: a setup re-run leaves the collected rows alone.
        store.ensure_table(conn, "gtfs_positions",
                           store.GTFS_POSITIONS_COLUMNS)
        store.create_indexes(conn)
        conn.commit()

        print()
        for table, count in store.row_counts(conn).items():
            print("%-24s %8d rows" % (table, count))
        print("%s: %.1f MB, timetable %s, validations %s" % (
            config.DB_PATH, config.DB_PATH.stat().st_size / 1e6,
            version, path.stem))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
