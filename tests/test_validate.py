# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         tests/test_validate.py
# Date:         26-09-2026
# Description:  Tests for the real-time rejection rules.
# Usage:        python -m pytest tests/test_validate.py -v
"""Tests for the real-time rejection rules (gtfs_position_collection.validate).

TODO: T07 (see docs/TICKETS.md).
"""


import sqlite3

import pytest

from gtfs_position_collection.validate import (
    MISSING_REQUIRED_FIELDS,
    POSITION_OUTSIDE_SA,
    STALE_TIMESTAMP,
    TRIP_NOT_FOUND,
    validate_position,
    validate_or_quarantine
)

# Standardised time used for the time-based validation tests
TEST_NOW = 1_800_000_000


@pytest.fixture
def db():
    """Creates an in-memory database for validator tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript(
        """
        CREATE TABLE scheduled_stop_times (
            gtfs_version TEXT NOT NULL,
            trip_id TEXT NOT NULL,
            stop_id TEXT NULL,
            stop_sequence INTEGER NOT NULL
        );

        CREATE TABLE quarantine (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            quarantined_at INTEGER NOT NULL,

            entity_id TEXT,
            vehicle_id TEXT,
            trip_id TEXT,
            route_id TEXT,

            timestamp INTEGER,
            latitude REAL,
            longitude REAL,

            reason TEXT NOT NULL,
            details TEXT,
            raw_record TEXT NOT NULL
        );
        """
    )

    conn.execute(
        """
        INSERT INTO scheduled_stop_times (
            gtfs_version,
            trip_id,
            stop_id,
            stop_sequence
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            "test-version",
            1134966,
            None,
            1,
        ),
    )

    conn.commit()

    yield conn

    conn.close()


@pytest.fixture
def valid_record():
    """Returns a vehicle position that should pass every validation rule."""
    return {
        "entity_id": "1",
        "vehicle_id": "1",
        "trip_id": "1134966",
        "route_id": "G10",

        # 30 seconds old.
        "timestamp": TEST_NOW - 30,

        # Adelaide.
        "latitude": -34.9285,
        "longitude": 138.6007,
    }


def test_required_fields_reject_missing_trip_id(db, valid_record):
    """T07 rule: required fields must be present."""
    record = valid_record.copy()
    del record["trip_id"]

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == MISSING_REQUIRED_FIELDS
    assert "trip_id" in result.details


def test_position_rejects_coordinates_outside_sa(db, valid_record):
    """T07 rule: position must lie inside South Australia."""
    record = valid_record.copy()

    # Coordinates outside SA.
    record["latitude"] = -33.8688
    record["longitude"] = 151.2093

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == POSITION_OUTSIDE_SA


def test_timestamp_rejects_stale_position(db, valid_record):
    """T07 rule: vehicle timestamp must be fresh."""
    record = valid_record.copy()

    # Deliberately far beyond the permitted freshness threshold.
    record["timestamp"] = TEST_NOW - 300

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == STALE_TIMESTAMP


def test_trip_must_exist_in_static_schedule(db, valid_record):
    """T07 rule: realtime trip must exist in scheduled_stop_times."""
    record = valid_record.copy()
    record["trip_id"] = "not-a-real-trip"

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == TRIP_NOT_FOUND


def test_valid_position_passes_all_rules(db, valid_record):
    """A valid realtime position should pass the rejection layer."""
    result = validate_position(
        valid_record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is True
    assert result.reason is None
    assert result.details is None

def test_invalid_position_is_written_to_quarantine(db, valid_record):
    """Rejected records should be stored with their rejection reason."""
    record = valid_record.copy()

    record["latitude"] = 0.0
    record["longitude"] = 0.0

    accepted = validate_or_quarantine(
        record,
        db,
        now=TEST_NOW,
    )

    db.commit()

    assert accepted is False

    row = db.execute(
        """
        SELECT reason, trip_id, raw_record
        FROM quarantine
        """
    ).fetchone()

    assert row is not None
    assert row["reason"] == POSITION_OUTSIDE_SA
    assert row["trip_id"] == "1134966"
    assert '"trip_id": "1134966"' in row["raw_record"]