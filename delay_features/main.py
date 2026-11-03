# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         delay_features/main.py
# Date:         03-11-2026
# Description:  Builds the ML training table from the A1 database.
# Usage:        python -m delay_features
"""Builds the ML training table from the A1 database.

One row per observed arrival (trip, stop and service date) from the
arrivals table, with the delay class as the target and eight inputs:
route, stop, quadrant, window, day type, scheduled headway, the same trip's
delay at its previous chosen stop, and precipitation in the scheduled hour.
The scheduled, observed and previous-stop times are kept for evaluation
(bus pairs and replays); they are not model inputs.

A live query can build the same row once the bus has passed its previous
chosen stop: window and precipitation use the scheduled time, not the
observed one. Categories are stored as text; encoding them is left to the
training step, so it is fitted on the training split only.

Rows are dropped in a fixed order and each drop is counted once: no
scheduled time, closest ping further than MAX_ARRIVAL_PING_M (observed time
too uncertain for the class bands), scheduled within EDGE_MARGIN_MINUTES of
a collection window's edge (a late or early bus there may fall outside the
window and never be seen), then missing headway, quadrant or weather. The
table is rebuilt from scratch on every run. docs/A2_FEATURE_DECISIONS.md
explains each choice.
"""

import sqlite3
from datetime import date, datetime

import pandas as pd

from shared import config

FEATURES_DDL = """
CREATE TABLE IF NOT EXISTS delay_features (
    trip_id             TEXT NOT NULL,
    stop_id             TEXT NOT NULL,
    service_date        TEXT NOT NULL,
    route               TEXT,
    quadrant            TEXT,
    window              TEXT,
    day_type            TEXT,
    headway_min         REAL,
    prev_stop_delay_min REAL,
    has_prev_stop       INTEGER,
    precipitation_mm    REAL,
    delay_min           REAL,
    delay_class         TEXT,
    scheduled_arrival   TEXT,
    observed_arrival    TEXT,
    prev_stop_observed  TEXT,
    PRIMARY KEY (trip_id, stop_id, service_date)
)
"""

FEATURE_COLUMNS = ["trip_id", "stop_id", "service_date", "route", "quadrant",
                   "window", "day_type", "headway_min", "prev_stop_delay_min",
                   "has_prev_stop", "precipitation_mm", "delay_min",
                   "delay_class", "scheduled_arrival", "observed_arrival",
                   "prev_stop_observed"]

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def delay_class(delay_min):
    """Labels a delay in minutes as early, on_time or late."""
    if delay_min < config.EARLY_MINUTES:
        return "early"
    if delay_min > config.LATE_MINUTES:
        return "late"
    return "on_time"


def day_type(service_date):
    """Names a "YYYY-MM-DD" service date weekday or weekend.

    With about two weeks of data each weekday occurs only twice, so the
    weekday itself would mostly identify the date.
    """
    return "weekend" if date.fromisoformat(service_date).weekday() >= 5 else "weekday"


def clock_minutes(clock_time):
    """Turns an "HH:MM" text into minutes after midnight."""
    hours, minutes = (int(part) for part in clock_time.split(":"))
    return hours * 60 + minutes


def window_of(scheduled_arrival, windows=config.COLLECTION_WINDOWS,
              names=config.WINDOW_NAMES, margin=config.EDGE_MARGIN_MINUTES):
    """Names the collection window a "YYYY-MM-DD HH:MM:SS" scheduled time is in.

    Only the inner part of a window counts: a bus scheduled near an edge is
    seen only if it ran on the side that stays inside the window, so its
    label would be biased.

    Returns:
        The window's name, or None when the time is within margin minutes
        of an edge or outside every window.
    """
    minute = clock_minutes(scheduled_arrival[11:16])
    for (start, end), name in zip(windows, names):
        if clock_minutes(start) + margin <= minute <= clock_minutes(end) - margin:
            return name
    return None


def keep_rows(frame, mask, reason, dropped):
    """Keeps the rows where mask is True and counts the others under reason."""
    dropped[reason] = int((~mask).sum())
    return frame[mask]


