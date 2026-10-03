# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/main.py
# Date:         27-09-2026
# Description:  Top-k route selection driver and demand ranking logic.
# Usage:        python -m select_routes
"""Top-k route selection driver and demand ranking logic.

T02: candidate routes by demand (Metrocard boardings at CBD stops).
  - Downloads the latest validations quarter from data.sa.gov.au
  - Fetches and caches the static timetable (checking version.txt for changes)
  - Ranks candidates and outputs data/selection/candidates_<timestamp>.csv

TODO: T03, T04 (see docs/TICKETS.md).
"""

from datetime import date, datetime

import pandas as pd

from shared import config
from shared.timetable import base_route, cbd_stop_ids, load_bus_routes, weekday_trips
from select_routes.validations import download_latest_validations


def demand_candidates(validations_path):
    """Ranks bus routes by boardings at CBD stops and keeps the top N.

    Boardings are banded, so BAND_BOARDINGS_FLOOR is summed (a lower bound).
    Variants are merged into their base route; the GTFS route_ids of every
    variant are kept so the collector can match live vehicles later.

    Args:
        validations_path: Path to a quarterly validations CSV.

    Returns:
        DataFrame with columns route, cbd_boardings, gtfs_route_ids.
    """
    v = pd.read_csv(validations_path, encoding="utf-8-sig", dtype=str)
    v = v[v.NUM_MODE_TRANSPORT == config.BUS_MODE]
    v["boardings"] = v.BAND_BOARDINGS_FLOOR.astype(int)
    v["route"] = base_route(v.ROUTE_CODE)

    routes = load_bus_routes()
    variants = routes.groupby("route").route_id.apply(
        lambda ids: " ".join(sorted(ids)))

    # Report codes with no GTFS bus route (special events, substitutes, night buses).
    unmatched = v[~v.route.isin(variants.index)]
    print("unmatched route codes: %.2f%% of bus boardings, codes: %s" % (
        100 * unmatched.boardings.sum() / v.boardings.sum(),
        " ".join(sorted(unmatched.ROUTE_CODE.unique()))))

    cbd = v[v.route.isin(variants.index) & v.GTFS_ID.isin(cbd_stop_ids())]
    top = (cbd.groupby("route").boardings.sum()
           .nlargest(config.N_CANDIDATES).rename("cbd_boardings").reset_index())
    top["gtfs_route_ids"] = top.route.map(variants)
    return top


def main():
    """Runs route selection and writes the results to data/selection/."""
    candidates = demand_candidates(download_latest_validations())
    next_four_bus_service_counts = weekday_trips(config.TIMETABLE_DIR, date.today())
    candidates["weekday_trips"] = candidates.route.map(next_four_bus_service_counts).fillna(0).astype(int)
    config.SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    # Timestamped so each run is kept; names sort oldest -> newest.
    path = config.SELECTION_DIR / ("candidates_%s.csv" % datetime.now().strftime("%Y%m%d-%H%M%S"))
    candidates.to_csv(path, index=False)
    print(candidates.to_string(index=False))
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
