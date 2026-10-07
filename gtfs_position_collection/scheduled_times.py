# Student Name: Joel Bates
# Student FAN:  BATE0218
# File:         gtfs_position_collection/scheduled_times.py
# Date:         27-09-2026
# Description:  Loads scheduled GTFS arrivals for selected routes and stops
# Usage:        python -m gtfs_position_collection.scheduled_times
"""Builds scheduled_stop_times for the chosen trips and stops, maintained with the current timetable version.

The chosen routes and stops are read from the routes and stops tables, the same
source the collector uses, so the schedule always matches what is being collected.
"""


import argparse
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from data_collection_setup.main import connect_to_database, get_state, set_state
from shared import config
from shared import timetable


def load_selected_routes(conn):
    """Loads the chosen base-route codes from the routes table.

    The collector and filters read the same table, so the schedule always
    matches the selection being collected.

    Args:
        conn: Open connection to the project database.

    Returns:
        Set of base route codes, e.g. {"G10", "M44"}.

    Raises:
        RuntimeError: if the routes table is empty.
    """
    routes = {row["route"] for row in conn.execute("SELECT route FROM routes")}
    if not routes:
        raise RuntimeError("routes table is empty; run `make selection` first")
    return routes


def load_selected_stops(conn):
    """Loads the chosen GTFS stop_ids from the stops table.

    Args:
        conn: Open connection to the project database.

    Returns:
        Set of stop_id strings (a stop chosen by two routes appears once).

    Raises:
        RuntimeError: if the stops table is empty.
    """
    stops = {row["stop_id"] for row in conn.execute("SELECT DISTINCT stop_id FROM stops")}
    if not stops:
        raise RuntimeError("stops table is empty; run `make selection` first")
    return stops


