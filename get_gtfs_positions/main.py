# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         get_gtfs_positions/main.py
# Date:         28-09-2026
# Description:  Snapshot of the live vehicle_positions feed, flattened to rows.
# Usage:        python -m get_gtfs_positions
"""Snapshot of the live vehicle_positions feed, flattened to rows.

get_positions() downloads ONE snapshot of the Adelaide Metro realtime feed and
flattens every vehicle into a row, one dict per bus.  Field names come straight
from the GTFS-RT protobuf: nested messages (trip, position, vehicle) become
snake_case columns such as trip_route_id, position_latitude and vehicle_id.

Run on its own this module writes the whole snapshot to data/gtfs_positions.csv;
the gtfs_position_collection loop calls get_positions() directly for the
database.
"""

import csv
import urllib.request

import pandas as pd

from google.transit import gtfs_realtime_pb2
from shared import config


def get_positions():
    """Downloads one snapshot of the live feed and flattens every vehicle.

    Returns:
        List of dicts, one per vehicle in the feed, with snake_case keys such
        as entity_id, trip_route_id, position_latitude and vehicle_id.  The
        list is empty if the feed holds no vehicle positions.
    """
    body = urllib.request.urlopen(config.LIVE_FEED_URL, timeout=30).read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(body)

    rows = []
    for entity in feed.entity:
        # Only process vehicle-position entities.
        if not entity.HasField("vehicle"):
            continue

        vehicle = entity.vehicle
        row = {"entity_id": entity.id}

        # Add every field that actually exists in the vehicle object.
        for field, value in vehicle.ListFields():
            field_name = field.name

            # Nested GTFS-RT messages such as trip, position and vehicle
            # need to be flattened.
            if field.type == field.TYPE_MESSAGE:
                for sub_field, sub_value in value.ListFields():
                    row["%s_%s" % (field_name, sub_field.name)] = sub_value
            else:
                row[field_name] = value

        rows.append(row)

    return rows


def main():
    """Writes one snapshot of the live feed to a CSV file."""
    rows = get_positions()
    if not rows:
        raise RuntimeError("No vehicle positions were found in the feed.")

    # Collect every column appearing in any vehicle.
    fieldnames = sorted({
        key
        for row in rows
        for key in row.keys()
    })

    with open(config.POSITIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    print("Feed contains %d entities" % len(rows))
    print("Saved %d vehicles to %s" % (len(rows), config.POSITIONS_CSV))
    print("This CSV represents one snapshot of the live feed.")


if __name__ == "__main__":
    main()