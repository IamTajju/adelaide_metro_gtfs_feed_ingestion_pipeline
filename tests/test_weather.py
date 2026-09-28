# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         tests/test_weather.py
# Date:         28-09-2026
# Description:  Tests for the hourly weather storage.
# Usage:        python -m pytest tests
"""Tests for the hourly weather storage."""

import sqlite3
from datetime import date, datetime

from weather_collection.main import (LOCAL_TZ, collection_hours,
                                     rows_from_payload, store_rows)

# A small fake Open-Meteo payload, three hours of one day.
PAYLOAD = {"hourly": {
    "time": ["2026-09-28T00:00", "2026-09-28T01:00", "2026-09-28T02:00"],
    "temperature_2m": [12.1, 11.6, 11.2],
    "precipitation": [0.0, 0.2, 0.0],
    "wind_speed_10m": [10.5, 9.8, 12.0],
    "weather_code": [1, 61, 2],
}}


def test_rows_keep_every_hour_without_window():
    rows = rows_from_payload(PAYLOAD)
    assert len(rows) == 3
    assert rows[1] == ("2026-09-28T01:00", 11.6, 0.2, 9.8, 61)


def test_rows_follow_the_collection_window():
    rows = rows_from_payload(PAYLOAD, {"2026-09-28T02:00"})
    assert [row[0] for row in rows] == ["2026-09-28T02:00"]


def test_store_rows_can_run_twice(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    rows = rows_from_payload(PAYLOAD)
    assert store_rows(conn, rows) == 3
    store_rows(conn, rows)
    count = conn.execute("SELECT COUNT(*) FROM weather_hourly").fetchone()[0]
    assert count == 3


def test_collection_hours_come_from_the_pings(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    conn.execute("CREATE TABLE gtfs_positions (timestamp INTEGER)")
    stamp = datetime(2026, 9, 28, 9, 30, tzinfo=LOCAL_TZ).timestamp()
    conn.execute("INSERT INTO gtfs_positions VALUES (?)", (int(stamp),))
    conn.commit()
    assert collection_hours(conn, date(2026, 9, 28)) == {"2026-09-28T09:00"}


def test_collection_hours_without_the_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    assert collection_hours(conn, date(2026, 9, 28)) is None


def test_collection_hours_on_a_day_without_pings(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    conn.execute("CREATE TABLE gtfs_positions (timestamp INTEGER)")
    conn.commit()
    assert collection_hours(conn, date(2026, 9, 28)) is None
