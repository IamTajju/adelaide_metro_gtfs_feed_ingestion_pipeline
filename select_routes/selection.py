# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/selection.py
# Date:         03-10-2026
# Description:  Picks the top-k routes by weighted rank with N/E/S/W coverage.
# Usage:        make selection  (or python -m select_routes.selection)
"""Picks the top-k routes by weighted rank with N/E/S/W coverage.

Reads the latest candidates CSV and writes data/selection/routes_<timestamp>.csv
plus a map of the chosen routes.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from shared import config
from shared.timetable import get_primary_route_shapes
from select_routes.plots import latest_candidates, route_map


def route_directions(routes, source=config.TIMETABLE_DIR):
    """Gives each route a compass direction from Victoria Square.

    The direction is the bearing to the route's point furthest from Victoria
    Square, rounded to the nearest of N/E/S/W (90 degree sectors).

    Args:
        routes: Iterable of base route codes.
        source: Timetable folder or zip (see read_gtfs).

    Returns:
        Series of direction letters indexed by base route.
    """
    directions = {}
    for route, pts in get_primary_route_shapes(source, routes).items():
        dy = pts.shape_pt_lat.values - config.VICTORIA_SQUARE_LAT
        # Scale longitude so east-west degrees match north-south ones.
        dx = ((pts.shape_pt_lon.values - config.VICTORIA_SQUARE_LON)
              * np.cos(np.radians(config.VICTORIA_SQUARE_LAT)))
        far = np.argmax(np.hypot(dx, dy))
        bearing = np.degrees(np.arctan2(dx[far], dy[far])) % 360
        directions[route] = config.DIRECTIONS[int((bearing + 45) % 360 // 90)]
    return pd.Series(directions)


def select_routes(candidates):
    """Scores candidates by weighted rank and picks K_ROUTES covering every direction.

    score = WEIGHT_BOARDINGS * boardings rank + WEIGHT_TRIPS * trips rank
    (rank 1 = most, so lower is better). The best route in each direction is
    taken first, then the rest are filled by score.

    Args:
        candidates: DataFrame with columns route, cbd_boardings, weekday_trips.

    Returns:
        Candidates with rank, score, direction and chosen columns, sorted by score.
    """
    c = candidates.copy()
    c["boardings_rank"] = c.cbd_boardings.rank(
        ascending=False, method="min").astype(int)
    c["trips_rank"] = c.weekday_trips.rank(
        ascending=False, method="min").astype(int)
    c["score"] = (config.WEIGHT_BOARDINGS * c.boardings_rank
                  + config.WEIGHT_TRIPS * c.trips_rank).round(2)
    c["direction"] = c.route.map(route_directions(c.route))
    c = c.sort_values(["score", "boardings_rank"]).reset_index(drop=True)

    missing = set(config.DIRECTIONS) - set(c.direction)
    if missing:
        print("no candidate heads %s; coverage is partial" %
              " ".join(sorted(missing)))
    best_per_direction = c.groupby("direction").head(1).index
    rest = c.index.difference(best_per_direction, sort=False)
    chosen = list(best_per_direction) + \
        list(rest[:config.K_ROUTES - len(best_per_direction)])
    c["chosen"] = c.index.isin(chosen)
    return c


def main():
    """Selects routes from the latest candidates and writes them to data/selection/."""
    src = latest_candidates()
    print("candidates from %s" % src)
    ranked = select_routes(pd.read_csv(src, dtype={"route": str}))
    print(ranked.drop(columns="gtfs_route_ids").to_string(index=False))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("routes_%s.csv" % stamp)
    ranked[ranked.chosen].drop(columns="chosen").to_csv(path, index=False)
    print("wrote %s" % path)
    map_path = config.SELECTION_DIR / ("routes_map_%s.png" % stamp)
    route_map(path, map_path, title="Selected bus routes by weekday trips")
    print("wrote %s" % map_path)


if __name__ == "__main__":
    main()
