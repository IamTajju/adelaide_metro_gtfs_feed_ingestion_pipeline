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

    stops = pd.read_csv(config.TIMETABLE_DIR / "stops.txt", dtype={"stop_id": str})
    in_cbd = (stops.stop_lat.between(config.CBD_SOUTH, config.CBD_NORTH)
              & stops.stop_lon.between(config.CBD_WEST, config.CBD_EAST))
    return set(stops.stop_id[in_cbd])
