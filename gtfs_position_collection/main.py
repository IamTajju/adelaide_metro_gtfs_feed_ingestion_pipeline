# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         gtfs_position_collection/main.py
# Date:         27-09-2026
# Description:  Polling loop: fetch vehicle positions, filter, validate, store.
# Usage:        python -m gtfs_position_collection
"""Polling loop: fetch vehicle positions, filter, validate, store.

TODO: T08 (see docs/TICKETS.md).
"""
from gtfs_position_collection.scheduled_times import (
    ensure_scheduled_stop_times,
)

def main():
    """Driver for this stage."""
    #raise NotImplementedError("see TODO above")

    """Runs the realtime GTFS vehicle-position collector."""

    schedule_info = ensure_scheduled_stop_times()

    print(
        "Static schedule ready: "
        f"{schedule_info['rows']:,} rows, "
        f"GTFS version {schedule_info['gtfs_version']}"
    )

if __name__ == "__main__":
    main()