def load_arrivals(conn, dropped):
    """Reads the observed arrivals that have a scheduled time to compare with.

    Args:
        conn: Open connection to the project database.
        dropped: Dict the number of arrivals without a scheduled time is
            added to.

    Returns:
        DataFrame of the arrivals with a delay_min column.
    """
    frame = pd.read_sql_query(
        "SELECT trip_id, stop_id, service_date, route_id AS route, "
        "observed_arrival, scheduled_arrival, distance_m FROM arrivals", conn)
    # The observed time always comes from a ping; the scheduled time is blank
    # where the timetable leaves arrival_time empty (non-timing-point stops).
    timed = keep_rows(frame, frame["scheduled_arrival"].notna(),
                      "no scheduled time", dropped).copy()
    observed = pd.to_datetime(timed["observed_arrival"], format=TIME_FORMAT)
    scheduled = pd.to_datetime(timed["scheduled_arrival"], format=TIME_FORMAT)
    timed["delay_min"] = (observed - scheduled).dt.total_seconds() / 60
    return timed


def add_previous_stop_delay(arrivals):
    """Adds the same trip's delay at its previous chosen stop that day.

    The first chosen stop of a trip has no previous stop: its value is 0
    and has_prev_stop is 0, so the model can tell it apart from a real 0.
    Run it before the distance and edge filters, so a dropped stop is still
    the previous stop of the next one, as it would be in a live query.

    Args:
        arrivals: DataFrame with trip_id, service_date, scheduled_arrival
            and delay_min columns.

    prev_stop_observed is when the bus was seen there: a replay at an
    earlier moment must not use that delay yet.

    Returns:
        Copy with prev_stop_delay_min, has_prev_stop and prev_stop_observed
        columns.
    """
    frame = arrivals.sort_values(["trip_id", "service_date", "scheduled_arrival"])
    trip = frame.groupby(["trip_id", "service_date"])
    previous = trip["delay_min"].shift(1)
    frame["has_prev_stop"] = previous.notna().astype(int)
    frame["prev_stop_delay_min"] = previous.fillna(0.0)
    frame["prev_stop_observed"] = trip["observed_arrival"].shift(1)
    return frame


def load_schedule(conn):
    """Reads one scheduled time per timetable version, trip and stop.

    Every version is kept: add_headway picks one version per date.

    Args:
        conn: Open connection to the project database.

    Returns:
        DataFrame with version_number, route, direction_id, service_id,
        trip_id, stop_id and arrival_seconds columns.
    """
    frame = pd.read_sql_query(
        "SELECT gtfs_version, route, direction_id, service_id, trip_id, "
        "stop_id, stop_sequence, arrival_seconds FROM scheduled_stop_times", conn)
    frame = frame.assign(version_number=pd.to_numeric(frame["gtfs_version"], errors="coerce"))
    frame = frame.sort_values("stop_sequence")
    frame = frame.drop_duplicates(subset=["version_number", "trip_id", "stop_id"], keep="first")
    return frame[["version_number", "route", "direction_id", "service_id", "trip_id",
                  "stop_id", "arrival_seconds"]]


def version_of_day(arrivals, schedule):
    """Picks the timetable version that ran on each service date.

    Service ids are reused across versions while trip ids are renumbered,
    so mixing versions would put a superseded trip next to its replacement
    (a fake 1 min headway). The version holding the most of the day's
    observed trips wins, the newest on a tie. Observed trips missing from it
    get no headway and are counted as "no headway".

    Returns:
        DataFrame with service_date and version_number columns.
    """
    trips = arrivals[["service_date", "trip_id"]].drop_duplicates()
    counts = trips.merge(schedule[["version_number", "trip_id"]].drop_duplicates(),
                         on="trip_id")
    counts = counts.groupby(["service_date", "version_number"]).size().reset_index(name="n")
    counts = counts.sort_values(["n", "version_number"], ascending=False)
    return counts.drop_duplicates("service_date")[["service_date", "version_number"]]


def add_headway(arrivals, schedule):
    """Adds the scheduled gap to the previous bus of the route at the stop.

    Each date uses one timetable version (version_of_day). The services
    running on a date are the services of the trips observed that date, so
    no calendar of past timetable versions is needed. The first bus of the
    day has no previous bus and takes the gap to the next.

    Args:
        arrivals: DataFrame with trip_id, stop_id and service_date columns.
        schedule: DataFrame as load_schedule returns it.

    Returns:
        Copy of arrivals with a headway_min column (NaN when the route has
        a single bus at that stop that day).
    """
    versions = version_of_day(arrivals, schedule)
    services = arrivals[["service_date", "trip_id"]].merge(versions, on="service_date")
    services = services.merge(
        schedule[["version_number", "trip_id", "service_id"]].drop_duplicates(),
        on=["version_number", "trip_id"])
    services = services[["service_date", "version_number", "service_id"]].drop_duplicates()
    day = services.merge(schedule, on=["version_number", "service_id"])
    day = day.dropna(subset=["arrival_seconds"])
    day = day.sort_values("arrival_seconds")
    group = day.groupby(["service_date", "route", "direction_id", "stop_id"],
                        dropna=False)["arrival_seconds"]
    gap = group.diff().fillna(-group.diff(-1))
    day["headway_min"] = gap / 60
    return arrivals.merge(day[["service_date", "trip_id", "stop_id", "headway_min"]],
                          on=["service_date", "trip_id", "stop_id"], how="left")


