# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         select_routes/main.py
# Date:         27-09-2026
# Description:  Top-k route selection driver and demand ranking logic.
# Usage:        python -m select_routes
"""Top-k route selection driver and demand ranking logic.

T02: candidate routes by demand (Metrocard boardings at CBD stops).
  - Downloads the latest validations quarter from data.sa.gov.au
  - Fetches and caches the static timetable (checking version.txt for changes)
  - Ranks candidates and outputs data/selection/candidates.csv

TODO: T03, T04 (see docs/TICKETS.md).
"""

import pandas as pd

import config
from select_routes.timetable import load_bus_routes, cbd_stop_ids
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

    from select_routes.timetable import base_route
    v["route"] = base_route(v.ROUTE_CODE)

    routes = load_bus_routes()
    variants = routes.groupby("route").route_id.apply(lambda ids: " ".join(sorted(ids)))

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
    config.SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(config.SELECTION_DIR / "candidates.csv", index=False)
    print(candidates.to_string(index=False))


if __name__ == "__main__":
    main()
