# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         tests/test_delay_features.py
# Date:         03-11-2026
# Description:  Tests for building the ML training table from the A1 tables.
# Usage:        python -m pytest tests
"""Tests for building the ML training table from the A1 tables."""

import sqlite3

import pandas as pd
import pytest

from data_collection_setup.main import (ARRIVALS_DDL, POSITIONS_DDL, SCHEDULED_STOP_TIMES_DDL,
                                        STOPS_DDL)
from delay_features.main import (build_features, covered_windows, day_type, delay_class,
                                  store_features, window_of)
from weather_collection.main import WEATHER_DDL

DAY = "2026-10-28"  # A Wednesday.


def add_pings(conn, *clocks):
    """Stores one position ping at each local "HH:MM" on DAY."""
    for clock in clocks:
        stamp = int(pd.Timestamp(DAY + " " + clock, tz="Australia/Adelaide").timestamp())
        conn.execute("INSERT INTO positions (vehicle_id, timestamp) VALUES ('v1', ?)", (stamp,))


def test_delay_class_bands():
    assert delay_class(-1.5) == "early"
    assert delay_class(-1.0) == "on_time"
    assert delay_class(5.0) == "on_time"
    assert delay_class(5.5) == "late"


def test_window_of_scheduled_time():
    windows = [("07:00", "09:00"), ("12:00", "14:00"), ("16:00", "18:00")]
    names = ["am", "midday", "pm"]
    assert window_of(DAY + " 08:15:00", windows, names, 10) == "am"
    assert window_of(DAY + " 12:10:00", windows, names, 10) == "midday"
    assert window_of(DAY + " 17:50:00", windows, names, 10) == "pm"
    # Within the margin of an edge, or outside every window: no window.
    assert window_of(DAY + " 07:05:00", windows, names, 10) is None
    assert window_of(DAY + " 08:55:00", windows, names, 10) is None
    assert window_of(DAY + " 10:30:00", windows, names, 10) is None


def test_day_type():
    assert day_type("2026-10-30") == "weekday"  # Friday
    assert day_type("2026-10-31") == "weekend"  # Saturday
    assert day_type("2026-11-01") == "weekend"  # Sunday


def make_db():
    conn = sqlite3.connect(":memory:")
    for ddl in (ARRIVALS_DDL, POSITIONS_DDL, SCHEDULED_STOP_TIMES_DDL, STOPS_DDL, WEATHER_DDL):
        conn.execute(ddl)
    add_pings(conn, "06:59", "08:59")  # The 07-09 window was collected in full.
    conn.executemany(
        "INSERT INTO stops (route, stop_id, quadrant) VALUES (?, ?, ?)",
        [("G10", "S1", "N"), ("G10", "S2", "S")])
    # Trips T1, T2 and T5 on service WK, 10 min apart, each serving S1 then
    # S2; T6 serves S1 at 08:55, inside the edge margin of the 07-09 window.
    # T3 belongs to a service that did not run that day.
    schedule = [("T1", "WK", "S1", 1, 8 * 3600), ("T1", "WK", "S2", 2, 8 * 3600 + 300),
                ("T2", "WK", "S1", 1, 8 * 3600 + 600), ("T2", "WK", "S2", 2, 8 * 3600 + 900),
                ("T5", "WK", "S1", 1, 8 * 3600 + 1200), ("T5", "WK", "S2", 2, 8 * 3600 + 1500),
                ("T6", "WK", "S1", 1, 8 * 3600 + 3300),
                ("T3", "SAT", "S1", 1, 8 * 3600 + 120)]
    conn.executemany(
        "INSERT INTO scheduled_stop_times (gtfs_version, route, route_id, "
        "route_short_name, service_id, trip_id, direction_id, stop_id, "
        "stop_sequence, arrival_seconds) VALUES ('1700', 'G10', 'G10', 'G10', "
        "?, ?, '0', ?, ?, ?)",
        [(service, trip, stop, seq, secs) for trip, service, stop, seq, secs in schedule])
    conn.executemany(
        "INSERT INTO arrivals VALUES (?, ?, ?, 'G10', ?, ?, ?)",
        [("T1", "S1", DAY, DAY + " 08:02:00", DAY + " 08:00:00", 40.0),
         ("T1", "S2", DAY, DAY + " 08:12:00", DAY + " 08:05:00", 60.0),
         ("T2", "S1", DAY, DAY + " 08:08:00", DAY + " 08:10:00", 30.0),
         ("T2", "S2", DAY, DAY + " 08:15:00", DAY + " 08:15:00", 450.0),
         ("T4", "S1", DAY, DAY + " 08:20:00", None, 20.0),
         ("T5", "S1", DAY, DAY + " 08:23:00", DAY + " 08:20:00", 300.0),
         ("T5", "S2", DAY, DAY + " 08:29:00", DAY + " 08:25:00", 50.0),
         ("T6", "S1", DAY, DAY + " 08:56:00", DAY + " 08:55:00", 20.0)])
    conn.execute("INSERT INTO weather_hourly VALUES (?, 20.0, 1.2, 10.0, 61)",
                 (DAY + "T08:00",))
    return conn


