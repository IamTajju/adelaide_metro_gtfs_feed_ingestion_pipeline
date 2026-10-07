# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         data_collection_setup/__init__.py
# Date:         06-10-2026
# Description:  Setup stage: creates data/gtfs.db with the routes, stops, positions and arrivals tables.
# Usage:        from data_collection_setup import main
"""Setup stage: creates data/gtfs.db with the routes, stops, positions and arrivals tables."""

from data_collection_setup.main import main

__all__ = ["main"]
