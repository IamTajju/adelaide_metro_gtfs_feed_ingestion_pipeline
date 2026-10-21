# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         tests/test_weather.py
# Date:         28-09-2026
# Description:  Tests for the hourly weather storage.
# Usage:        python -m pytest tests
"""Tests for the hourly weather storage."""

import importlib
import sqlite3
from datetime import date, datetime

from weather_collection.main import (LOCAL_TZ, collection_hours,
                                     rows_from_payload, store_rows, window_hours)

# The module itself (weather_collection.main is also the name of its main()).
weather_main = importlib.import_module("weather_collection.main")

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
    conn.execute("CREATE TABLE positions (timestamp INTEGER)")
    stamp = datetime(2026, 9, 28, 9, 30, tzinfo=LOCAL_TZ).timestamp()
    conn.execute("INSERT INTO positions VALUES (?)", (int(stamp),))
    conn.commit()
    assert collection_hours(conn, date(2026, 9, 28)) == {"2026-09-28T09:00"}


def test_collection_hours_without_the_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    assert collection_hours(conn, date(2026, 9, 28)) is None


def test_collection_hours_on_a_day_without_pings(tmp_path):
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    conn.execute("CREATE TABLE positions (timestamp INTEGER)")
    conn.commit()
    assert collection_hours(conn, date(2026, 9, 28)) is None


def test_window_hours_cover_the_hours_a_window_touches():
    assert window_hours(date(2026, 10, 7), "07:00", "09:00") == {
        "2026-10-07T07:00", "2026-10-07T08:00"}
    assert window_hours(date(2026, 10, 7), "16:15", "17:30") == {
        "2026-10-07T16:00", "2026-10-07T17:00"}


def test_window_weather_keeps_only_that_windows_hours(tmp_path, monkeypatch):
    monkeypatch.setattr(weather_main, "fetch_hourly", lambda day: PAYLOAD)
    conn = sqlite3.connect(tmp_path / "gtfs.db")
    assert weather_main.store_window_weather(conn, date(2026, 9, 28), "01:00", "02:00") == 1
    assert conn.execute("SELECT hour_local FROM weather_hourly").fetchall() == [("2026-09-28T01:00",)]
