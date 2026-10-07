# Student Name: Joel Bates
# Student FAN:  BATE0218
# File:         tests/test_validate.py
# Date:         07-10-2026
# Description:  Tests for GTFS vehicle-position validation and quarantine.
# Usage:        python -m pytest tests/test_validate.py -v

"""Tests for collection layer (gtfs_position_collection.validate)."""

import json
import sqlite3

import pytest

from gtfs_position_collection.validate import (
    FUTURE_TIMESTAMP,
    MISSING_REQUIRED_FIELDS,
    POSITION_OUTSIDE_SA,
    STALE_TIMESTAMP,
    TRIP_NOT_FOUND,
    validate_position,
    validate_positions,
)

# Arbitrary standardised timestamp for time-based tests
TEST_NOW = 1_800_000_000


@pytest.fixture
def db():
    """Creates an in-memory database for validator tests.

    The database contains:
      - one known scheduled GTFS trip;
      - an empty quarantine table.
    """
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
            "known-trip",
            "stop-1",
            1,
        ),
    )

    conn.commit()

    yield conn

    conn.close()


@pytest.fixture
def valid_record():
    """Returns a flattened feed row that should pass all rules.

    Field names match the flattened rows passed from feed.py into
    filters.keep_relevant() and then validate.validate_positions().
    """
    return {
        "entity_id": "entity-1",
        "vehicle_id": "vehicle-1",

        "trip_trip_id": "known-trip",
        "trip_route_id": "G10",

        # Thirty seconds old: comfortably inside the freshness limit.
        "timestamp": TEST_NOW - 30,

        # Adelaide CBD.
        "position_latitude": -34.9285,
        "position_longitude": 138.6007,
    }


def test_required_fields_reject_missing_trip_id(db, valid_record):
    """A missing required field must reject the row."""
    record = valid_record.copy()
    del record["trip_trip_id"]

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == MISSING_REQUIRED_FIELDS
    assert "trip_id" in result.details


def test_position_rejects_coordinates_outside_sa(db, valid_record):
    """A vehicle position outside SA must be rejected."""
    record = valid_record.copy()

    # Sydney.
    record["position_latitude"] = -33.8688
    record["position_longitude"] = 151.2093

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == POSITION_OUTSIDE_SA


def test_timestamp_rejects_stale_position(db, valid_record):
    """A stale vehicle observation must be rejected."""
    record = valid_record.copy()

    # Five minutes old.
    record["timestamp"] = TEST_NOW - 300

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == STALE_TIMESTAMP


def test_trip_must_exist_in_static_schedule(db, valid_record):
    """trip_id must exist in scheduled_stop_times."""
    record = valid_record.copy()
    record["trip_trip_id"] = "unknown-trip"

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == TRIP_NOT_FOUND


def test_valid_position_passes_all_rules(db, valid_record):
    """A correct relevant vehicle row should pass validation."""
    result = validate_position(
        valid_record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is True
    assert result.reason is None
    assert result.details is None


def test_invalid_position_is_written_to_quarantine(db, valid_record):
    """validate_positions() should quarantine invalid rows."""
    record = valid_record.copy()

    record["position_latitude"] = 0.0
    record["position_longitude"] = 0.0

    valid_rows, quarantined = validate_positions(
        [record],
        db,
        now=TEST_NOW,
    )

    assert valid_rows == []
    assert quarantined == 1

    row = db.execute(
        """
        SELECT
            reason,
            trip_id,
            route_id,
            latitude,
            longitude,
            raw_record
        FROM quarantine
        """
    ).fetchone()

    assert row is not None

    assert row["reason"] == POSITION_OUTSIDE_SA
    assert row["trip_id"] == "known-trip"
    assert row["route_id"] == "G10"
    assert row["latitude"] == 0.0
    assert row["longitude"] == 0.0

    raw_record = json.loads(row["raw_record"])

    assert raw_record["trip_trip_id"] == "known-trip"
    assert raw_record["trip_route_id"] == "G10"


def test_validate_positions_returns_valid_rows(db, valid_record):
    """validate_positions() should return rows that pass validation."""
    valid_rows, quarantined = validate_positions(
        [valid_record],
        db,
        now=TEST_NOW,
    )

    assert quarantined == 0
    assert len(valid_rows) == 1
    assert valid_rows[0] == valid_record

    quarantine_count = db.execute(
        "SELECT COUNT(*) FROM quarantine"
    ).fetchone()[0]

    assert quarantine_count == 0


def test_validate_positions_handles_mixed_batch(db, valid_record):
    """A batch may contain both accepted and quarantined records."""
    good = valid_record.copy()

    bad = valid_record.copy()
    bad["entity_id"] = "entity-2"
    bad["vehicle_id"] = "vehicle-2"
    bad["trip_trip_id"] = "unknown-trip"

    valid_rows, quarantined = validate_positions(
        [good, bad],
        db,
        now=TEST_NOW,
    )

    assert len(valid_rows) == 1
    assert valid_rows[0]["entity_id"] == "entity-1"

    assert quarantined == 1

    quarantine_row = db.execute(
        """
        SELECT reason, trip_id
        FROM quarantine
        """
    ).fetchone()

    assert quarantine_row["reason"] == TRIP_NOT_FOUND
    assert quarantine_row["trip_id"] == "unknown-trip"


def test_future_timestamp_beyond_tolerance_is_rejected(
    db,
    valid_record,
):
    """A timestamp too far ahead of our clock should be rejected."""
    record = valid_record.copy()

    # Deliberately well beyond the configured future-clock tolerance.
    record["timestamp"] = TEST_NOW + 300

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is False
    assert result.reason == FUTURE_TIMESTAMP


def test_simple_field_aliases_are_also_supported(db):
    """Validator should also accept the non-flattened field aliases."""
    record = {
        "entity_id": "entity-simple",
        "vehicle_id": "vehicle-simple",
        "trip_id": "known-trip",
        "route_id": "G10",
        "timestamp": TEST_NOW - 30,
        "latitude": -34.9285,
        "longitude": 138.6007,
    }

    result = validate_position(
        record,
        db,
        now=TEST_NOW,
    )

    assert result.valid is True