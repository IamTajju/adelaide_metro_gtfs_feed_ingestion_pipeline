# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/selection.py
# Date:         03-10-2026
# Description:  Picks the top-k routes by weighted rank with N/E/S/W coverage.
# Usage:        make selection  (or python -m select_routes.selection)
"""Picks the top-k routes by weighted rank with N/E/S/W coverage.

Reads the latest route_candidates CSV and writes data/selection/top_k_routes_<timestamp>.csv
plus a map of the chosen routes.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from shared import config
from shared.timetable import get_primary_route_shapes
from select_routes.plots import get_latest_route_candidates, draw_route_map


def route_directions(routes, metro_timetable_path=config.TIMETABLE_DIR):
    """Gives each route a compass direction from Victoria Square.

    The direction is the bearing to the route's point furthest from Victoria
    Square, rounded to the nearest of N/E/S/W (90 degree sectors).

    Args:
        routes: Iterable of base route codes.
        metro_timetable_path: Timetable folder or zip (see read_gtfs).

    Returns:
        Series of direction letters indexed by base route.
    """
    directions = {}
    for route, pts in get_primary_route_shapes(metro_timetable_path, routes).items():
        dy = pts.shape_pt_lat.values - config.VICTORIA_SQUARE_LAT
        # Scale longitude so east-west degrees match north-south ones.
        dx = ((pts.shape_pt_lon.values - config.VICTORIA_SQUARE_LON)
              * np.cos(np.radians(config.VICTORIA_SQUARE_LAT)))
        far = np.argmax(np.hypot(dx, dy))
        bearing = np.degrees(np.arctan2(dx[far], dy[far])) % 360
        directions[route] = config.DIRECTIONS[int((bearing + 45) % 360 // 90)]
    return pd.Series(directions)


def select_routes(route_candidates):
    """Scores the route candidates by weighted rank and picks K_ROUTES covering every direction.

    score = WEIGHT_BOARDINGS * boardings rank + WEIGHT_TRIPS * trips rank
    (rank 1 = most, so lower is better). The best route in each direction is
    taken first, then the rest are filled by score.

    Args:
        route_candidates: DataFrame with columns route, cbd_boardings, weekday_trips.

    Returns:
        route_candidates with rank, score, direction and chosen columns, sorted by score.
    """
    candidates = route_candidates.copy()
    candidates["boardings_rank"] = candidates.cbd_boardings.rank(
        ascending=False, method="min").astype(int)
    candidates["trips_rank"] = candidates.weekday_trips.rank(
        ascending=False, method="min").astype(int)
    candidates["score"] = (config.WEIGHT_BOARDINGS * candidates.boardings_rank
                  + config.WEIGHT_TRIPS * candidates.trips_rank).round(2)
    candidates["direction"] = candidates.route.map(route_directions(candidates.route))
    candidates = candidates.sort_values(["score", "boardings_rank"]).reset_index(drop=True)

    missing = set(config.DIRECTIONS) - set(candidates.direction)
    if missing:
        print("no candidate heads %s; coverage is partial" %
              " ".join(sorted(missing)))
    best_per_direction = candidates.groupby("direction").head(1).index
    rest = candidates.index.difference(best_per_direction, sort=False)
    chosen = list(best_per_direction) + \
        list(rest[:config.K_ROUTES - len(best_per_direction)])
    candidates["chosen"] = candidates.index.isin(chosen)
    return candidates


def main():
    """Selects routes from the latest route candidates and writes them to data/selection/."""
    src = get_latest_route_candidates()
    print("candidates from %s" % src)
    ranked = select_routes(pd.read_csv(src, dtype={"route": str}))
    print(ranked.drop(columns="gtfs_route_ids").to_string(index=False))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("top_k_routes_%s.csv" % stamp)
    ranked[ranked.chosen].drop(columns="chosen").to_csv(path, index=False)
    print("wrote %s" % path)
    map_path = config.SELECTION_DIR / ("top_k_routes_map_%s.png" % stamp)
    draw_route_map(
        path, map_path, title="Top %d bus routes" % config.K_ROUTES)
    print("wrote %s" % map_path)


if __name__ == "__main__":
    main()
