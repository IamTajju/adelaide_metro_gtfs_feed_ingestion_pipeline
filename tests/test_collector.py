# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_collector.py
# Date:         07-10-2026
# Description:  Tests for the collector: feed rows, storing positions, collection window.
# Usage:        python -m pytest tests
"""Tests for the collector: feed rows, storing positions, collection window."""

import sqlite3
from datetime import date, datetime

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


def test_gtfs_time_past_midnight():
    assert collection_window.convert_gtfs_time_to_seconds("25:10:30") == 25 * 3600 + 630


def test_window_includes_the_tail_of_yesterday_after_midnight(monkeypatch):
    # Every service day: 06:00 to 24:30 (00:30 the next morning).
    monkeypatch.setattr(collection_window, "find_scheduled_window_seconds",
                        lambda *args: (6 * 3600, 24 * 3600 + 30 * 60))
    window = collection_window.CollectionWindow({"G10"}, {"1"}, margin_minutes=0)
    assert window.is_open(datetime(2026, 10, 7, 12, 0, tzinfo=ADELAIDE))
    assert window.is_open(datetime(2026, 10, 8, 0, 15, tzinfo=ADELAIDE))
    assert not window.is_open(datetime(2026, 10, 8, 3, 0, tzinfo=ADELAIDE))


def test_window_is_closed_on_a_day_without_chosen_trips(monkeypatch):
    monkeypatch.setattr(collection_window, "find_scheduled_window_seconds", lambda *args: None)
    window = collection_window.CollectionWindow({"G10"}, {"1"})
    assert not window.is_open(datetime(2026, 10, 7, 12, 0, tzinfo=ADELAIDE))
    assert window.describe(date(2026, 10, 7)) == "no chosen trips run"
