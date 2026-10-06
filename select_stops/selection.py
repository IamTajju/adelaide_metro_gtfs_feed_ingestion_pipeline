# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_stops/selection.py
# Date:         06-10-2026
# Description:  Picks the top n CBD stops per route with N/E/S/W quadrant coverage.
# Usage:        make stop_selection  (or python -m select_stops.selection)
"""Picks the top n CBD stops per route with N/E/S/W quadrant coverage.

Reads the latest stop_candidates CSV and writes data/selection/top_m_stops_<timestamp>.csv
(one row per route x chosen stop; m = the number of unique stops), plus a CBD map
of the chosen stops coloured by quadrant.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from shared import config
from select_stops.plots import draw_top_stops_cbd_map


def get_latest_stop_candidates():
    """Returns the path of the newest data/selection/stop_candidates_<timestamp>.csv.

    Raises:
        FileNotFoundError: if the stop candidates have not been built yet.
    """
    stop_candidates_paths = sorted(config.SELECTION_DIR.glob("stop_candidates_*.csv"))
    if not stop_candidates_paths:
        raise FileNotFoundError(
            "no stop_candidates_*.csv in %s; run `make stop_candidates` first" % config.SELECTION_DIR)
    return stop_candidates_paths[-1]


def tag_stops_by_quadrant(stop_lats, stop_lons):
    """Tags each stop N/E/S/W by its bearing from Victoria Square (90 degree sectors).

    Args:
        stop_lats: Series of stop latitudes.
        stop_lons: Series of stop longitudes.

    Returns:
        Series of quadrant letters, aligned with the inputs.
    """
    north_offsets = stop_lats - config.VICTORIA_SQUARE_LAT
    # Scale longitude so east-west degrees match north-south ones.
    east_offsets = ((stop_lons - config.VICTORIA_SQUARE_LON)
                    * np.cos(np.radians(config.VICTORIA_SQUARE_LAT)))
    # Compute the bearing in degrees, then map to quadrants (N=0, E=1, S=2, W=3).
    bearings = np.degrees(np.arctan2(east_offsets, north_offsets)) % 360
    quadrant_indexes = ((bearings + 45) % 360 // 90).astype(int)
    # Map quadrant indexes to letters using config.DIRECTIONS.
    return quadrant_indexes.map(lambda index: config.DIRECTIONS[index])


def find_removable_pick(top_stops, route):
    """Finds the route's lowest-boardings pick that can go without losing a quadrant.

    Args:
        top_stops: Current picks with columns route, stop_id, quadrant, stop_boardings.
        route: Base route code whose picks may be swapped.

    Returns:
        Index label of the pick to remove, or None if every pick holds a quadrant.
    """
    # For each pick of the route, starting from the lowest boardings, check if removing it leaves another quadrant empty.
    for pick_index in top_stops[top_stops.route == route].sort_values("stop_boardings").index:
        other_picks = top_stops.drop(index=pick_index)
        if top_stops.at[pick_index, "quadrant"] in set(other_picks.quadrant):
            return pick_index
    return None


def select_top_stops(stop_candidates):
    """Picks the top N_STOPS_PER_ROUTE stops per route, then swaps to cover every quadrant.

    For each missing quadrant, the candidate in that quadrant with the most
    boardings on its route replaces that route's lowest pick, as long as the
    removed pick does not leave another quadrant empty.

    Args:
        stop_candidates: DataFrame with columns route, stop_id, stop_name, stop_lat,
            stop_lon, stop_boardings (one row per route x stop).

    Returns:
        The chosen route x stop rows with quadrant, stop_rank_on_route and
        chosen_by ("top n" or "quadrant swap"), sorted by route then rank.
    """
    stop_candidates = stop_candidates.assign(
        quadrant=tag_stops_by_quadrant(stop_candidates.stop_lat, stop_candidates.stop_lon),
        stop_rank_on_route=stop_candidates.groupby("route").stop_boardings
        .rank(ascending=False, method="first").astype(int))
    top_stops = stop_candidates[stop_candidates.stop_rank_on_route <= config.N_STOPS_PER_ROUTE]
    top_stops = top_stops.assign(chosen_by="top n")

    for missing_quadrant in [q for q in config.DIRECTIONS if q not in set(top_stops.quadrant)]:
        quadrant_candidates = (stop_candidates[stop_candidates.quadrant == missing_quadrant]
                               .sort_values("stop_boardings", ascending=False))
        if quadrant_candidates.empty:
            print("no stop candidate in quadrant %s; coverage is partial" % missing_quadrant)
            continue
        for _, replacement in quadrant_candidates.iterrows():
            removable_pick = find_removable_pick(top_stops, replacement.route)
            if removable_pick is None:
                continue
            print("quadrant %s missing: route %s swaps %s for %s" % (
                missing_quadrant, replacement.route,
                top_stops.at[removable_pick, "stop_name"], replacement.stop_name))
            top_stops = pd.concat([top_stops.drop(index=removable_pick),
                                   replacement.to_frame().T.assign(chosen_by="quadrant swap")])
            break

    return top_stops.sort_values(["route", "stop_rank_on_route"]).reset_index(drop=True)


def main():
    """Selects stops from the latest stop candidates and writes them to data/selection/."""
    stop_candidates_path = get_latest_stop_candidates()
    print("stop candidates from %s" % stop_candidates_path)
    stop_candidates = pd.read_csv(stop_candidates_path, dtype={"route": str, "stop_id": str})

    top_stops = select_top_stops(stop_candidates)
    print(top_stops[["route", "stop_id", "stop_name", "quadrant", "stop_boardings",
                     "stop_rank_on_route", "chosen_by"]].to_string(index=False))
    print("m = %d unique stops; per quadrant: %s" % (
        top_stops.stop_id.nunique(),
        top_stops.drop_duplicates("stop_id").quadrant.value_counts()
        .reindex(list(config.DIRECTIONS), fill_value=0).to_dict()))

    # Timestamped so each run is kept; names sort oldest -> newest.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("top_m_stops_%s.csv" % stamp)
    top_stops.to_csv(path, index=False)
    print("wrote %s" % path)

    # Draw the chosen stops on a CBD map, coloured by quadrant.
    map_path = config.SELECTION_DIR / ("top_m_stops_map_%s.png" % stamp)
    draw_top_stops_cbd_map(path, stop_candidates_path, map_path)
    print("wrote %s" % map_path)


if __name__ == "__main__":
    main()
