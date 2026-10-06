# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/plots.py
# Date:         27-09-2026
# Description:  Route charts: candidates bar chart, route map, rank heatmap.
# Usage:        python -m select_routes.plots  (maps the latest route_candidates CSV)
"""Route charts: candidates bar chart, route map, rank heatmap.

TODO: bar chart and rank heatmap (T04, see docs/TICKETS.md).
"""

from shared.timetable import get_primary_route_shapes
from shared import config
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import contextily as ctx
import matplotlib
matplotlib.use("Agg")  # Write PNGs only; no window.


ROUTE_COLOR = "#2a78d6"  # One colour for every route.


def to_web_mercator(lat, lon):
    """Converts WGS84 degrees to Web Mercator metres (the basemap's CRS)."""
    r = 6378137.0
    x = np.radians(lon) * r
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * r
    return x, y


def get_latest_route_candidates():
    """Returns the path of the newest data/selection/route_candidates_<timestamp>.csv."""
    return max(config.SELECTION_DIR.glob("route_candidates_*.csv"))


def draw_route_map(routes_path, path, title="Candidate bus routes",
                   metro_timetable_path=config.TIMETABLE_DIR):
    """Draws the routes in a routes CSV on an Adelaide basemap, each labelled with its code.

    Args:
        routes_path: Routes CSV with a route column (base route codes).
        path: Output PNG path.
        title: Plot title.
        metro_timetable_path: Timetable folder or zip (see read_gtfs).
    """
    routes = pd.read_csv(routes_path, dtype={"route": str})
    shapes = get_primary_route_shapes(metro_timetable_path, routes.route)
    cbd_x, cbd_y = to_web_mercator((config.CBD_NORTH + config.CBD_SOUTH) / 2,
                                   (config.CBD_WEST + config.CBD_EAST) / 2)

    fig, ax = plt.subplots(figsize=(10, 12))
    for route in routes.route:
        pts = shapes[route]
        x, y = to_web_mercator(pts.shape_pt_lat.values,
                               pts.shape_pt_lon.values)
        ax.plot(x, y, color=ROUTE_COLOR, linewidth=2.5,
                solid_capstyle="round")
        # Label the route at its point furthest from the CBD.
        far = np.argmax(np.hypot(x - cbd_x, y - cbd_y))
        ax.annotate(route, (x[far], y[far]), fontsize=9, fontweight="bold",
                    color="#222222", ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))

    ax.set_aspect("equal")
    ax.margins(0.05)
    ctx.add_basemap(
        ax, source=ctx.providers.Esri.WorldGrayCanvas, crs="EPSG:3857")
    ax.set_axis_off()
    ax.set_title(title + ", Adelaide Metro")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    src = get_latest_route_candidates()
    out = src.with_name(src.name.replace(
        "route_candidates_", "route_candidates_map_").replace(".csv", ".png"))
    draw_route_map(src, out)
    print("wrote %s" % out)
