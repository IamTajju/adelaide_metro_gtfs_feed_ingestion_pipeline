# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         shared/config.py
# Date:         26-09-2026
# Description:  All URLs, paths, timers, CBD box and selection sizes.
# Usage:        from shared import config
"""All URLs, paths, timers, CBD box and selection sizes.

TODO: rest of T01 (see docs/TICKETS.md).
"""

from pathlib import Path

# Paths
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "gtfs.db"  # The one SQLite database every stage shares.
TIMETABLE_DIR = DATA_DIR / "timetable"
METRO_TAPS_DIR = DATA_DIR / "validations"
SELECTION_DIR = DATA_DIR / "selection"
LOG_DIR = DATA_DIR / "logs"

# Static GTFS: Adelaide Metro timetables and stop/route data.
GTFS_BASE = "https://gtfs.adelaidemetro.com.au/v1"
GTFS_STATIC = GTFS_BASE + "/static/latest/google_transit.zip"
GTFS_VERSION = GTFS_BASE + "/static/latest/version.txt"

# Real-time vehicle positions. The feed header timestamp moves every 15 s
# (measured 07-10-2026), so polling faster only re-reads the same snapshot.
LIVE_FEED_URL = GTFS_BASE + "/realtime/vehicle_positions"
LIVE_POLL_SECONDS = 15
# Collect from the first to the last scheduled bus at the chosen stops, widened
# by this margin so early and late buses near the stops are still recorded.
COLLECTION_MARGIN_MINUTES = 30
# While outside the collection window, check again this often.
OUTSIDE_WINDOW_CHECK_SECONDS = 300

# Demand data: Adelaide Metro banded Metrocard validations (data.sa.gov.au).
VALIDATIONS_API = ("https://data.sa.gov.au/data/api/3/action/package_show"
                   "?id=adelaide-metrocard-validations")
# NUM_MODE_TRANSPORT: 1=Bus, 4=Tram, 5=Train (dataset metadata).
BUS_MODE = "1"

# Adelaide CBD: the box inside North, South, West and East Terraces.
CBD_NORTH = -34.9205
CBD_SOUTH = -34.9357
CBD_WEST = 138.5873
CBD_EAST = 138.6104
# Victoria Square: centre for route directions (N/E/S/W).
VICTORIA_SQUARE_LAT = -34.9285
VICTORIA_SQUARE_LON = 138.6007

# GTFS constants
# route_type for bus in GTFS (3=bus, 4=tram, 5=train, etc.)
BUS_ROUTE_TYPE = "3"
SERVICE_RUNS = "1"  # calendar.txt weekday column: service runs that weekday.
# calendar_dates.txt exception_type: service added on the date.
SERVICE_ADDED = "1"
# calendar_dates.txt exception_type: service removed on the date.
SERVICE_REMOVED = "2"

# Route selection
N_CANDIDATES = 15  # Route candidates: top routes by CBD boardings, narrowed to K_ROUTES by the selection.
# Weekday trips = busiest Wednesday in this many weeks.
WEEKDAY_WINDOW_WEEKS = 4
K_ROUTES = 5  # Routes kept by the selection.
# Weighted rank: demand leads, frequency breaks near-ties (weights sum to 1).
WEIGHT_BOARDINGS = 0.6
WEIGHT_TRIPS = 0.4
# Each needs at least one chosen route (needs K_ROUTES >= 4).
DIRECTIONS = "NESW"

# Stop selection
N_STOPS_PER_ROUTE = 3  # Top stops per chosen route by boardings on that route.
