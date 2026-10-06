# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/candidates.py
# Date:         06-10-2026
# Description:  Route candidates: bus routes ranked by Metrocard boardings at CBD stops.
# Usage:        from select_routes.candidates import rank_routes_by_cbd_boardings
"""Route candidates: bus routes ranked by Metrocard boardings at CBD stops."""

import pandas as pd

from shared import config
from shared.timetable import cbd_stop_ids, load_bus_routes, strip_route_variants


def rank_routes_by_cbd_boardings(metrocard_taps_quarterly_data_path):
    """Ranks bus routes by boardings at CBD stops and keeps the top N_CANDIDATES.

    Boardings are range-based, so BAND_BOARDINGS_FLOOR is summed (a lower bound).
    Variants are merged into their base route; the GTFS route_ids of every
    variant are kept so the collector can match live vehicles later.

    Args:
        metrocard_taps_quarterly_data_path: Path to a quarterly metrocard taps CSV.

    Returns:
        DataFrame with columns route, cbd_boardings, gtfs_route_ids.
    """
    metrocard_taps_df = pd.read_csv(
        metrocard_taps_quarterly_data_path, encoding="utf-8-sig", dtype=str)
    metrocard_taps_df = metrocard_taps_df[metrocard_taps_df.NUM_MODE_TRANSPORT == config.BUS_MODE]
    metrocard_taps_df["boardings"] = metrocard_taps_df.BAND_BOARDINGS_FLOOR.astype(
        int)
    metrocard_taps_df["route"] = strip_route_variants(
        metrocard_taps_df.ROUTE_CODE)

    routes = load_bus_routes()
    variant_route_ids_by_base_route = routes.groupby("route").route_id.apply(
        lambda ids: " ".join(sorted(ids)))

    # Report codes with no GTFS bus route (special events, substitutes, night buses).
    unmatched = metrocard_taps_df[~metrocard_taps_df.route.isin(
        variant_route_ids_by_base_route.index)]
    print("unmatched route codes: %.2f%% of bus boardings, codes: %s" % (
        100 * unmatched.boardings.sum() / metrocard_taps_df.boardings.sum(),
        " ".join(sorted(unmatched.ROUTE_CODE.unique()))))

    cbd = metrocard_taps_df[metrocard_taps_df.route.isin(
        variant_route_ids_by_base_route.index) & metrocard_taps_df.GTFS_ID.isin(cbd_stop_ids())]
    route_candidates = (cbd.groupby("route").boardings.sum()
                        .nlargest(config.N_CANDIDATES).rename("cbd_boardings").reset_index())
    route_candidates["gtfs_route_ids"] = route_candidates.route.map(
        variant_route_ids_by_base_route)
    return route_candidates
