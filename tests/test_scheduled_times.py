# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_scheduled_times.py
# Date:         07-10-2026
# Description:  Tests for scheduled_stop_times: selection from the database and version handling.
# Usage:        python -m pytest tests
"""Tests for scheduled_stop_times: selection from the database and version handling."""

import pandas as pd
import pytest

from data_collection_setup.main import connect_to_database, create_database
from gtfs_position_collection import scheduled_times

SCHEDULE_COLUMNS = ["gtfs_version", "route", "route_id", "route_short_name", "service_id",
                    "trip_id", "direction_id", "shape_id", "stop_id", "stop_sequence",
                    "scheduled_arrival", "scheduled_departure", "arrival_seconds",
                    "departure_seconds", "pickup_type", "drop_off_type", "timepoint"]


def make_schedule(version, trip_id):
    row = dict.fromkeys(SCHEDULE_COLUMNS, "x")
    row.update(gtfs_version=version, trip_id=trip_id, stop_id="3456", stop_sequence=1,
               arrival_seconds=36000, departure_seconds=36000)
    return pd.DataFrame([row], columns=SCHEDULE_COLUMNS)


@pytest.fixture
def conn(tmp_path):
    db_path = create_database(tmp_path / "gtfs.db")
    conn = connect_to_database(db_path)
    yield conn
    conn.close()


def count_rows(conn, version):
    return conn.execute("SELECT COUNT(*) FROM scheduled_stop_times WHERE gtfs_version = ?",
                        (version,)).fetchone()[0]


def test_selection_is_read_from_the_routes_and_stops_tables(conn):
    with conn:
        conn.execute("INSERT INTO routes (route) VALUES ('G10'), ('M44')")
        conn.execute("INSERT INTO stops (route, stop_id) VALUES ('G10', '3456'), ('M44', '3456'), ('M44', '3452')")
    assert scheduled_times.load_selected_routes(conn) == {"G10", "M44"}
    assert scheduled_times.load_selected_stops(conn) == {"3456", "3452"}


def test_empty_selection_says_to_run_selection(conn):
    with pytest.raises(RuntimeError, match="make selection"):
        scheduled_times.load_selected_routes(conn)


def test_new_timetable_version_keeps_earlier_versions(conn):
    scheduled_times.replace_schedule(conn, make_schedule("1704", "old-trip"), "1704", "f", keep_other_versions=False)
    scheduled_times.replace_schedule(conn, make_schedule("1705", "new-trip"), "1705", "f", keep_other_versions=True)
    assert (count_rows(conn, "1704"), count_rows(conn, "1705")) == (1, 1)


def test_changed_selection_replaces_every_version(conn):
    scheduled_times.replace_schedule(conn, make_schedule("1704", "old-trip"), "1704", "f1", keep_other_versions=False)
    scheduled_times.replace_schedule(conn, make_schedule("1705", "new-trip"), "1705", "f2", keep_other_versions=False)
    assert (count_rows(conn, "1704"), count_rows(conn, "1705")) == (0, 1)


def test_fingerprint_changes_with_the_selection():
    base = scheduled_times.selection_fingerprint({"G10"}, {"3456"})
    assert base == scheduled_times.selection_fingerprint({"G10"}, {"3456"})
    assert base != scheduled_times.selection_fingerprint({"G10"}, {"3452"})
