# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/main.py
# Date:         27-09-2026
# Description:  Route candidates driver: ranks routes by CBD boardings, adds weekday trips, writes CSV and charts.
# Usage:        python -m select_routes

"""Route candidates driver: ranks routes by CBD boardings, adds weekday trips, writes CSV and charts.
  - Downloads the latest validations quarter (Demand data of metrocard boardings) from data.sa.gov.au
  - Fetches and caches the static timetable (checking version.txt for changes)
  - Ranks routes by CBD boardings (select_routes/candidates.py) and outputs the candidates to data/selection/route_candidates_<timestamp>.csv
  - Draws a route map of the candidates on an Adelaide basemap (data/selection/route_candidates_map_<timestamp>.png).
  - Draws bar charts of CBD boardings and weekday trips per candidate (data/selection/route_candidates_bar_charts_<timestamp>.png).
"""

from datetime import date, datetime
from shared import config
from shared.timetable import count_peak_weekday_trips_by_route
from select_routes.candidates import rank_routes_by_cbd_boardings
from select_routes.plots import draw_boardings_and_weekday_trips_bar_charts, draw_route_map
from select_routes.validations import download_latest_quaterly_metro_taps_data


def main():
    """Runs route selection and writes the results to data/selection/."""
    route_candidates = rank_routes_by_cbd_boardings(
        download_latest_quaterly_metro_taps_data())
    # Count the number of trips per base route on a weekday in the last 4 weeks.
    peak_weekday_trips_by_route = count_peak_weekday_trips_by_route(
        config.TIMETABLE_DIR, date.today())
    route_candidates["weekday_trips"] = route_candidates.route.map(
        peak_weekday_trips_by_route).fillna(0).astype(int)

    config.SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    # Timestamped so each run is kept; names sort oldest -> newest.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = config.SELECTION_DIR / ("route_candidates_%s.csv" % stamp)
    route_candidates.to_csv(path, index=False)
    print(route_candidates.to_string(index=False))
    print("wrote %s" % path)

    # Draw a map of the candidate routes on an Adelaide basemap.
    map_path = config.SELECTION_DIR / ("route_candidates_map_%s.png" % stamp)
    draw_route_map(path, map_path, metro_timetable_path=config.TIMETABLE_DIR)
    print("wrote %s" % map_path)

    # Draw bar charts of CBD boardings and weekday trips per candidate route.
    bar_charts_path = config.SELECTION_DIR / ("route_candidates_bar_charts_%s.png" % stamp)
    draw_boardings_and_weekday_trips_bar_charts(path, bar_charts_path)
    print("wrote %s" % bar_charts_path)


if __name__ == "__main__":
    main()
