# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         select_routes/plots.py
# Date:         27-09-2026
# Description:  Route charts: candidate bar chart, route map, rank heatmap.
# Usage:        python -m select_routes.plots  (maps the latest candidates CSV)
"""Route charts: candidate bar chart, route map, rank heatmap.

TODO: bar chart and rank heatmap (T04, see docs/TICKETS.md).
"""

from shared.timetable import get_primary_route_shapes
from shared import config
from matplotlib.colors import LinearSegmentedColormap, Normalize
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import contextily as ctx
import matplotlib
matplotlib.use("Agg")  # Write PNGs only; no window.


# Sequential blue ramp (light -> dark) for weekday trips.
TRIPS_CMAP = LinearSegmentedColormap.from_list(
    "trips", ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])


def to_web_mercator(lat, lon):
    """Converts WGS84 degrees to Web Mercator metres (the basemap's CRS)."""
    r = 6378137.0
    x = np.radians(lon) * r
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * r
    return x, y


def latest_candidates():
    """Returns the path of the newest data/selection/candidates_<timestamp>.csv."""
    return max(config.SELECTION_DIR.glob("candidates_*.csv"))


def route_map(candidates_path, path, title="Candidate bus routes by weekday trips",
              source=config.TIMETABLE_DIR):
    """Draws the routes in a candidates CSV on an Adelaide basemap, coloured by weekday trips.

    Args:
        candidates_path: Candidates CSV with columns route, weekday_trips.
        path: Output PNG path.
        title: Plot title.
        source: Timetable folder or zip (see read_gtfs).
    """
    candidates = pd.read_csv(candidates_path, dtype={"route": str})
    shapes = get_primary_route_shapes(source, candidates.route)
    norm = Normalize(candidates.weekday_trips.min(),
                     candidates.weekday_trips.max())
    cbd_x, cbd_y = to_web_mercator((config.CBD_NORTH + config.CBD_SOUTH) / 2,
                                   (config.CBD_WEST + config.CBD_EAST) / 2)

    fig, ax = plt.subplots(figsize=(10, 12))
    # Busiest last, so it is drawn on top.
    for row in candidates.sort_values("weekday_trips").itertuples():
        pts = shapes[row.route]
        x, y = to_web_mercator(pts.shape_pt_lat.values,
                               pts.shape_pt_lon.values)
        ax.plot(x, y, color=TRIPS_CMAP(norm(row.weekday_trips)), linewidth=2.5,
                solid_capstyle="round")
        # Label the route at its point furthest from the CBD.
        far = np.argmax(np.hypot(x - cbd_x, y - cbd_y))
        ax.annotate(row.route, (x[far], y[far]), fontsize=9, fontweight="bold",
                    color="#222222", ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))

    ax.set_aspect("equal")
    ax.margins(0.05)
    ctx.add_basemap(
        ax, source=ctx.providers.Esri.WorldGrayCanvas, crs="EPSG:3857")
    ax.set_axis_off()
    sm = plt.cm.ScalarMappable(cmap=TRIPS_CMAP, norm=norm)
    fig.colorbar(sm, ax=ax, shrink=0.5,
                 label="Weekday trips (busiest Wednesday, next 4 weeks)")
    ax.set_title(title + ", Adelaide Metro")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    src = latest_candidates()
    out = src.with_name(src.name.replace(
        "candidates_", "route_map_").replace(".csv", ".png"))
    route_map(src, out)
    print("wrote %s" % out)
