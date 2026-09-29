# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         get_gtfs_positions/__init__.py
# Date:         28-09-2026
# Description:  Snapshot of the live vehicle_positions feed, flattened to rows.
# Usage:        from get_gtfs_positions import get_positions, main
"""Snapshot of the live vehicle_positions feed, flattened to rows."""

from get_gtfs_positions.main import get_positions, main

__all__ = ["get_positions", "main"]