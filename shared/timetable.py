# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         shared/timetable.py
# Date:         27-09-2026
# Description:  Static GTFS timetable download, version management, and route loading.
# Usage:        from shared.timetable import load_bus_routes, cbd_stop_ids
"""Static GTFS timetable download, version management, and route loading.

Manages downloading and caching Adelaide Metro's static timetable.
Checks version.txt for changes and only re-downloads when needed.
"""

import io
import shutil
import urllib.request
import zipfile

import pandas as pd

from shared import config


def base_route(codes):
    """Strips variant suffixes from route codes, e.g. "300H" -> "300".

    Args:
        codes: pandas Series of route codes.

    Returns:
        Series of base codes (leading letters + digits), NaN if none.
    """
    return codes.str.extract(r"^([A-Z]*\d+)", expand=False)


def get_timetable_version():
    """Fetches the current GTFS static timetable version from Adelaide Metro.

    Returns:
        The version string (e.g. "1700").
    """
    with urllib.request.urlopen(config.GTFS_VERSION, timeout=60) as resp:
        return resp.read().decode().strip()


def download_timetable(version):
    """Downloads and extracts the GTFS static timetable if not already present.

    Checks if the timetable version on disk matches the current endpoint version.
    If not, downloads the zip and replaces data/timetable/ with it, so the folder
    only ever holds files from one version.

    Args:
        version: The timetable version string (e.g. "1700").

    Returns:
        Path to the extracted timetable directory.
    """
    timetable_path = config.TIMETABLE_DIR
    version_file = timetable_path / "version.txt"

    # Check if we already have this version.
    if version_file.exists():
        local_version = version_file.read_text().strip()
        if local_version == version:
            return timetable_path

    # Download fully first, so a failed download leaves the old version in place.
    print("downloading GTFS timetable version %s" % version)
    with urllib.request.urlopen(config.GTFS_STATIC, timeout=60) as resp:
        body = resp.read()

    # Clear the old version so no file from it lingers, then extract.
    shutil.rmtree(timetable_path, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        zf.extractall(timetable_path)

    # Record the version.
    version_file.write_text(version)
    return timetable_path


def load_bus_routes():
    """Loads the bus routes from the static timetable (routes.txt).

    Ensures the timetable is present and current; downloads if needed.
    Merges route variants into their base route code.

    Returns:
        DataFrame with columns: route_id, route_short_name, route (base code).
    """
    version = get_timetable_version()
    download_timetable(version)

    routes = pd.read_csv(config.TIMETABLE_DIR / "routes.txt", dtype=str)
    routes = routes[routes.route_type == config.BUS_ROUTE_TYPE]
    routes["route"] = base_route(routes.route_short_name)
    return routes


def cbd_stop_ids():
    """Returns the set of GTFS stop_ids inside the CBD box.

    Ensures the timetable is present and current; downloads if needed.
    """
    version = get_timetable_version()
    download_timetable(version)

    stops = pd.read_csv(config.TIMETABLE_DIR / "stops.txt",
                        dtype={"stop_id": str})
    in_cbd = (stops.stop_lat.between(config.CBD_SOUTH, config.CBD_NORTH)
              & stops.stop_lon.between(config.CBD_WEST, config.CBD_EAST))
    return set(stops.stop_id[in_cbd])


def read_gtfs(source, name):
    """Reads one GTFS file, all columns as strings.

    Args:
        source: Path to an extracted timetable folder or to a GTFS zip.
        name: File name inside it, e.g. "trips.txt".

    Returns:
        DataFrame of the file.
    """
    if source.suffix == ".zip":
        with zipfile.ZipFile(source) as zf, zf.open(name) as fh:
            return pd.read_csv(fh, dtype=str, encoding="utf-8-sig")
    return pd.read_csv(source / name, dtype=str, encoding="utf-8-sig")


def trips_on_date(source, day):
    """Counts bus trips per base route that run on one date.

    A service runs if calendar.txt covers the date and weekday, adjusted by
    the one-off additions (1) and removals (2) in calendar_dates.txt.

    Args:
        source: Timetable folder or zip (see read_gtfs).
        day: datetime.date or pd.Timestamp to count.

    Returns:
        Series of trip counts indexed by base route.
    """
    ymd = day.strftime("%Y%m%d")
    cal = read_gtfs(source, "calendar.txt")
    # Filter to services that run on the weekday and cover the date.
    weekday = day.strftime("%A").lower()  # e.g. "wednesday", a column of calendar.txt
    runs_that_weekday = cal[weekday] == config.SERVICE_RUNS
    in_date_range = (cal.start_date <= ymd) & (cal.end_date >= ymd)
    services = set(cal.service_id[runs_that_weekday & in_date_range])

    exceptions = read_gtfs(source, "calendar_dates.txt")
    exceptions = exceptions[exceptions.date == ymd]
    services |= set(exceptions.service_id[exceptions.exception_type == config.SERVICE_ADDED])
    services -= set(exceptions.service_id[exceptions.exception_type == config.SERVICE_REMOVED])

    routes = read_gtfs(source, "routes.txt")
    routes = routes[routes.route_type == config.BUS_ROUTE_TYPE]
    trips = read_gtfs(source, "trips.txt")
    trips = trips[trips.service_id.isin(services)].merge(
        routes[["route_id", "route_short_name"]], on="route_id")
    return trips.groupby(base_route(trips.route_short_name)).size()


def weekday_trips(source, start):
    """Counts weekday bus trips per base route on Wednesdays on or after start date for 4 wednesdays (WEEKDAY_WINDOW_WEEKS).

    Wednesdays are used as a representative weekday (lower chance of being part of public holiday and/or long weekend), and the maximum count across the 4 weeks is returned.

    Args:
        source: Timetable folder or zip (see read_gtfs).
        start: datetime.date the window starts on.

    Returns:
        Series of trip counts indexed by base route.
    """
    days = pd.date_range(
        start, periods=config.WEEKDAY_WINDOW_WEEKS, freq="W-WED")
    counts = pd.concat([trips_on_date(source, d)
                       for d in days], axis=1).fillna(0)
    return counts.max(axis=1).astype(int)


def route_shapes(source, routes):
    """Picks one shape per base route: the one its trips use most.

    Args:
        source: Timetable folder or zip (see read_gtfs).
        routes: Iterable of base route codes.

    Returns:
        Dict of base route -> DataFrame of shape points (lat, lon) in order.
    """
    names = read_gtfs(source, "routes.txt")[["route_id", "route_short_name"]]
    trips = read_gtfs(source, "trips.txt").merge(names, on="route_id")
    trips["route"] = base_route(trips.route_short_name)
    trips = trips[trips.route.isin(routes)]
    main_shape = trips.groupby("route").shape_id.agg(lambda s: s.mode()[0])

    shapes = read_gtfs(source, "shapes.txt")
    shapes = shapes[shapes.shape_id.isin(main_shape)]
    shapes = shapes.astype({"shape_pt_lat": float, "shape_pt_lon": float,
                            "shape_pt_sequence": int})
    by_shape = {sid: pts.sort_values("shape_pt_sequence")
                for sid, pts in shapes.groupby("shape_id")}
    return {route: by_shape[sid] for route, sid in main_shape.items()}
