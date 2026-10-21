# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         gtfs_position_collection/main.py
# Date:         07-10-2026
# Description:  Polling loop: fetch vehicle positions, filter, store (T08).
# Usage:        python -m gtfs_position_collection [--once]
"""Polling loop: fetch vehicle positions, filter, store (T08).

Every LIVE_POLL_SECONDS, while one of the daily collection windows is open
(config.COLLECTION_WINDOWS, see collection_window):
  1. fetch the live vehicle_positions feed;
  2. skip it if the feed header timestamp has not moved since the last poll;
  3. keep only chosen routes within STOP_RADIUS_M of a chosen stop (filters);
  4. validate them; rejected rows go to quarantine with the reason (validate);
  5. store the rest in positions with their base route; a vehicle report already
     stored (same vehicle_id and timestamp) is ignored.
The chosen routes and stops are read once, at start, from the routes and stops
tables (`make selection` fills them). scheduled_stop_times is checked at start and
again on each new Adelaide day, so a new timetable version is picked up during a
multi-day collection (scheduled_times). Each poll is logged to
data/logs/collector.log; an error is logged and the loop carries on, so one
network blip never ends a collection day. Between windows it sleeps until the
next one opens, so one run collects every window of every day. When a window
closes, its hourly weather is stored (weather_collection). It asks the
operating system not to sleep while it runs (keep_awake). Stop it with Ctrl+C.
"""

import argparse
import logging
import time
from datetime import datetime

from data_collection_setup.main import POSITIONS_COLUMNS, connect_to_database, create_database
from gtfs_position_collection import filters, validate
from gtfs_position_collection.collection_window import ADELAIDE_TZ, CollectionWindow
from gtfs_position_collection.feed import fetch_vehicle_positions
from gtfs_position_collection.keep_awake import prevent_sleep
from gtfs_position_collection.scheduled_times import ensure_scheduled_stop_times
from shared import config
from weather_collection.main import store_window_weather

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


def load_chosen_routes_and_stops(conn):
    """Reads the selection from the database.

    Returns:
        Tuple (base_routes, stops): base route codes for the filter and
        (stop_id, stop_lat, stop_lon) tuples.

    Raises:
        RuntimeError: if the routes or stops table is empty.
    """
    base_routes, stops = filters.load_selection(conn)
    if not base_routes or not stops:
        raise RuntimeError("routes/stops tables in %s are empty; run `make selection` first"
                           % config.DB_PATH)
    return base_routes, stops


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
    """Fetches, filters, validates and stores one feed snapshot.

    Args:
        conn: Open connection to the project database.
        base_routes: Set of chosen base route codes.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.
        last_feed_timestamp: Header timestamp of the previous poll, or None.

    Returns:
        The header timestamp of this poll.
    """
    feed_timestamp, rows = fetch_vehicle_positions()

    # Do not process exactly the same feed snapshot twice.
    if feed_timestamp == last_feed_timestamp:
        logger.info(
            "feed unchanged (header %d), skipped",
            feed_timestamp,
        )
        return feed_timestamp

    # Only keeps rows that match selection.
    relevant_rows = filters.keep_relevant(rows, base_routes, stops)

    # Call the validation layer
    # Bad rows are written to quarantine; only good rows continue.
    valid_rows, quarantined = validate.validate_positions(relevant_rows, conn)

    # Existing duplicate vehicle/timestamp observations are ignored.
    stored = store_positions(conn, valid_rows)

    logger.info(
        (
            "feed %d: %d vehicles, "
            "%d near chosen stops, "
            "%d valid, "
            "%d quarantined, "
            "%d new rows stored"
        ),
        feed_timestamp,
        len(rows),
        len(relevant_rows),
        len(valid_rows),
        quarantined,
        stored,
    )

    return feed_timestamp

