# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         config.py
# Date:         26-09-2026
# Description:  All URLs, paths, timers, CBD box and selection sizes.
# Usage:        imported by other modules
"""All URLs, paths, timers, CBD box and selection sizes.

TODO: rest of T01 (see docs/TICKETS.md).
"""

from pathlib import Path

# Paths
DATA_DIR = Path(__file__).parent / "data"
TIMETABLE_DIR = DATA_DIR / "timetable"
VALIDATIONS_DIR = DATA_DIR / "validations"
SELECTION_DIR = DATA_DIR / "selection"

# Static GTFS: Adelaide Metro timetables and stop/route data.
GTFS_BASE = "https://gtfs.adelaidemetro.com.au/v1"
GTFS_STATIC = GTFS_BASE + "/static/latest/google_transit.zip"
GTFS_VERSION = GTFS_BASE + "/static/latest/version.txt"

# Demand data: Adelaide Metro banded Metrocard validations (data.sa.gov.au).
VALIDATIONS_API = ("https://data.sa.gov.au/data/api/3/action/package_show"
                   "?id=adelaide-metrocard-validations")
BUS_MODE = "1"  # NUM_MODE_TRANSPORT: 1=Bus, 4=Tram, 5=Train (dataset metadata).

# Adelaide CBD: the box inside North, South, West and East Terraces.
CBD_NORTH = -34.9205
CBD_SOUTH = -34.9357
CBD_WEST = 138.5873
CBD_EAST = 138.6104

# GTFS constants
BUS_ROUTE_TYPE = "3"  # route_type for bus in GTFS (3=bus, 4=tram, 5=train, etc.)

# Route selection
N_CANDIDATES = 15  # Top routes by CBD boardings, ranked further in T04.
