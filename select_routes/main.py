# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/main.py
# Date:         27-09-2026
# Description:  Top-k route selection driver and demand ranking logic.
# Usage:        python -m select_routes

"""Top-k route selection driver and demand ranking logic.
  - Downloads the latest validations quarter (Demand data of metrocard boardings) from data.sa.gov.au
  - Fetches and caches the static timetable (checking version.txt for changes)
  - Ranks candidates and outputs data/selection/candidates_<timestamp>.csv
  - Draws a route map of the candidates on an Adelaide basemap (data/selection/route_map_<timestamp>.png).
"""

from datetime import date, datetime
import pandas as pd
from shared import config
from shared.timetable import strip_route_variants, cbd_stop_ids, load_bus_routes, count_peak_weekday_trips_by_route
from select_routes.plots import route_map
from select_routes.validations import download_latest_quaterly_metro_taps_data


def rank_routes_by_cbd_boardings(metrocard_taps_quarterly_data_path):
    """Ranks bus routes by boardings at CBD stops and keeps the top N.

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
    top_n_routes_by_cbd_boardings = (cbd.groupby("route").boardings.sum()
                                     .nlargest(config.N_CANDIDATES).rename("cbd_boardings").reset_index())
    top_n_routes_by_cbd_boardings["gtfs_route_ids"] = top_n_routes_by_cbd_boardings.route.map(
        variant_route_ids_by_base_route)
    return top_n_routes_by_cbd_boardings


def main():
    """Runs route selection and writes the results to data/selection/."""
    top_n_routes_by_cbd_boardings = rank_routes_by_cbd_boardings(
        download_latest_quaterly_metro_taps_data())
    # Count the number of trips per base route on a weekday in the last 4 weeks.
    peak_weekday_trips_by_route = count_peak_weekday_trips_by_route(
        config.TIMETABLE_DIR, date.today())
    top_n_routes_by_cbd_boardings["weekday_trips"] = top_n_routes_by_cbd_boardings.route.map(
        peak_weekday_trips_by_route).fillna(0).astype(int)
    
    config.SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    # Timestamped so each run is kept; names sort oldest -> newest.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("candidates_%s.csv" % stamp)
    top_n_routes_by_cbd_boardings.to_csv(path, index=False)
    print(top_n_routes_by_cbd_boardings.to_string(index=False))
    print("wrote %s" % path)
    
    # Draw a map of the selected routes on an Adelaide basemap.
    map_path = config.SELECTION_DIR / ("route_map_%s.png" % stamp)
    route_map(path, map_path)
    print("wrote %s" % map_path)


if __name__ == "__main__":
    main()
