# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_stops/plots.py
# Date:         06-10-2026
# Description:  CBD map of the chosen stops coloured by quadrant.
# Usage:        from select_stops.plots import draw_top_stops_cbd_map
"""CBD map of the chosen stops coloured by quadrant."""

import contextily as ctx
import matplotlib
matplotlib.use("Agg")  # Write PNGs only; no window.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from shared import config
from select_routes.plots import to_web_mercator

# One colour per quadrant, in config.DIRECTIONS order (N, E, S, W).
QUADRANT_COLORS = {"N": "#2a78d6", "E": "#eb6834", "S": "#1baf7a", "W": "#eda100"}
CANDIDATE_STOP_COLOR = "#9a9a9a"


def draw_quadrant_boundaries(ax):
    """Draws the CBD box, Victoria Square and the diagonal lines between quadrants."""
    box_west_x, box_south_y = to_web_mercator(config.CBD_SOUTH, config.CBD_WEST)
    box_east_x, box_north_y = to_web_mercator(config.CBD_NORTH, config.CBD_EAST)
    ax.add_patch(plt.Rectangle((box_west_x, box_south_y), box_east_x - box_west_x,
                               box_north_y - box_south_y, fill=False,
                               edgecolor="#444444", linewidth=1.2, linestyle="--"))

    # Quadrants are 90 degree sectors centred on N/E/S/W, so they meet on the diagonals.
    square_x, square_y = to_web_mercator(config.VICTORIA_SQUARE_LAT, config.VICTORIA_SQUARE_LON)
    diagonal_reach = max(box_east_x - box_west_x, box_north_y - box_south_y)
    for diagonal_bearing in (45, 135, 225, 315):
        bearing_radians = np.radians(diagonal_bearing)
        ax.plot([square_x, square_x + diagonal_reach * np.sin(bearing_radians)],
                [square_y, square_y + diagonal_reach * np.cos(bearing_radians)],
                color="#666666", linewidth=0.8, linestyle=":")
    ax.plot(square_x, square_y, marker="*", markersize=14, color="#222222", zorder=5)
    ax.annotate("Victoria Square", (square_x, square_y), xytext=(8, -12),
                textcoords="offset points", fontsize=8, color="#222222")
    ax.set_xlim(box_west_x - 150, box_east_x + 150)
    ax.set_ylim(box_south_y - 150, box_north_y + 150)


def draw_top_stops_cbd_map(top_m_stops_path, stop_candidates_path, map_path):
    """Draws the chosen stops on a CBD basemap, coloured by quadrant, over all candidate stops.

    Each chosen stop is numbered on the map; a key beside it gives the stop code,
    quadrant and the routes that chose it.

    Args:
        top_m_stops_path: Top m stops CSV (route, stop_id, stop_name, stop_lat, stop_lon, quadrant).
        stop_candidates_path: Stop candidates CSV (stop_id, stop_lat, stop_lon), drawn in grey.
        map_path: Output PNG path.
    """
    top_stops = pd.read_csv(top_m_stops_path, dtype={"route": str, "stop_id": str})
    stop_candidates = pd.read_csv(stop_candidates_path, dtype={"stop_id": str})
    # One marker per stop; a stop chosen by several routes lists them all.
    chosen_stops = (top_stops.groupby(["stop_id", "stop_name", "stop_lat", "stop_lon", "quadrant"],
                                      as_index=False).route.agg(", ".join))
    unchosen_stops = (stop_candidates[~stop_candidates.stop_id.isin(chosen_stops.stop_id)]
                      .drop_duplicates("stop_id"))

    # Number stops by quadrant (N, E, S, W) then name, so the key reads in quadrant order.
    chosen_stops["quadrant_order"] = chosen_stops.quadrant.map(config.DIRECTIONS.index)
    chosen_stops = chosen_stops.sort_values(["quadrant_order", "stop_name"]).reset_index(drop=True)
    chosen_stops["stop_number"] = chosen_stops.index + 1

    fig, ax = plt.subplots(figsize=(14, 10))
    unchosen_x, unchosen_y = to_web_mercator(unchosen_stops.stop_lat.values,
                                             unchosen_stops.stop_lon.values)
    ax.scatter(unchosen_x, unchosen_y, s=18, color=CANDIDATE_STOP_COLOR,
               label="Other candidate stops", zorder=3)

    for quadrant in config.DIRECTIONS:
        quadrant_stops = chosen_stops[chosen_stops.quadrant == quadrant]
        stop_x, stop_y = to_web_mercator(quadrant_stops.stop_lat.values,
                                         quadrant_stops.stop_lon.values)
        ax.scatter(stop_x, stop_y, s=260, color=QUADRANT_COLORS[quadrant],
                   edgecolor="#222222", linewidth=1, zorder=4,
                   label="%s (%d %s)" % (quadrant, len(quadrant_stops),
                                         "stop" if len(quadrant_stops) == 1 else "stops"))
        for stop_number, x, y in zip(quadrant_stops.stop_number, stop_x, stop_y):
            ax.annotate(str(stop_number), (x, y), ha="center", va="center", fontsize=7,
                        fontweight="bold", color="#111111", zorder=5)

    # Key: stop number -> stop code, quadrant, routes that chose it.
    # "Stop E3 Currie St - North side" -> "E3 Currie St".
    stop_key_lines = ["%2d  %s  (%s)  %s" % (stop.stop_number, stop.stop_name.replace("Stop ", "").split(" - ")[0],
                                            stop.quadrant, stop.route)
                      for stop in chosen_stops.itertuples()]
    fig.text(0.80, 0.5, "Chosen stops (quadrant)  routes\n\n" + "\n".join(stop_key_lines),
             fontsize=8, family="monospace", va="center", ha="left", color="#222222")
    fig.subplots_adjust(right=0.78)

    draw_quadrant_boundaries(ax)
    ax.set_aspect("equal")
    ctx.add_basemap(ax, source=ctx.providers.Esri.WorldGrayCanvas, crs="EPSG:3857")
    ax.set_axis_off()
    ax.legend(loc="upper left", fontsize=8, title="Quadrant from Victoria Square",
              title_fontsize=8, framealpha=0.9)
    ax.set_title("Top %d CBD stops (top %d per route), Adelaide Metro"
                 % (chosen_stops.stop_id.nunique(), config.N_STOPS_PER_ROUTE))
    fig.savefig(map_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
