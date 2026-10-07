# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         gtfs_position_collection/arrivals.py
# Date:         29-09-2026
# Description:  Observed arrival vs scheduled time per trip and stop.
# Usage:        python -m gtfs_position_collection.arrivals
"""Observed arrival vs scheduled time per trip and stop.

For every chosen stop, trip and service date the stored ping closest to the
stop (within STOP_RADIUS_M) is taken as the observed arrival, and it is
written to the arrivals table next to its scheduled time from the
scheduled_stop_times table (filled by scheduled_times). When two pings are equally close the earlier one wins, because
the bus was already there. What counts as "delayed" is a question for
Artefact 2, so this stage only keeps the two times side by side.

Reruns are safe: the closest ping of a trip, stop and date replaces the row
that is already there, so the table never holds duplicates.
"""

import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from data_collection_setup.main import ARRIVALS_DDL, create_database
from gtfs_position_collection import filters
from shared import config

LOCAL_TZ = ZoneInfo("Australia/Adelaide")


def load_pings(conn, route_ids):
    """Reads the stored pings of the chosen routes.

    Args:
        conn: Open connection to the project database.
        route_ids: Set of chosen route ids.

    Returns:
        DataFrame with trip_id, route_id, service_date, lat, lon and
        timestamp columns, service dates normalised to YYYY-MM-DD.
    """
    frame = pd.read_sql_query(
        "SELECT trip_trip_id AS trip_id, trip_route_id, "
        "trip_start_date AS service_date, position_latitude AS lat, "
        "position_longitude AS lon, timestamp "
        "FROM positions", conn)
    frame = frame.dropna(subset=["trip_id", "lat", "lon", "timestamp"])
    # The feed reports variants such as "G10A", the selection holds "G10".
    frame["route_id"] = [filters.base_route(code)
                         for code in frame["trip_route_id"]]
    frame = frame[frame["route_id"].isin(route_ids)].copy()
    frame = frame.drop(columns=["trip_route_id"])
    frame["service_date"] = frame["service_date"].astype(str).str.replace(
        r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", regex=True)
    return frame


def closest_arrivals(pings, stops, radius_m=filters.STOP_RADIUS_M):
    """Picks the closest ping per trip, stop and service date.

    Args:
        pings: DataFrame as load_pings returns it.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.
        radius_m: Radius around a stop that counts as an arrival.

    Returns:
        DataFrame with one row per (trip_id, stop_id, service_date), its
        observed ping timestamp and the distance to the stop in metres.
    """
    columns = ["trip_id", "route_id", "service_date", "stop_id",
               "timestamp", "distance_m"]
    pieces = []
    for stop_id, stop_lat, stop_lon in stops:
        near = pings.copy()
        near["distance_m"] = [
            filters.haversine(lat, lon, stop_lat, stop_lon)
            for lat, lon in zip(near["lat"], near["lon"])]
        near = near[near["distance_m"] <= radius_m]
        if near.empty:
            continue
        near["stop_id"] = stop_id
        pieces.append(near[columns])
    if not pieces:
        return pd.DataFrame(columns=columns)
    stacked = pd.concat(pieces, ignore_index=True)
    return stacked.sort_values(["distance_m", "timestamp"]).drop_duplicates(
        subset=["trip_id", "stop_id", "service_date"], keep="first")


def scheduled_arrival(service_date, arrival_time):
    """Builds the scheduled arrival text of one stop time.

    GTFS times count from the start of the service day and can pass
    midnight, so "24:15:00" on 2026-09-28 is 00:15:00 on the 29th.

    Args:
        service_date: "YYYY-MM-DD" service day of the trip.
        arrival_time: GTFS "HH:MM:SS" text from the timetable.

    Returns:
        "YYYY-MM-DD HH:MM:SS" local text, or None when a part is missing.
    """
    if not service_date or arrival_time is None or pd.isna(arrival_time):
        return None
    hours, minutes, seconds = (int(part) for part in arrival_time.split(":"))
    day = date.fromisoformat(service_date) + timedelta(days=hours // 24)
    return "%s %02d:%02d:%02d" % (day, hours % 24, minutes, seconds)


def load_stop_times(conn, stops):
    """Reads the scheduled times of the chosen stops from scheduled_stop_times.

    The table keeps every timetable version loaded during the collection, so
    trips collected before a timetable change still find their scheduled time.
    If a trip and stop appear in several versions, the newest version wins. A
    trip that loops through the same stop twice keeps its first visit.

    Args:
        conn: Open connection to the project database.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.

    Returns:
        DataFrame with trip_id, stop_id and arrival_time columns.

    Raises:
        RuntimeError: if scheduled_stop_times holds nothing for the chosen stops.
    """
    frame = pd.read_sql_query(
        "SELECT gtfs_version, trip_id, stop_id, stop_sequence, "
        "scheduled_arrival AS arrival_time FROM scheduled_stop_times", conn)
    chosen = {stop_id for stop_id, _, _ in stops}
    frame = frame[frame["stop_id"].isin(chosen)]
    if frame.empty:
        raise RuntimeError(
            "scheduled_stop_times has no rows for the chosen stops; run `make schedule` "
            "(or start `make collect`, which builds it) first")
    # Versions are numbers ("1705"); compare them as numbers, newest first.
    frame = frame.assign(version_number=pd.to_numeric(frame["gtfs_version"], errors="coerce"))
    frame = frame.sort_values(["version_number", "stop_sequence"], ascending=[False, True])
    return frame.drop_duplicates(subset=["trip_id", "stop_id"], keep="first")[
        ["trip_id", "stop_id", "arrival_time"]]


def add_times(observed, stop_times):
    """Adds the observed and scheduled arrival texts to the picked pings.

    The merge is inner on purpose: a bus can pass within the radius of a
    chosen stop that its trip never serves, e.g. another route's stop one
    street over, and such a pairing is not an arrival. Keeping only the
    trip and stop pairs the timetable knows drops that noise.

    Args:
        observed: DataFrame as closest_arrivals returns it.
        stop_times: DataFrame as load_stop_times returns it.

    Returns:
        DataFrame ready for the arrivals table.
    """
    merged = observed.merge(stop_times, on=["trip_id", "stop_id"], how="inner")
    merged["observed_arrival"] = [
        datetime.fromtimestamp(int(stamp), LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        for stamp in merged["timestamp"]]
    merged["scheduled_arrival"] = [
        scheduled_arrival(day, at) for day, at in
        zip(merged["service_date"], merged["arrival_time"])]
    merged["distance_m"] = merged["distance_m"].round(1)
    return merged


def store_arrivals(conn, arrivals):
    """Writes the arrivals, replacing rows of the same trip, stop and date.

    Args:
        conn: Open connection to the project database.
        arrivals: DataFrame as add_times returns it.

    Returns:
        Number of rows written.
    """
    conn.execute(ARRIVALS_DDL)
    rows = arrivals[["trip_id", "stop_id", "service_date", "route_id",
                     "observed_arrival", "scheduled_arrival", "distance_m"]]
    conn.executemany(
        "INSERT OR REPLACE INTO arrivals VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows.itertuples(index=False, name=None))
    conn.commit()
    return len(rows)


def fill_arrivals(conn, route_ids=None, stops=None, stop_times=None):
    """Fills the arrivals table from the pings stored so far.

    Args:
        conn: Open connection to the project database.
        route_ids: Optional set of chosen base route codes, read from the
            routes table when not given.
        stops: Optional list of (stop_id, stop_lat, stop_lon) tuples, read
            from the stops table when not given.
        stop_times: Optional DataFrame of scheduled times, read from the
            scheduled_stop_times table when not given.

    Returns:
        Number of arrivals written.
    """
    if route_ids is None or stops is None:
        route_ids, stops = filters.load_selection(conn)
    pings = load_pings(conn, route_ids)
    observed = closest_arrivals(pings, stops)
    if observed.empty:
        return 0
    if stop_times is None:
        stop_times = load_stop_times(conn, stops)
    arrivals = add_times(observed, stop_times)
    return store_arrivals(conn, arrivals)


def main():
    """Fills the arrivals table and prints what was stored."""
    create_database(config.DB_PATH)  # Adds any table an older database is missing.
    conn = sqlite3.connect(config.DB_PATH)
    try:
        written = fill_arrivals(conn)
        total = conn.execute("SELECT COUNT(*) FROM arrivals").fetchone()[0]
        print("%d observed arrivals written, %d rows in the table"
              % (written, total))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