def gtfs_time_to_seconds(value):
    """Converts a GTFS HH:MM:SS value to seconds from service-day midnight.

    Unlike datetime.time, GTFS permits hours greater than 23. For example,
    25:10:00 represents 01:10 on the following calendar day but belongs
    to the previous GTFS service day.

    Args:
        value: GTFS time string.

    Returns:
        Integer seconds from service-day midnight, or None.
    """
    if value is None or pd.isna(value):
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        hours, minutes, seconds = map(int, value.split(":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid GTFS time: {value!r}") from exc

    if hours < 0 or not 0 <= minutes <= 59 or not 0 <= seconds <= 59:
        raise ValueError(f"Invalid GTFS time: {value!r}")

    return hours * 3600 + minutes * 60 + seconds


def build_scheduled_stop_times(
    timetable_path,
    selected_routes,
    selected_stops,
    version,
):
    """Builds scheduled arrivals for selected routes and stops.

    All trips belonging to the selected base routes are found first.
    stop_times.txt is then restricted to those trips and the selected
    Stage 2 stops.

    Args:
        timetable_path: Extracted static GTFS directory.
        selected_routes: Set of base route codes.
        selected_stops: Set of selected GTFS stop IDs.
        version: Current static GTFS version.

    Returns:
        DataFrame ready for scheduled_stop_times.
    """
    # Resolves selected base routes to the GTFS route_ids
    routes = timetable.read_gtfs(
        timetable_path,
        "routes.txt",
        columns=[
            "route_id",
            "route_short_name",
            "route_type",
        ],
    )

    routes = routes[
        routes["route_type"] == config.BUS_ROUTE_TYPE
    ].copy()

    routes["route"] = timetable.strip_route_variants(
        routes["route_short_name"]
    )

    routes = routes[
        routes["route"].isin(selected_routes)
    ].copy()

    if routes.empty:
        raise RuntimeError(
            "None of the selected routes exist in the current GTFS feed"
        )

    found_routes = set(routes["route"].dropna())
    missing_routes = sorted(selected_routes - found_routes)

    if missing_routes:
        print(
            "Warning: selected routes missing from current GTFS:",
            ", ".join(missing_routes),
        )

    # Find every trip operating on those routes.
    trips = timetable.read_gtfs(
        timetable_path,
        "trips.txt",
        columns=[
            "route_id",
            "service_id",
            "trip_id",
            "direction_id",
            "shape_id",
        ],
    )

    trips = trips.merge(
        routes[
            [
                "route_id",
                "route_short_name",
                "route",
            ]
        ],
        how="inner",
        on="route_id",
    )

    if trips.empty:
        raise RuntimeError(
            "Selected routes produced no trips in trips.txt"
        )

    selected_trip_ids = set(trips["trip_id"])

    # Loads stop_times and keeps selected trips x selected stops.

    stop_times = timetable.read_gtfs(
        timetable_path,
        "stop_times.txt",
        columns=[
            "trip_id",
            "arrival_time",
            "departure_time",
            "stop_id",
            "stop_sequence",
            "pickup_type",
            "drop_off_type",
            "timepoint",
        ],
    )

    stop_times = stop_times[
        stop_times["trip_id"].isin(selected_trip_ids)
        & stop_times["stop_id"].isin(selected_stops)
    ].copy()

    if stop_times.empty:
        raise RuntimeError(
            "No scheduled stop times matched the selected trips and stops. "
            "Check that Stage 2 stop IDs are GTFS stop_id values."
        )

    # Attach route/trip metadata.
    schedule = stop_times.merge(
        trips[
            [
                "trip_id",
                "service_id",
                "route_id",
                "route_short_name",
                "route",
                "direction_id",
                "shape_id",
            ]
        ],
        how="inner",
        on="trip_id",
    )

    # GTFS requires stop_sequence to be numeric.
    schedule["stop_sequence"] = pd.to_numeric(
        schedule["stop_sequence"],
        errors="raise",
    ).astype(int)

    # Normalise scheduled times.
    schedule["scheduled_arrival"] = schedule["arrival_time"]
    schedule["scheduled_departure"] = schedule["departure_time"]

    missing_arrival = (
        schedule["scheduled_arrival"].isna()
        | schedule["scheduled_arrival"].eq("")
    )

    schedule.loc[
        missing_arrival,
        "scheduled_arrival",
    ] = schedule.loc[
        missing_arrival,
        "scheduled_departure",
    ]

    schedule["arrival_seconds"] = schedule[
        "scheduled_arrival"
    ].apply(gtfs_time_to_seconds)

    schedule["departure_seconds"] = schedule[
        "scheduled_departure"
    ].apply(gtfs_time_to_seconds)

    # Without either an arrival or departure timestamp the row cannot later be used to calculate delay.
    missing_schedule_time = schedule["arrival_seconds"].isna()

    if missing_schedule_time.any():
        count = int(missing_schedule_time.sum())

        print(
            f"Warning: dropping {count} stop-time rows with no usable "
            "scheduled arrival/departure time"
        )

        schedule = schedule[~missing_schedule_time].copy()

    schedule["gtfs_version"] = str(version)

    # Final database column order.
    columns = [
        "gtfs_version",
        "route",
        "route_id",
        "route_short_name",
        "service_id",
        "trip_id",
        "direction_id",
        "shape_id",
        "stop_id",
        "stop_sequence",
        "scheduled_arrival",
        "scheduled_departure",
        "arrival_seconds",
        "departure_seconds",
        "pickup_type",
        "drop_off_type",
        "timepoint",
    ]

    schedule = schedule[columns]

    # Duplicate trip/sequence values should never occur in valid GTFS.
    duplicates = schedule.duplicated(
        subset=["trip_id", "stop_sequence"],
        keep=False,
    )

    if duplicates.any():
        raise RuntimeError(
            "GTFS produced duplicate (trip_id, stop_sequence) rows"
        )

    return schedule.reset_index(drop=True)


def selection_fingerprint(selected_routes, selected_stops):
    """Fingerprints the current selection, so a changed selection forces a rebuild.

    Args:
        selected_routes: Set of base route codes.
        selected_stops: Set of stop_ids.

    Returns:
        Hex SHA-256 of the sorted routes and stops.
    """
    digest = hashlib.sha256()
    digest.update(",".join(sorted(selected_routes)).encode("utf-8"))
    digest.update(b"|")
    digest.update(",".join(sorted(selected_stops)).encode("utf-8"))
    return digest.hexdigest()


def replace_schedule(conn, schedule, version, fingerprint, keep_other_versions):
    """Atomically loads a schedule into scheduled_stop_times.

    If an insertion fails, SQLite rolls the entire transaction back, so
    the previous working schedule remains available.

    Args:
        conn: Open connection to the project database.
        schedule: DataFrame from build_scheduled_stop_times.
        version: GTFS version of the schedule.
        fingerprint: selection_fingerprint of the chosen routes and stops.
        keep_other_versions: True when only the timetable version changed:
            rows of earlier versions stay, so arrivals already collected
            under them can still be matched. False when the selection
            changed: every row is replaced, since old trips x stops no
            longer apply.
    """
    sql = """
        INSERT INTO scheduled_stop_times (
            gtfs_version,
            route,
            route_id,
            route_short_name,
            service_id,
            trip_id,
            direction_id,
            shape_id,
            stop_id,
            stop_sequence,
            scheduled_arrival,
            scheduled_departure,
            arrival_seconds,
            departure_seconds,
            pickup_type,
            drop_off_type,
            timepoint
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # Convert NaN values from pandas into SQLite NULL.
    clean = schedule.astype(object).where(
        pd.notna(schedule),
        None,
    )

    rows = list(clean.itertuples(index=False, name=None))

    with conn:
        if keep_other_versions:
            conn.execute("DELETE FROM scheduled_stop_times WHERE gtfs_version = ?", (str(version),))
        else:
            conn.execute("DELETE FROM scheduled_stop_times")

        conn.executemany(sql, rows)

        set_state(
            conn,
            "scheduled_stop_times_version",
            version,
        )

        set_state(
            conn,
            "scheduled_selection_fingerprint",
            fingerprint,
        )


def current_adelaide_date():
    """Returns today's date according to Adelaide local time."""
    return datetime.now(
        ZoneInfo(config.LOCAL_TIMEZONE)
    ).date().isoformat()


def current_gtfs_version(conn, force_check=False):
    """Gets the current GTFS version, contacting Adelaide Metro once per day.

    Args:
        conn: SQLite connection.
        force_check: Ignore the daily cache and query version.txt now.

    Returns:
        Current GTFS timetable version.
    """
    today = current_adelaide_date()

    checked_date = get_state(
        conn,
        "gtfs_version_checked_date",
    )

    cached_version = get_state(
        conn,
        "remote_gtfs_version",
    )

    if (
        not force_check
        and checked_date == today
        and cached_version
    ):
        return cached_version

    # Network call.
    version = timetable.get_timetable_version()

    with conn:
        set_state(
            conn,
            "remote_gtfs_version",
            version,
        )

        set_state(
            conn,
            "gtfs_version_checked_date",
            today,
        )

    return version


def schedule_row_count(conn, version):
    """Returns the number of scheduled_stop_times rows of one GTFS version."""
    return conn.execute(
        "SELECT COUNT(*) FROM scheduled_stop_times WHERE gtfs_version = ?",
        (str(version),),
    ).fetchone()[0]


def ensure_scheduled_stop_times(
    force_version_check=False,
    force_reload=False,
):
    """Ensures scheduled_stop_times contains the current selected schedule.

    This is the main public function used by Stage 3.

    It:
      - reads the chosen routes and stops from the routes and stops tables;
      - checks version.txt once per Adelaide day;
      - downloads static GTFS when necessary;
      - rebuilds the schedule when either GTFS or selections change.

    Args:
        force_version_check: Query version.txt even if already checked today.
        force_reload: Rebuild the table even if nothing appears to have changed.

    Returns:
        Dictionary describing the schedule state.
    """
    conn = connect_to_database()

    try:

        # Daily remote timetable version check
        version = current_gtfs_version(
            conn,
            force_check=force_version_check,
        )

        # Ensures data/timetable belongs to this version
        timetable_path = timetable.download_timetable(version)

        selected_routes = load_selected_routes(conn)
        selected_stops = load_selected_stops(conn)
        fingerprint = selection_fingerprint(selected_routes, selected_stops)

        loaded_version = get_state(
            conn,
            "scheduled_stop_times_version",
        )

        loaded_fingerprint = get_state(
            conn,
            "scheduled_selection_fingerprint",
        )

        existing_rows = schedule_row_count(conn, version)
        selection_changed = loaded_fingerprint != fingerprint

        reload_required = (
            force_reload
            or existing_rows == 0
            or loaded_version != version
            or selection_changed
        )

        if not reload_required:
            print(
                "scheduled_stop_times is current "
                f"(GTFS version {version}, {existing_rows:,} rows)"
            )

            return {
                "gtfs_version": version,
                "rows": existing_rows,
                "reloaded": False,
            }

        print(
            f"Building schedule for {len(selected_routes)} routes "
            f"and {len(selected_stops)} selected stops..."
        )

        schedule = build_scheduled_stop_times(
            timetable_path=timetable_path,
            selected_routes=selected_routes,
            selected_stops=selected_stops,
            version=version,
        )

        replace_schedule(
            conn,
            schedule,
            version,
            fingerprint,
            keep_other_versions=not selection_changed,
        )

        print(
            f"Loaded {len(schedule):,} scheduled stop times "
            f"for GTFS version {version}."
        )

        print(
            f"Trips:  {schedule['trip_id'].nunique():,}"
        )

        print(
            f"Stops:  {schedule['stop_id'].nunique():,}"
        )

        print(
            f"Routes: {schedule['route'].nunique():,}"
        )

        return {
            "gtfs_version": version,
            "rows": len(schedule),
            "trips": schedule["trip_id"].nunique(),
            "stops": schedule["stop_id"].nunique(),
            "routes": schedule["route"].nunique(),
            "reloaded": True,
        }

    finally:
        conn.close()


def main():
    """Command-line entry point for T06."""
    parser = argparse.ArgumentParser(
        description=(
            "Load selected Adelaide Metro GTFS scheduled stop times."
        )
    )

    parser.add_argument(
        "--force-version-check",
        action="store_true",
        help="Check Adelaide Metro version.txt even if checked today.",
    )

    parser.add_argument(
        "--force-reload",
        action="store_true",
        help="Rebuild scheduled_stop_times even if unchanged.",
    )

    args = parser.parse_args()

    ensure_scheduled_stop_times(
        force_version_check=args.force_version_check,
        force_reload=args.force_reload,
    )


if __name__ == "__main__":
    main()