def refresh_scheduled_stop_times():
    """Makes sure scheduled_stop_times matches today's timetable version and logs it.

    The version check behind it contacts Adelaide Metro at most once per day.
    """
    schedule_info = ensure_scheduled_stop_times()
    logger.info(
        "static schedule ready: %d rows, GTFS version %s%s",
        schedule_info["rows"],
        schedule_info["gtfs_version"],
        " (reloaded)" if schedule_info["reloaded"] else "",
    )

def store_weather_for_window(conn, start, end):
    """Stores today's weather for one closed window; a failure is logged, never fatal.

    `make weather` can fill the window in later if this fails.
    """
    today = datetime.now(ADELAIDE_TZ).date()
    try:
        stored = store_window_weather(conn, today, start, end)
        logger.info("weather for window %s-%s stored: %d hours", start, end, stored)
    except Exception:
        logger.exception("weather for window %s-%s failed; run `make weather DAY=%s` later",
                         start, end, today)


def main():
    """Polls live positions while a collection window is open."""
    parser = argparse.ArgumentParser(
        description="Collect live positions of the chosen routes."
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "poll once and exit, ignoring the collection windows "
            "(for testing)"
        ),
    )

    args = parser.parse_args()

    set_up_logging()

    # Create core database tables if setup has not already done so.
    create_database(config.DB_PATH)

    # Ensure the current static GTFS timetable and scheduled_stop_times
    # are ready before realtime validation begins. A failure (e.g. a network
    # blip right after a reboot) is retried in the loop instead of ending the run.
    try:
        refresh_scheduled_stop_times()
        schedule_checked_on = datetime.now(ADELAIDE_TZ).date()
    except Exception:
        if args.once:
            raise
        logger.exception("schedule refresh failed at start; retrying next poll")
        schedule_checked_on = None

    conn = connect_to_database(config.DB_PATH)

    try:
        base_routes, stops = load_chosen_routes_and_stops(conn)

        logger.info(
            "collecting routes %s near %d stops into %s",
            " ".join(sorted(base_routes)),
            len(stops),
            config.DB_PATH,
        )

        if args.once:
            poll_once(
                conn,
                base_routes,
                stops,
                last_feed_timestamp=None,
            )
            return

        sleep_blocker = prevent_sleep()
        if sleep_blocker:
            logger.info("system sleep blocked while collecting (%s)", sleep_blocker)
        else:
            logger.warning("could not block system sleep; turn idle sleep off in the power settings")

        window = CollectionWindow()

        last_feed_timestamp = None
        was_open = None
        current_window = None

        while True:
            # A new Adelaide day: re-check the timetable version (T06 daily reload).
            today = datetime.now(ADELAIDE_TZ).date()
            if today != schedule_checked_on:
                try:
                    refresh_scheduled_stop_times()
                    schedule_checked_on = today
                except Exception:  # Keep collecting with the current schedule.
                    logger.exception("daily schedule refresh failed; retrying next poll")

            open_window = window.open_window()
            is_open = open_window is not None

            # A window just closed: store its hourly weather.
            if current_window and open_window != current_window:
                store_weather_for_window(conn, *current_window)
            current_window = open_window

            if is_open != was_open:
                logger.info(
                    "collection window %s; daily windows %s",
                    "open" if is_open else "closed",
                    window.describe(),
                )

                was_open = is_open

            if not is_open:
                # Sleep until the next window opens, checking at least every
                # OUTSIDE_WINDOW_CHECK_SECONDS.
                time.sleep(min(window.seconds_until_open(),
                               config.OUTSIDE_WINDOW_CHECK_SECONDS))
                continue

            poll_started = time.monotonic()

            try:
                last_feed_timestamp = poll_once(
                    conn,
                    base_routes,
                    stops,
                    last_feed_timestamp,
                )

            except Exception:
                # One bad HTTP request/database operation should not end
                # an entire day's collection.
                logger.exception("poll failed")

            elapsed = time.monotonic() - poll_started

            time.sleep(max(0.0, config.LIVE_POLL_SECONDS - elapsed))

    except KeyboardInterrupt:
        logger.info("stopped by user")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