def load_precipitation(conn):
    """Reads the hourly precipitation, keyed by "YYYY-MM-DDTHH:00".

    Raises:
        RuntimeError: if weather_hourly does not exist yet.
    """
    tables = {name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "weather_hourly" not in tables:
        raise RuntimeError("weather_hourly is missing; run `make weather DAY=...` "
                           "for each collection day first")
    return pd.read_sql_query(
        "SELECT hour_local, precipitation AS precipitation_mm FROM weather_hourly", conn)


def build_features(conn):
    """Builds the feature rows from the arrivals and their context tables.

    Args:
        conn: Open connection to the project database.

    Returns:
        Tuple (features DataFrame in FEATURE_COLUMNS order, dict of how many
        arrivals each step dropped).
    """
    dropped = {}
    frame = add_previous_stop_delay(load_arrivals(conn, dropped))
    # Before any filter, so services are inferred from every observed trip.
    frame = add_headway(frame, load_schedule(conn))
    frame = keep_rows(frame, frame["distance_m"] <= config.MAX_ARRIVAL_PING_M,
                      "closest ping too far", dropped)
    frame = frame.assign(window=frame["scheduled_arrival"].map(window_of))
    frame = keep_rows(frame, frame["window"].notna(),
                      "scheduled near a window edge", dropped)
    quadrants = pd.read_sql_query(
        "SELECT route, stop_id, quadrant FROM stops", conn)
    frame = frame.merge(quadrants, on=["route", "stop_id"], how="left")
    frame = frame.assign(hour_local=frame["scheduled_arrival"].str[:13].str.replace(" ", "T")
                         + ":00")
    frame = frame.merge(load_precipitation(conn), on="hour_local", how="left")
    frame = keep_rows(frame, frame["headway_min"].notna(), "no headway", dropped)
    frame = keep_rows(frame, frame["quadrant"].notna(), "no quadrant", dropped)
    frame = keep_rows(frame, frame["precipitation_mm"].notna(), "no weather", dropped)
    frame = frame.assign(
        day_type=[day_type(day) for day in frame["service_date"]],
        delay_class=frame["delay_min"].map(delay_class))
    frame = frame.assign(headway_min=frame["headway_min"].round(1),
                         delay_min=frame["delay_min"].round(2),
                         prev_stop_delay_min=frame["prev_stop_delay_min"].round(2))
    return frame[FEATURE_COLUMNS], dropped


def store_features(conn, features):
    """Replaces the delay_features table with the given rows.

    Returns:
        Number of rows written.
    """
    conn.execute(FEATURES_DDL)
    conn.execute("DELETE FROM delay_features")
    conn.executemany(
        "INSERT INTO delay_features VALUES (%s)" % ", ".join("?" * len(FEATURE_COLUMNS)),
        features.itertuples(index=False, name=None))
    conn.commit()
    return len(features)


def main():
    """Rebuilds delay_features and prints what went in and what was dropped."""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        distances = pd.read_sql_query("SELECT distance_m FROM arrivals", conn)["distance_m"]
        features, dropped = build_features(conn)
        written = store_features(conn, features)
    finally:
        conn.close()
    quantiles = distances.quantile([0.5, 0.75, 0.9, 0.95]).round(0)
    print("closest-ping distance (m), median / 75%% / 90%% / 95%%: %s "
          "(cutoff %d m)" % (" / ".join("%d" % q for q in quantiles),
                             config.MAX_ARRIVAL_PING_M))
    for reason, count in dropped.items():
        print("dropped, %s: %d" % (reason, count))
    print("%d feature rows written at %s" % (written, datetime.now().strftime(TIME_FORMAT)))
    print(features["delay_class"].value_counts().to_string())


if __name__ == "__main__":
    main()
