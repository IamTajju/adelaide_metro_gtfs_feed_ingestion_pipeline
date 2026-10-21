# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_collector.py
# Date:         07-10-2026
# Description:  Tests for the collector: feed rows, storing positions, collection window.
# Usage:        python -m pytest tests
"""Tests for the collector: feed rows, storing positions, collection window."""

import sqlite3
from datetime import datetime

from google.transit import gtfs_realtime_pb2

from data_collection_setup.main import create_database
from gtfs_position_collection import collection_window
from gtfs_position_collection.main import store_positions
from gtfs_position_collection.feed import convert_vehicle_entity_to_row

ADELAIDE = collection_window.ADELAIDE_TZ


def make_row(vehicle_id, timestamp, trip_route_id="G10A"):
    """A filtered feed row as the collector stores it."""
    return {"entity_id": "e" + vehicle_id, "position_bearing": 90.0,
            "position_latitude": -34.92, "position_longitude": 138.60,
            "position_speed": 5.0, "timestamp": timestamp, "trip_direction_id": 0,
            "trip_route_id": trip_route_id, "trip_schedule_relationship": 0,
            "trip_start_date": "20261007", "trip_trip_id": "t1",
            "vehicle_id": vehicle_id, "vehicle_label": vehicle_id}


def make_database(tmp_path):
    db_path = create_database(tmp_path / "gtfs.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO routes (route, gtfs_route_ids) VALUES ('G10', 'G10 G10A')")
    conn.commit()
    return conn


def test_feed_entity_becomes_a_positions_row():
    entity = gtfs_realtime_pb2.FeedEntity(id="V1")
    entity.vehicle.trip.route_id = "G10A"
    entity.vehicle.trip.trip_id = "t1"
    entity.vehicle.position.latitude = -34.92
    entity.vehicle.position.longitude = 138.6
    entity.vehicle.timestamp = 100
    entity.vehicle.vehicle.id = "1001"
    row = convert_vehicle_entity_to_row(entity)
    assert row["trip_route_id"] == "G10A" and row["vehicle_id"] == "1001"
    assert row["timestamp"] == 100
    # Fields the feed left out are stored as NULL, not as protobuf defaults.
    assert row["position_speed"] is None and row["trip_direction_id"] is None


def test_store_positions_fills_the_base_route(tmp_path):
    conn = make_database(tmp_path)
    assert store_positions(conn, [make_row("1001", 100)]) == 1
    assert conn.execute("SELECT route, trip_route_id FROM positions").fetchone() == ("G10", "G10A")


def test_store_positions_ignores_a_report_already_stored(tmp_path):
    conn = make_database(tmp_path)
    store_positions(conn, [make_row("1001", 100)])
    assert store_positions(conn, [make_row("1001", 100), make_row("1001", 115)]) == 1
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 2


WINDOWS = [("07:00", "09:00"), ("12:00", "14:00"), ("16:00", "18:00")]


def test_clock_time_to_seconds():
    assert collection_window.convert_clock_time_to_seconds("16:30") == 16 * 3600 + 1800


def test_window_is_open_only_inside_the_three_windows():
    window = collection_window.CollectionWindow(WINDOWS)
    assert window.is_open(datetime(2026, 10, 7, 7, 0, tzinfo=ADELAIDE))
    assert window.is_open(datetime(2026, 10, 7, 13, 30, tzinfo=ADELAIDE))
    assert window.is_open(datetime(2026, 10, 7, 17, 59, tzinfo=ADELAIDE))
    assert not window.is_open(datetime(2026, 10, 7, 9, 0, tzinfo=ADELAIDE))
    assert not window.is_open(datetime(2026, 10, 7, 15, 0, tzinfo=ADELAIDE))
    assert not window.is_open(datetime(2026, 10, 7, 23, 0, tzinfo=ADELAIDE))


def test_seconds_until_the_next_window_opens():
    window = collection_window.CollectionWindow(WINDOWS)
    assert window.seconds_until_open(datetime(2026, 10, 7, 8, 0, tzinfo=ADELAIDE)) == 0
    assert window.seconds_until_open(datetime(2026, 10, 7, 11, 30, tzinfo=ADELAIDE)) == 1800
    # After the last window: tomorrow's first one.
    assert window.seconds_until_open(datetime(2026, 10, 7, 19, 0, tzinfo=ADELAIDE)) == 12 * 3600
    assert window.describe() == "07:00-09:00, 12:00-14:00, 16:00-18:00"


def test_open_window_names_the_window():
    window = collection_window.CollectionWindow(WINDOWS)
    assert window.open_window(datetime(2026, 10, 7, 12, 30, tzinfo=ADELAIDE)) == ("12:00", "14:00")
    assert window.open_window(datetime(2026, 10, 7, 14, 0, tzinfo=ADELAIDE)) is None
