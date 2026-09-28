# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         data_collection_setup/__init__.py
# Date:         28-09-2026
# Description:  Full static GTFS and validations load into the SQLite database.
# Usage:        from data_collection_setup import main
"""Full static GTFS and validations load into the SQLite database."""

from data_collection_setup.main import main, load_gtfs, load_validations

__all__ = [
    "main",
    "load_gtfs",
    "load_validations",
]