def test_build_features_end_to_end():
    conn = make_db()
    rows, dropped = build_features(conn)
    rows = rows.set_index(["trip_id", "stop_id"])

    # T4 has no scheduled time, T2 at S2 and T5 at S1 had their closest ping
    # too far out, T6 is scheduled near the window edge. Each drop is counted
    # once, so the counts and the kept rows add up to all 8 arrivals.
    assert len(rows) == 4
    assert dropped["no scheduled time"] == 1
    assert dropped["closest ping too far"] == 2
    assert dropped["scheduled near a window edge"] == 1
    assert sum(dropped.values()) + len(rows) == 8

    t1_s1, t1_s2, t2_s1 = rows.loc[("T1", "S1")], rows.loc[("T1", "S2")], rows.loc[("T2", "S1")]
    assert t1_s1["delay_min"] == 2.0 and t1_s1["delay_class"] == "on_time"
    assert t1_s2["delay_min"] == 7.0 and t1_s2["delay_class"] == "late"
    assert t2_s1["delay_class"] == "early"

    # Previous chosen stop of the same trip, and the flag at the first stop.
    assert t1_s1["has_prev_stop"] == 0 and t1_s1["prev_stop_delay_min"] == 0.0
    assert t1_s2["has_prev_stop"] == 1 and t1_s2["prev_stop_delay_min"] == 2.0
    # T5 at S1 is dropped for its far ping, but is still S2's previous stop.
    t5_s2 = rows.loc[("T5", "S2")]
    assert t5_s2["has_prev_stop"] == 1 and t5_s2["prev_stop_delay_min"] == 3.0
    assert t5_s2["prev_stop_observed"] == DAY + " 08:23:00"
    assert pd.isna(t1_s1["prev_stop_observed"])

    # T3's service did not run, so T1 and T2 are 10 min apart at S1.
    assert t1_s1["headway_min"] == 10.0 and t2_s1["headway_min"] == 10.0

    assert t1_s1["quadrant"] == "N" and t1_s2["quadrant"] == "S"
    assert t1_s1["window"] == "am" and t1_s1["day_type"] == "weekday"
    assert t1_s1["precipitation_mm"] == pytest.approx(1.2)


def test_headway_ignores_superseded_timetable_versions():
    # An older version reuses service WK with a renumbered trip one minute
    # after T1. Mixing versions would give T1 a fake 1 min headway.
    conn = make_db()
    conn.executemany(
        "INSERT INTO scheduled_stop_times (gtfs_version, route, route_id, "
        "route_short_name, service_id, trip_id, direction_id, stop_id, "
        "stop_sequence, arrival_seconds) VALUES ('1690', 'G10', 'G10', 'G10', "
        "'WK', 'OLD1', '0', ?, ?, ?)",
        [("S1", 1, 8 * 3600 + 60), ("S2", 2, 8 * 3600 + 360)])
    rows, dropped = build_features(conn)
    rows = rows.set_index(["trip_id", "stop_id"])
    assert rows.loc[("T1", "S1"), "headway_min"] == 10.0
    assert rows.loc[("T1", "S2"), "headway_min"] == 10.0
    assert dropped["no headway"] == 0


def test_covered_windows_needs_pings_at_both_ends():
    conn = make_db()
    assert covered_windows(conn) == {(DAY, "am")}
    conn.execute("DELETE FROM positions")
    add_pings(conn, "06:59", "08:00")  # Collection stopped an hour early.
    assert covered_windows(conn) == set()


def test_rows_in_a_half_collected_window_are_dropped():
    conn = make_db()
    conn.execute("DELETE FROM positions")
    add_pings(conn, "06:59", "08:00")
    rows, dropped = build_features(conn)
    assert rows.empty
    assert dropped["window not fully collected"] == 4
    assert sum(dropped.values()) == 8


def test_store_features_replaces_the_table():
    conn = make_db()
    rows, _ = build_features(conn)
    store_features(conn, rows)
    assert store_features(conn, rows) == 4
    assert conn.execute("SELECT COUNT(*) FROM delay_features").fetchone()[0] == 4


def test_missing_weather_table_says_what_to_run():
    conn = make_db()
    conn.execute("DROP TABLE weather_hourly")
    with pytest.raises(RuntimeError, match="make weather"):
        build_features(conn)
