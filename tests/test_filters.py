# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         tests/test_filters.py
# Date:         29-09-2026
# Description:  Tests for the route and stop relevance filters.
# Usage:        python -m pytest tests
"""Tests for the route and stop relevance filters."""

import math
import sqlite3

import pytest

from gtfs_position_collection import filters

# Victoria Square, roughly the middle of the CBD.
SQUARE = (-34.9285, 138.6007)

# 0.003 degrees of latitude is about 333 m (inside the 500 m radius) and
# 0.006 degrees is about 667 m (outside it).
NEAR = (SQUARE[0] + 0.003, SQUARE[1])
FAR = (SQUARE[0] + 0.006, SQUARE[1])

STOPS = [("S1", SQUARE[0], SQUARE[1])]


def ping(route, lat, lon):
    return {"trip_route_id": route,
            "position_latitude": lat,
            "position_longitude": lon}


def test_haversine_of_the_same_point_is_zero():
    assert filters.haversine(*SQUARE, *SQUARE) == pytest.approx(0.0)


def test_haversine_of_one_degree_of_latitude():
    metres = filters.haversine(-34.0, 138.6, -35.0, 138.6)
    assert metres == pytest.approx(111195, rel=0.01)


def test_haversine_is_symmetric():
    there = filters.haversine(*SQUARE, *NEAR)
    back = filters.haversine(*NEAR, *SQUARE)
    assert there == pytest.approx(back)


def test_nearest_stop_picks_the_closest():
    stops = STOPS + [("S2", FAR[0], FAR[1])]
    stop_id, dist = filters.nearest_stop(NEAR[0], NEAR[1], stops)
    assert stop_id == "S1"
    assert dist == pytest.approx(333, rel=0.02)


def test_nearest_stop_with_no_stops():
    stop_id, dist = filters.nearest_stop(SQUARE[0], SQUARE[1], [])
    assert stop_id is None
    assert math.isinf(dist)


def test_keeps_a_chosen_route_near_a_stop():
    rows = [ping("G10", *NEAR)]
    assert filters.keep_relevant(rows, {"G10"}, STOPS) == rows


def test_drops_a_route_that_was_not_chosen():
    rows = [ping("X99", *NEAR)]
    assert filters.keep_relevant(rows, {"G10"}, STOPS) == []


def test_drops_a_ping_outside_every_radius():
    rows = [ping("G10", *FAR)]
    assert filters.keep_relevant(rows, {"G10"}, STOPS) == []


def test_drops_a_row_without_a_position():
    rows = [{"trip_route_id": "G10"}]
    assert filters.keep_relevant(rows, {"G10"}, STOPS) == []


def test_base_route_strips_the_variant_suffix():
    assert filters.base_route("G10A") == "G10"
    assert filters.base_route("300H") == "300"
    assert filters.base_route("J1") == "J1"
    assert filters.base_route(None) is None


def test_keeps_a_variant_of_a_chosen_route():
    rows = [ping("G10A", *NEAR)]
    assert filters.keep_relevant(rows, {"G10"}, STOPS) == rows


def test_load_selection_reads_the_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    conn.execute("CREATE TABLE routes (route TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE stops (route TEXT, stop_id TEXT, "
                 "stop_lat REAL, stop_lon REAL)")
    conn.execute("INSERT INTO routes VALUES ('G10'), ('J1')")
    conn.executemany("INSERT INTO stops VALUES (?, ?, ?, ?)", [
        ("G10", "S1", -34.9285, 138.6007),
        ("J1", "S1", -34.9285, 138.6007),
        ("J1", "S2", -34.9240, 138.6010),
    ])
    conn.commit()
    route_ids, stops = filters.load_selection(conn)
    assert route_ids == {"G10", "J1"}
    assert stops == [("S1", -34.9285, 138.6007), ("S2", -34.9240, 138.6010)]
