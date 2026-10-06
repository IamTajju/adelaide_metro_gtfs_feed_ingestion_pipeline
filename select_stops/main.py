# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_stops/main.py
# Date:         06-10-2026
# Description:  Stop candidates driver: reads the top k routes, writes their CBD stops with boardings.
# Usage:        python -m select_stops

"""Stop candidates driver: reads the top k routes, writes their CBD stops with boardings.
  - Reads the latest data/selection/top_k_routes_<timestamp>.csv (run `make route_selection` first)
  - Finds the CBD stops each route serves (select_stops/candidates.py)
  - Adds each stop's boardings on that route from the latest quarterly metrocard taps data
  - Outputs data/selection/stop_candidates_<timestamp>.csv (one row per route x stop)

"""

from datetime import datetime
import pandas as pd
from shared import config
from select_routes.validations import download_latest_quaterly_metro_taps_data
from select_stops.candidates import (add_boardings_to_stop_candidates, find_cbd_stops_served_by_routes,
                                     sum_boardings_by_route_and_stop)


def get_latest_top_k_routes():
    """Returns the path of the newest data/selection/top_k_routes_<timestamp>.csv.

    Raises:
        FileNotFoundError: if route selection has not been run yet.
    """
    top_k_routes_paths = sorted(config.SELECTION_DIR.glob("top_k_routes_*.csv"))
    if not top_k_routes_paths:
        raise FileNotFoundError(
            "no top_k_routes_*.csv in %s; run `make route_candidates` then `make route_selection` first"
            % config.SELECTION_DIR)
    return top_k_routes_paths[-1]


def main():
    """Finds the CBD stops of the latest top k routes, adds boardings, and writes them to data/selection/."""
    top_k_routes_path = get_latest_top_k_routes()
    print("top k routes from %s" % top_k_routes_path)
    top_k_routes = pd.read_csv(top_k_routes_path, dtype={"route": str})

    stop_candidates = find_cbd_stops_served_by_routes(top_k_routes)
    boardings_by_route_and_stop = sum_boardings_by_route_and_stop(
        download_latest_quaterly_metro_taps_data())
    stop_candidates = add_boardings_to_stop_candidates(stop_candidates, boardings_by_route_and_stop)
    print(stop_candidates.groupby("route").agg(
        cbd_stops=("stop_id", "size"), stops_without_taps=("stop_boardings", lambda b: (b == 0).sum()),
        total_stop_boardings=("stop_boardings", "sum")).to_string())
    print("%d unique CBD stops across %d routes" % (
        stop_candidates.stop_id.nunique(), stop_candidates.route.nunique()))

    # Timestamped so each run is kept; names sort oldest -> newest.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("stop_candidates_%s.csv" % stamp)
    stop_candidates.to_csv(path, index=False)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
