# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_check.py
# Date:         21-10-2026
# Description:  Tests for the morning check and the database backup.
# Usage:        python -m pytest tests
"""Tests for the morning check and the database backup."""

import sqlite3
from datetime import date

from data_collection_setup.backup import backup_database
from data_collection_setup.main import create_database
from gtfs_position_collection.check import summarise_day, window_bounds
from tests.test_collector import make_database, make_row
from gtfs_position_collection.main import store_positions

DAY = date(2026, 10, 7)
WINDOWS = [("07:00", "09:00"), ("12:00", "14:00")]


def test_window_bounds_are_adelaide_time():
    # 07:00 ACDT (UTC+10:30) on 7 Oct 2026 = 20:30 UTC on 6 Oct.
    assert window_bounds(DAY, "07:00", "09:00") == (1791318600, 1791325800)


def test_summary_counts_each_window_and_spots_an_empty_one(tmp_path):
    conn = make_database(tmp_path)
    morning = window_bounds(DAY, "07:00", "09:00")[0]
    store_positions(conn, [make_row("1001", morning + 60), make_row("1002", morning + 75),
                           make_row("1001", morning - 60)])  # The last one is before the window.
    morning_window, midday_window = summarise_day(conn, DAY, WINDOWS)
    assert morning_window["positions"] == 2 and morning_window["vehicles"] == 2
    assert midday_window["positions"] == 0


def test_backup_is_a_readable_copy(tmp_path):
    db_path = create_database(tmp_path / "gtfs.db")
    backup_path = backup_database(tmp_path / "backups", db_path)
    tables = sqlite3.connect(backup_path).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert ("positions",) in tables
