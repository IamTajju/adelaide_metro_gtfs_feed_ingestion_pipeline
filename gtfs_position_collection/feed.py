# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         gtfs_position_collection/feed.py
# Date:         07-10-2026
# Description:  Fetches the live vehicle_positions feed as rows for the positions table.
# Usage:        from gtfs_position_collection.feed import fetch_vehicle_positions
"""Fetches the live vehicle_positions feed as rows for the positions table.

Each vehicle becomes one dict whose keys are the positions columns
(entity_id, position_latitude, trip_route_id, vehicle_id, ...). A field the
feed leaves out is None, so it is stored as NULL. The base route column is
filled later by the collector, after filtering.
"""

import urllib.request

from google.transit import gtfs_realtime_pb2

from shared import config


def read_optional_field(message, field_name):
    """Returns a GTFS-realtime field's value, or None if the feed left it out."""
    return getattr(message, field_name) if message.HasField(field_name) else None


def convert_vehicle_entity_to_row(entity):
    """Flattens one vehicle entity into a positions row (without the base route).

    Args:
        entity: gtfs_realtime_pb2.FeedEntity with a vehicle field.

    Returns:
        Dict keyed by the positions columns.
    """
    vehicle = entity.vehicle
    trip, position, descriptor = vehicle.trip, vehicle.position, vehicle.vehicle
    return {
        "entity_id": entity.id,
        "position_bearing": read_optional_field(position, "bearing"),
        "position_latitude": read_optional_field(position, "latitude"),
        "position_longitude": read_optional_field(position, "longitude"),
        "position_speed": read_optional_field(position, "speed"),
        "timestamp": read_optional_field(vehicle, "timestamp"),
        "trip_direction_id": read_optional_field(trip, "direction_id"),
        "trip_route_id": read_optional_field(trip, "route_id"),
        "trip_schedule_relationship": read_optional_field(trip, "schedule_relationship"),
        "trip_start_date": read_optional_field(trip, "start_date"),
        "trip_trip_id": read_optional_field(trip, "trip_id"),
        "vehicle_id": read_optional_field(descriptor, "id"),
        "vehicle_label": read_optional_field(descriptor, "label"),
    }


def fetch_vehicle_positions(feed_url=config.LIVE_FEED_URL):
    """Downloads one snapshot of the live feed.

    Args:
        feed_url: URL of the GTFS-realtime vehicle_positions feed.

    Returns:
        Tuple (feed_timestamp, rows): the header timestamp (POSIX seconds) the
        collector uses to skip an unchanged snapshot, and one row per vehicle.
    """
    with urllib.request.urlopen(feed_url, timeout=30) as response:
        feed_message = gtfs_realtime_pb2.FeedMessage()
        feed_message.ParseFromString(response.read())
    rows = [convert_vehicle_entity_to_row(entity)
            for entity in feed_message.entity if entity.HasField("vehicle")]
    return feed_message.header.timestamp, rows
