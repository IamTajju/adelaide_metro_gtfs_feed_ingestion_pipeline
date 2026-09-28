# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         gtfs_position_collection/filters.py
# Date:         29-09-2026
# Description:  Keeps only the pings of chosen routes near chosen stops.
# Usage:        from gtfs_position_collection import filters
"""Keeps only the pings of chosen routes near chosen stops.

The live feed carries every bus in Adelaide, but the study only needs the
chosen routes while they are close to the chosen stops. keep_relevant()
takes the flattened rows the collector fetches and drops everything else,
so it can sit directly between the feed snapshot and the database insert.

A ping is kept when its route is chosen and it lies within STOP_RADIUS_M
of at least one chosen stop. That also covers the boundary rule from the
meeting: a bus that has not yet reached the first chosen stop of its route
is outside every radius, so nothing of it is recorded.

The chosen routes and stops are the files the selection stages write into
data/selection: routes.csv with a route_id column, and stops.csv with
stop_id, stop_lat and stop_lon columns.
"""

import csv
import math

from shared import config

# A bus counts as "at" a stop when it is inside this circle around it.
STOP_RADIUS_M = 500.0

EARTH_RADIUS_M = 6371000.0

ROUTES_CSV = config.SELECTION_DIR / "routes.csv"
STOPS_CSV = config.SELECTION_DIR / "stops.csv"


def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points, in metres.

    Args:
        lat1, lon1: First point in decimal degrees.
        lat2, lon2: Second point in decimal degrees.

    Returns:
        Distance in metres.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def nearest_stop(lat, lon, stops):
    """Finds the chosen stop closest to a position.

    Args:
        lat, lon: Position of the bus in decimal degrees.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.

    Returns:
        Tuple of (stop_id, distance_m) of the closest stop, or (None, inf)
        when the stop list is empty.
    """
    best_id, best_dist = None, math.inf
    for stop_id, stop_lat, stop_lon in stops:
        dist = haversine(lat, lon, stop_lat, stop_lon)
        if dist < best_dist:
            best_id, best_dist = stop_id, dist
    return best_id, best_dist


def is_relevant(row, route_ids, stops, radius_m=STOP_RADIUS_M):
    """Decides whether one flattened ping row is worth storing.

    A row without a route or a position can never match a chosen stop, so
    it is dropped as well.

    Args:
        row: Flattened feed row with trip_route_id, position_latitude and
            position_longitude keys, as the collector fetches them.
        route_ids: Set of chosen route ids.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.
        radius_m: Radius around a stop that counts as relevant.

    Returns:
        True when the ping belongs to a chosen route near a chosen stop.
    """
    lat = row.get("position_latitude")
    lon = row.get("position_longitude")
    if row.get("trip_route_id") not in route_ids or lat is None or lon is None:
        return False
    return nearest_stop(lat, lon, stops)[1] <= radius_m


def keep_relevant(rows, route_ids, stops, radius_m=STOP_RADIUS_M):
    """Filters one fetched poll down to the rows the study needs.

    Args:
        rows: List of flattened feed rows.
        route_ids: Set of chosen route ids.
        stops: List of (stop_id, stop_lat, stop_lon) tuples.
        radius_m: Radius around a stop that counts as relevant.

    Returns:
        The rows that pass is_relevant, in their original order.
    """
    return [row for row in rows if is_relevant(row, route_ids, stops, radius_m)]


def load_selection(routes_csv=None, stops_csv=None):
    """Reads the chosen routes and stops written by the selection stages.

    Args:
        routes_csv: Optional path to the routes file, data/selection/routes.csv
            by default.
        stops_csv: Optional path to the stops file, data/selection/stops.csv
            by default.

    Returns:
        Tuple of (route_ids, stops) where route_ids is a set of route ids
        and stops is a list of (stop_id, stop_lat, stop_lon) tuples.
    """
    routes_csv = ROUTES_CSV if routes_csv is None else routes_csv
    stops_csv = STOPS_CSV if stops_csv is None else stops_csv
    with open(routes_csv, newline="", encoding="utf-8") as handle:
        route_ids = {row["route_id"] for row in csv.DictReader(handle)}
    stops = []
    with open(stops_csv, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            stops.append((row["stop_id"],
                          float(row["stop_lat"]), float(row["stop_lon"])))
    return route_ids, stops
