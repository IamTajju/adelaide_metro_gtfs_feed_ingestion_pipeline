# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         gtfs_position_collection/main.py
# Date:         07-10-2026
# Description:  Polling loop: fetch vehicle positions, filter, store (T08).
# Usage:        python -m gtfs_position_collection [--once]
"""Polling loop: fetch vehicle positions, filter, store (T08).

Every LIVE_POLL_SECONDS, while the collection window is open (first to last
scheduled bus of the chosen routes at the chosen stops, see collection_window):
  1. fetch the live vehicle_positions feed;
  2. skip it if the feed header timestamp has not moved since the last poll;
  3. keep only chosen routes within STOP_RADIUS_M of a chosen stop (filters);
  4. store them in positions with their base route; a vehicle report already
     stored (same vehicle_id and timestamp) is ignored.
The chosen routes and stops are read once, at start, from the routes and stops
tables (`make selection` fills them). Each poll is logged to
data/logs/collector.log; an error is logged and the loop carries on, so one
network blip never ends a collection day. Stop it with Ctrl+C.

TODO: T07 rejection layer (validate.py) between steps 3 and 4.
"""

import argparse
import logging
import sqlite3
import time
from datetime import datetime

from data_collection_setup.main import POSITIONS_COLUMNS, create_database
from gtfs_position_collection import filters
from gtfs_position_collection.collection_window import ADELAIDE_TZ, CollectionWindow
from gtfs_position_collection.feed import fetch_vehicle_positions
from shared import config

logger = logging.getLogger("collector")


def set_up_logging():
    """Logs to data/logs/collector.log and the terminal."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(config.LOG_DIR / "collector.log"),
                    logging.StreamHandler()):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def load_chosen_route_ids_and_stops(conn):
    """Reads the selection from the database.

    Returns:
        Tuple (base_routes, variant_route_ids, stops): base route codes for the
        filter, every GTFS route_id variant for the timetable window, and
        (stop_id, stop_lat, stop_lon) tuples.

    Raises:
        RuntimeError: if the routes or stops table is empty.
    """
    base_routes, stops = filters.load_selection(conn)
    if not base_routes or not stops:
        raise RuntimeError("routes/stops tables in %s are empty; run `make selection` first"
                           % config.DB_PATH)
    variant_route_ids = {variant for (route_ids,) in conn.execute("SELECT gtfs_route_ids FROM routes")
                         for variant in route_ids.split()}
    return base_routes, variant_route_ids, stops


def store_positions(conn, rows):
    """Adds the base route to each row and inserts them, ignoring reports already stored.

    Args:
        conn: Open connection to the project database.
        rows: Filtered feed rows (see feed.convert_vehicle_entity_to_row).

    Returns:
        Number of new rows stored.
    """
    rows_before = conn.total_changes
    with conn:  # One transaction per poll: rolled back if the insert fails.
        conn.executemany(
            "INSERT OR IGNORE INTO positions (%s) VALUES (%s)" % (
                ", ".join(POSITIONS_COLUMNS), ", ".join("?" * len(POSITIONS_COLUMNS))),
            [[dict(row, route=filters.base_route(row["trip_route_id"]))[column]
              for column in POSITIONS_COLUMNS] for row in rows])
    return conn.total_changes - rows_before


def poll_once(conn, base_routes, stops, last_feed_timestamp):
    """Fetches, filters and stores one snapshot of the feed, then logs what happened.

    Args:
        conn: Open connection to the project database.
        base_routes: Set of chosen base route codes.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.
        last_feed_timestamp: Header timestamp of the previous poll, or None.

    Returns:
        The header timestamp of this poll.
    """
    feed_timestamp, rows = fetch_vehicle_positions()
    if feed_timestamp == last_feed_timestamp:
        logger.info("feed unchanged (header %d), skipped", feed_timestamp)
        return feed_timestamp
    relevant_rows = filters.keep_relevant(rows, base_routes, stops)
    stored = store_positions(conn, relevant_rows)
    logger.info("feed %d: %d vehicles, %d near chosen stops, %d new rows stored",
                feed_timestamp, len(rows), len(relevant_rows), stored)
    return feed_timestamp


def main():
    """Polls the live feed into the positions table while the collection window is open."""
    parser = argparse.ArgumentParser(
        description="Collect live positions of the chosen routes.")
    parser.add_argument("--once", action="store_true",
                        help="poll once and exit, ignoring the collection window (for testing)")
    args = parser.parse_args()
    set_up_logging()

    # Creates the tables if setup has not run; never deletes rows.
    create_database(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        base_routes, variant_route_ids, stops = load_chosen_route_ids_and_stops(
            conn)
        logger.info("collecting routes %s near %d stops into %s",
                    " ".join(sorted(base_routes)), len(stops), config.DB_PATH)
        if args.once:
            poll_once(conn, base_routes, stops, last_feed_timestamp=None)
            return

        window = CollectionWindow(
            variant_route_ids, {stop_id for stop_id, _, _ in stops})
        last_feed_timestamp, was_open = None, None
        while True:
            is_open = window.is_open()
            if is_open != was_open:
                today = datetime.now(ADELAIDE_TZ).date()
                logger.info("collection window %s; today %s", "open" if is_open else "closed",
                            window.describe(today))
                was_open = is_open
            if not is_open:
                time.sleep(config.OUTSIDE_WINDOW_CHECK_SECONDS)
                continue
            poll_started = time.monotonic()
            try:
                last_feed_timestamp = poll_once(
                    conn, base_routes, stops, last_feed_timestamp)
            except Exception:  # Never crash: log it and try again next poll.
                logger.exception("poll failed")
            time.sleep(max(0.0, config.LIVE_POLL_SECONDS -
                       (time.monotonic() - poll_started)))
    except KeyboardInterrupt:
        logger.info("stopped by user")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
