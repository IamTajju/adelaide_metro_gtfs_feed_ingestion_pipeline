# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         gtfs_position_collection/__init__.py
# Date:         28-09-2026
# Description:  Stage 3: collects live vehicle positions into the database.
# Usage:        from gtfs_position_collection import collect_once, main
"""Stage 3: collects live vehicle positions into the database."""

from gtfs_position_collection.main import collect_once, main

__all__ = ["collect_once", "main"]