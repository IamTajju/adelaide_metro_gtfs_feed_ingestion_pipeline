# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         gtfs_position_collection/check.py
# Date:         21-10-2026
# Description:  Morning check: what the collector stored in each window of one day.
# Usage:        python -m gtfs_position_collection.check [YYYY-MM-DD]
"""Morning check: what the collector stored in each window of one day.

For each window in config.COLLECTION_WINDOWS it prints the positions stored,
the distinct vehicles and trips among them, and the rows quarantined. A
window with no stored positions means the collector was not running (or the
computer slept), so the command then exits with status 1. The day is
yesterday by default.
"""

import sqlite3
import sys
from datetime import datetime, timedelta

from gtfs_position_collection.collection_window import ADELAIDE_TZ
from shared import config


def window_bounds(day, start, end):
    """Returns the POSIX seconds of one "HH:MM" window on one Adelaide day."""
    return tuple(int(datetime.combine(day, datetime.strptime(clock, "%H:%M").time(),
                                      ADELAIDE_TZ).timestamp())
                 for clock in (start, end))


def summarise_day(conn, day, windows=config.COLLECTION_WINDOWS):
    """Counts what was stored in each collection window of one day.

    Args:
        conn: Open connection to the project database.
        day: datetime.date of the collection day (Adelaide).
        windows: List of ("HH:MM", "HH:MM") windows.

    Returns:
        List of dicts: window, positions, vehicles, trips, quarantined.
    """
    summary = []
    for start, end in windows:
        first, last = window_bounds(day, start, end)
        positions, vehicles, trips = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT vehicle_id), COUNT(DISTINCT trip_trip_id) "
            "FROM positions WHERE timestamp >= ? AND timestamp < ?", (first, last)).fetchone()
        quarantined = conn.execute(
            "SELECT COUNT(*) FROM quarantine WHERE quarantined_at >= ? AND quarantined_at < ?",
            (first, last)).fetchone()[0]
        summary.append({"window": "%s-%s" % (start, end), "positions": positions,
                        "vehicles": vehicles, "trips": trips, "quarantined": quarantined})
    return summary


def main():
    """Prints one day's per-window counts; exits with status 1 if a window is empty."""
    if len(sys.argv) > 1:
        day = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        day = datetime.now(ADELAIDE_TZ).date() - timedelta(days=1)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        summary = summarise_day(conn, day)
    finally:
        conn.close()
    print("%s  %-11s %9s %8s %6s %11s" % (day, "window", "positions", "vehicles", "trips", "quarantined"))
    for row in summary:
        print("            %-11s %9d %8d %6d %11d%s" % (
            row["window"], row["positions"], row["vehicles"], row["trips"], row["quarantined"],
            "   <- NO DATA" if row["positions"] == 0 else ""))
    if any(row["positions"] == 0 for row in summary):
        sys.exit(1)


if __name__ == "__main__":
    main()
