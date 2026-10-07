# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         tests/test_arrivals.py
# Date:         29-09-2026
# Description:  Tests for picking the observed arrival from stored pings.
# Usage:        python -m pytest tests
"""Tests for picking the observed arrival from stored pings."""

import sqlite3

import pandas as pd
import pytest

from gtfs_position_collection import arrivals

STOP = ("S1", -34.9285, 138.6007)

# Latitude offsets from the stop: 0.00045 degrees is about 50 m,
# 0.0027 about 300 m, 0.0036 about 400 m and 0.006 about 667 m.
AT_STOP = STOP[1] + 0.00045
LEAVING = STOP[1] + 0.0027
APPROACHING = STOP[1] + 0.0036
OUTSIDE = STOP[1] + 0.006


def ping_frame(rows):
    return pd.DataFrame(rows, columns=[
        "trip_id", "route_id", "service_date", "lat", "lon", "timestamp"])


def test_the_closest_ping_wins():
    pings = ping_frame([
        ("T1", "G10", "2026-09-28", APPROACHING, STOP[2], 100),
        ("T1", "G10", "2026-09-28", AT_STOP, STOP[2], 130),
        ("T1", "G10", "2026-09-28", LEAVING, STOP[2], 160),
    ])
    observed = arrivals.closest_arrivals(pings, [STOP])
    assert len(observed) == 1
    assert observed.iloc[0]["timestamp"] == 130
    assert observed.iloc[0]["distance_m"] < 100


def test_a_distance_tie_takes_the_earlier_ping():
    pings = ping_frame([
        ("T1", "G10", "2026-09-28", AT_STOP, STOP[2], 200),
        ("T1", "G10", "2026-09-28", AT_STOP, STOP[2], 140),
    ])
    observed = arrivals.closest_arrivals(pings, [STOP])
    assert len(observed) == 1
    assert observed.iloc[0]["timestamp"] == 140


def test_pings_outside_the_radius_make_no_arrival():
    pings = ping_frame([
        ("T1", "G10", "2026-09-28", OUTSIDE, STOP[2], 100),
    ])
    assert arrivals.closest_arrivals(pings, [STOP]).empty


def test_service_dates_are_kept_apart():
    pings = ping_frame([
        ("T1", "G10", "2026-09-28", AT_STOP, STOP[2], 100),
        ("T1", "G10", "2026-09-29", AT_STOP, STOP[2], 86500),
    ])
    observed = arrivals.closest_arrivals(pings, [STOP])
    assert len(observed) == 2


def test_scheduled_arrival_joins_date_and_time():
    text = arrivals.scheduled_arrival("2026-09-28", "08:15:30")
    assert text == "2026-09-28 08:15:30"


def test_scheduled_arrival_with_a_missing_time():
    assert arrivals.scheduled_arrival("2026-09-28", None) is None


def test_scheduled_arrival_past_midnight():
    text = arrivals.scheduled_arrival("2026-09-28", "24:15:00")
    assert text == "2026-09-29 00:15:00"


def test_a_stop_the_trip_never_serves_is_dropped():
    observed = arrivals.closest_arrivals(ping_frame([
        ("T1", "G10", "2026-09-28", AT_STOP, STOP[2], 100),
    ]), [STOP])
    stop_times = pd.DataFrame({
        "trip_id": ["T2"], "stop_id": ["S1"], "arrival_time": ["08:15:00"]})
    assert arrivals.add_times(observed, stop_times).empty


def test_fill_arrivals_end_to_end(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    pings = pd.DataFrame({
        "entity_id": ["V1", "V1"],
        "trip_trip_id": ["T1", "T1"],
        "trip_route_id": ["G10A", "G10A"],
        "trip_start_date": ["20260928", "20260928"],
        "position_latitude": [APPROACHING, AT_STOP],
        "position_longitude": [STOP[2], STOP[2]],
        "timestamp": [1790579700, 1790579730],
    })
    pings.to_sql("positions", conn, index=False)
    stop_times = pd.DataFrame({
        "trip_id": ["T1"], "stop_id": ["S1"], "arrival_time": ["08:15:00"]})

    written = arrivals.fill_arrivals(conn, {"G10"}, [STOP], stop_times)
    assert written == 1
    row = conn.execute(
        "SELECT trip_id, stop_id, service_date, route_id, scheduled_arrival "
        "FROM arrivals").fetchone()
    assert row == ("T1", "S1", "2026-09-28", "G10", "2026-09-28 08:15:00")

    # A second run replaces the row instead of duplicating it.
    assert arrivals.fill_arrivals(conn, {"G10"}, [STOP], stop_times) == 1
    assert conn.execute("SELECT COUNT(*) FROM arrivals").fetchone()[0] == 1


def make_schedule_db(tmp_path, rows):
    """A project database whose scheduled_stop_times holds the given rows."""
    from data_collection_setup.main import create_database
    conn = sqlite3.connect(create_database(tmp_path / "gtfs.db"))
    conn.executemany(
        "INSERT INTO scheduled_stop_times (gtfs_version, route, route_id, route_short_name, "
        "service_id, trip_id, stop_id, stop_sequence, scheduled_arrival) "
        "VALUES (?, 'G10', 'G10', 'G10', 'svc', ?, ?, ?, ?)", rows)
    conn.commit()
    return conn


def test_load_stop_times_prefers_the_newest_timetable_version(tmp_path):
    conn = make_schedule_db(tmp_path, [("1704", "T1", "S1", 5, "08:10:00"),
                                       ("1705", "T1", "S1", 5, "08:12:00"),
                                       ("1704", "T0", "S1", 5, "07:00:00")])
    times = arrivals.load_stop_times(conn, [STOP]).set_index("trip_id")["arrival_time"]
    # T1 takes the newer version; T0 only exists in the older one and is kept.
    assert times.to_dict() == {"T1": "08:12:00", "T0": "07:00:00"}


def test_load_stop_times_keeps_the_first_visit_of_a_loop(tmp_path):
    conn = make_schedule_db(tmp_path, [("1705", "T1", "S1", 30, "09:00:00"),
                                       ("1705", "T1", "S1", 2, "08:00:00")])
    assert arrivals.load_stop_times(conn, [STOP])["arrival_time"].tolist() == ["08:00:00"]


def test_load_stop_times_without_a_schedule_says_what_to_run(tmp_path):
    conn = make_schedule_db(tmp_path, [])
    with pytest.raises(RuntimeError, match="make schedule"):
        arrivals.load_stop_times(conn, [STOP])
