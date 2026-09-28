# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         gtfs_position_collection/main.py
# Date:         28-09-2026
# Description:  Collects live vehicle positions into the database table.
# Usage:        python -m gtfs_position_collection
"""Polls live vehicle positions and appends them to the database.

Runs until the terminal is closed.  Every LIVE_POLL_SECONDS the realtime
vehicle_positions feed is fetched via get_gtfs_positions.get_positions(), and
every returned row is appended to the gtfs_positions table, one row per bus in
the feed.  Each row keeps the feed's own timestamp, so no clock of ours is
needed.

The table is created empty by data_collection_setup, so a setup re-run leaves
the collected rows alone.  A failed poll is only logged: the loop never exits,
so a single network blip is not allowed to end a collection day.
"""

import time

import pandas as pd

from get_gtfs_positions import get_positions
from shared import config, store


def collect_once(conn):
    """Fetches one poll and appends its rows to the database.

    Args:
        conn: Open connection to the database.

    Returns:
        Number of rows stored for this poll.
    """
    rows = get_positions()
    if not rows:
        return 0
    frame = pd.DataFrame(rows)
    written = store.insert_rows(conn, "gtfs_positions", frame)
    conn.commit()
    return written


def main():
    """Collects a poll every LIVE_POLL_SECONDS until the terminal closes."""
    conn = store.connect()
    try:
        store.ensure_table(conn, "gtfs_positions",
                           store.GTFS_POSITIONS_COLUMNS)
        store.create_indexes(conn)
        conn.commit()
        print("collecting %s every %s s" % (config.LIVE_FEED_URL,
                                            config.LIVE_POLL_SECONDS))
        while True:
            started = time.time()
            try:
                written = collect_once(conn)
                print("%s s, %d rows" % (round(time.time() - started, 1),
                                         written))
            except Exception as error:
                print("poll failed: %s" % error)
            time.sleep(config.LIVE_POLL_SECONDS)
    finally:
        conn.close()


if __name__ == "__main__":
    main()