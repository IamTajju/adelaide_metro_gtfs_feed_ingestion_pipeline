# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_stops/candidates.py
# Date:         06-10-2026
# Description:  Stop candidates: every CBD stop served by the top k routes, with boardings.
# Usage:        from select_stops.candidates import find_cbd_stops_served_by_routes, ...
"""Stop candidates: every CBD stop served by the top k routes, with its boardings on that route."""

import pandas as pd

from shared import config
from shared.timetable import cbd_stop_ids, read_gtfs, strip_route_variants


def find_cbd_stops_served_by_routes(top_k_routes, metro_timetable_path=config.TIMETABLE_DIR):
    """Finds every CBD stop that the trips of each route stop at.

    Chain: each route's GTFS route_ids (all variants) -> trips.txt -> stop_times.txt
    -> stops.txt, keeping stops inside the CBD box.

    Args:
        top_k_routes: DataFrame with columns route, gtfs_route_ids (space-separated).
        metro_timetable_path: Timetable folder or zip (see read_gtfs).

    Returns:
        DataFrame with columns route, stop_id, stop_name, stop_lat, stop_lon;
        one row per route x stop, sorted by route then stop name.
    """
    # Create expanded DataFrame of route IDs.
    route_ids_by_route = (top_k_routes.assign(route_id=top_k_routes.gtfs_route_ids.str.split())
                          .explode("route_id")[["route", "route_id"]])

    trips = read_gtfs(metro_timetable_path, "trips.txt", columns=["route_id", "trip_id"])
    # Join to keep only trips of the top k routes (all variants).
    trips_of_routes = trips.merge(route_ids_by_route, on="route_id")

    # Find the stops served by those trips, keeping only those in the CBD box.
    stop_times = read_gtfs(metro_timetable_path, "stop_times.txt", columns=["trip_id", "stop_id"])
    stop_times = stop_times[stop_times.trip_id.isin(trips_of_routes.trip_id)]
    stops_served_by_route = (stop_times.merge(trips_of_routes[["trip_id", "route"]], on="trip_id")
                             [["route", "stop_id"]].drop_duplicates())

    stops = read_gtfs(metro_timetable_path, "stops.txt",
                      columns=["stop_id", "stop_name", "stop_lat", "stop_lon"])
    cbd_stops = stops[stops.stop_id.isin(cbd_stop_ids())]

    # Join to keep only the stops served by the top k routes that are in the CBD box.
    return (stops_served_by_route.merge(cbd_stops, on="stop_id")
            .sort_values(["route", "stop_name"]).reset_index(drop=True))


def sum_boardings_by_route_and_stop(metrocard_taps_quarterly_data_path):
    """Sums bus boardings per base route and stop over the quarter.

    Boardings are range-based, so BAND_BOARDINGS_FLOOR is summed (a lower bound).
    GTFS_ID in the taps data is the GTFS stop_id.

    Args:
        metrocard_taps_quarterly_data_path: Path to a quarterly metrocard taps CSV.

    Returns:
        DataFrame with columns route, stop_id, stop_boardings.
    """
    metrocard_taps = pd.read_csv(metrocard_taps_quarterly_data_path, encoding="utf-8-sig", dtype=str,
                                 usecols=["NUM_MODE_TRANSPORT", "ROUTE_CODE", "GTFS_ID",
                                          "BAND_BOARDINGS_FLOOR"])
    bus_taps = metrocard_taps[metrocard_taps.NUM_MODE_TRANSPORT == config.BUS_MODE]
    bus_taps = bus_taps.assign(route=strip_route_variants(bus_taps.ROUTE_CODE),
                               stop_id=bus_taps.GTFS_ID,
                               stop_boardings=bus_taps.BAND_BOARDINGS_FLOOR.astype(int))
    return bus_taps.groupby(["route", "stop_id"], as_index=False).stop_boardings.sum()


def add_boardings_to_stop_candidates(stop_candidates, boardings_by_route_and_stop):
    """Adds each stop's boardings on its route; 0 where the stop has no tap-ons.

    Args:
        stop_candidates: DataFrame with columns route, stop_id (see find_cbd_stops_served_by_routes).
        boardings_by_route_and_stop: DataFrame with columns route, stop_id, stop_boardings.

    Returns:
        stop_candidates with a stop_boardings column, sorted by route then most boardings first.
    """
    # Join to add the stop_boardings column, filling NaN with 0.
    stop_candidates_with_boardings = stop_candidates.merge(
        boardings_by_route_and_stop, on=["route", "stop_id"], how="left")
    # Fill NaN with 0 and convert to int, then sort by route then most boardings first.
    stop_candidates_with_boardings["stop_boardings"] = (
        stop_candidates_with_boardings.stop_boardings.fillna(0).astype(int))
    # Sort by route then most boardings first, resetting the index.
    return (stop_candidates_with_boardings
            .sort_values(["route", "stop_boardings"], ascending=[True, False])
            .reset_index(drop=True))
