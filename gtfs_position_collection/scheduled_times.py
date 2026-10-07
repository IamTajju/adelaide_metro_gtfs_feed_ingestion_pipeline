# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         gtfs_position_collection/scheduled_times.py
# Date:         27-09-2026
# Description:  Loads scheduled GTFS arrivals for selected routes and stops
# Usage:        python -m gtfs_position_collection.scheduled_times
"""Builds scheduled_stop_times for the chosen trips and stops, maintained with the current timetable version."""


import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from shared import config
from shared import store
from shared import timetable



def find_latest_file(directory, pattern):
    """Finds the most recently modified matching CSV.

    Args:
        directory: Directory containing selection CSVs.
        pattern: Filename glob such as top_k_routes_*.csv.

    Returns:
        Absolute Path to the newest matching file.

    Raises:
        FileNotFoundError: If no matching file exists.
    """
    directory = Path(directory).resolve()

    files = list(directory.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No file matching {pattern!r} found in {directory}"
        )

    latest = max(files, key=lambda path: path.stat().st_mtime)

    return latest.resolve()


def _selected_rows(df):
    """Filters a selection DataFrame if it contains a 'selected' column.

    If no 'selected' column exists, every row is treated as selected.
    """
    if "selected" not in df.columns:
        return df

    selected = (
        df["selected"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"1", "true", "yes", "y"})
    )
    
    return df[selected]


def load_selected_routes(path):
    """Loads selected base-route codes from the top-k route CSV.

    Args:
        path: Path to top_k_routes_*.csv.

    Returns:
        Set of selected route codes.
    """
    path = Path(path)

    # If a relative path was supplied, interpret it relative to project root
    if not path.is_absolute():
        path = config.ROOT / path

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Selected routes CSV does not exist: {path}"
        )

    df = pd.read_csv(path, dtype=str)

    df = _selected_rows(df)

    if "route" not in df.columns:
        raise ValueError(
            f"{path} does not contain the required 'route' column"
        )

    routes = {
        route.strip()
        for route in df["route"].dropna()
        if route.strip()
    }

    if not routes:
        raise ValueError(
            f"No selected routes found in {path}"
        )

    return routes


def load_selected_stops(path):
    """Loads selected GTFS stop IDs from the top-m stop CSV.

    Args:
        path: Path to top_m_stops_*.csv.

    Returns:
        Set of selected GTFS stop IDs.
    """
    path = Path(path)

    # If a relative path was supplied, interpret it relative to project root
    if not path.is_absolute():
        path = config.ROOT / path

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Selected stops CSV does not exist: {path}"
        )

    df = pd.read_csv(path, dtype=str)

    df = _selected_rows(df)

    if "stop_id" in df.columns:
        column = "stop_id"
    elif "gtfs_stop_id" in df.columns:
        column = "gtfs_stop_id"
    else:
        raise ValueError(
            f"{path} must contain 'stop_id' or 'gtfs_stop_id'"
        )

    stops = {
        stop.strip()
        for stop in df[column].dropna()
        if stop.strip()
    }

    if not stops:
        raise ValueError(
            f"No selected stops found in {path}"
        )

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


def selection_fingerprint(route_path, stop_path):
    """Produces a fingerprint for the current route/stop selections.
    """
    digest = hashlib.sha256()

    for path in (Path(route_path), Path(stop_path)):
        digest.update(path.name.encode("utf-8"))

        with path.open("rb") as file:
            while True:
                block = file.read(64 * 1024)

                if not block:
                    break

                digest.update(block)

    return digest.hexdigest()


def replace_schedule(conn, schedule, version, fingerprint):
    """Atomically replaces scheduled_stop_times with a new schedule.

    If an insertion fails, SQLite rolls the entire transaction back, so
    the previous working schedule remains available.
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
        conn.execute("DELETE FROM scheduled_stop_times")

        conn.executemany(sql, rows)

        store.set_state(
            conn,
            "scheduled_stop_times_version",
            version,
        )

        store.set_state(
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

    checked_date = store.get_state(
        conn,
        "gtfs_version_checked_date",
    )

    cached_version = store.get_state(
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
        store.set_state(
            conn,
            "remote_gtfs_version",
            version,
        )

        store.set_state(
            conn,
            "gtfs_version_checked_date",
            today,
        )

    return version


def schedule_row_count(conn):
    """Returns the number of rows currently in scheduled_stop_times."""
    return conn.execute(
        "SELECT COUNT(*) FROM scheduled_stop_times"
    ).fetchone()[0]


def ensure_scheduled_stop_times(
    route_path=None,
    stop_path=None,
    force_version_check=False,
    force_reload=False,
):
    """Ensures scheduled_stop_times contains the current selected schedule.

    This is the main public function used by Stage 3.

    It:
      - resolves the latest Stage 1/Stage 2 selection files;
      - checks version.txt once per Adelaide day;
      - downloads static GTFS when necessary;
      - rebuilds the schedule when either GTFS or selections change.

    Args:
        route_path: Optional route selection CSV.
        stop_path: Optional stop selection CSV.
        force_version_check: Query version.txt even if already checked today.
        force_reload: Rebuild the table even if nothing appears to have changed.

    Returns:
        Dictionary describing the schedule state.
    """
    if route_path is None:
        route_path = find_latest_file(
            config.SELECTION_DIR,
            "top_k_routes_*",
        )

    if stop_path is None:
        stop_path = find_latest_file(
            config.SELECTION_DIR,
            "top_m_stops_*",
        )

    route_path = Path(route_path)
    stop_path = Path(stop_path)

    conn = store.connect()

    try:
        store.initialise_database(conn)

        # Daily remote timetable version check
        version = current_gtfs_version(
            conn,
            force_check=force_version_check,
        )

        # Ensures data/timetable belongs to this version
        timetable_path = timetable.download_timetable(version)

        fingerprint = selection_fingerprint(
            route_path,
            stop_path,
        )

        loaded_version = store.get_state(
            conn,
            "scheduled_stop_times_version",
        )

        loaded_fingerprint = store.get_state(
            conn,
            "scheduled_selection_fingerprint",
        )

        existing_rows = schedule_row_count(conn)

        reload_required = (
            force_reload
            or existing_rows == 0
            or loaded_version != version
            or loaded_fingerprint != fingerprint
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
                "route_file": str(route_path),
                "stop_file": str(stop_path),
            }

        selected_routes = load_selected_routes(route_path)
        selected_stops = load_selected_stops(stop_path)

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
            "route_file": str(route_path),
            "stop_file": str(stop_path),
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
        "--routes",
        type=Path,
        help=(
            "Route selection CSV. "
            "Defaults to latest top_k_routes_*.csv."
        ),
    )

    parser.add_argument(
        "--stops",
        type=Path,
        help=(
            "Stop selection CSV. "
            "Defaults to latest top_m_stops_*.csv."
        ),
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
        route_path=args.routes,
        stop_path=args.stops,
        force_version_check=args.force_version_check,
        force_reload=args.force_reload,
    )


if __name__ == "__main__":
    main()