# Student Name: [Your Name]
# Student FAN:  [YourFAN]
# File:         gtfs_position_collection/validate.py
# Date:         27-09-2026
# Description:  Real-time rejection layer: row checks before storing.
# Usage:        from gtfs_position_collection.validate import ...
"""Real-time rejection and quarantine layer for vehicle positions: row checks before storing.

TODO: T07 (see docs/TICKETS.md).
"""

import json
import time
from dataclasses import dataclass

from shared import config


# Validation failure reasons
MISSING_REQUIRED_FIELDS = "missing_required_fields"
POSITION_OUTSIDE_SA = "position_outside_sa"
STALE_TIMESTAMP = "stale_timestamp"
FUTURE_TIMESTAMP = "future_timestamp"
TRIP_NOT_FOUND = "trip_not_found"


@dataclass(frozen=True)
class ValidationResult:
    """Result returned by the vehicle-position validator.

    Attributes:
        valid: True when the record passed every validation rule.
        reason: Machine-readable rejection reason, or None for a valid row.
        details: Human-readable explanation, or None for a valid row.
    """

    valid: bool
    reason: str | None = None
    details: str | None = None


def _is_missing(value):
    """Returns True when a required value is absent.

    Zero is not considered missing because latitude, longitude and timestamps
    are numeric fields where zero may still need to reach later validation.
    """
    if value is None:
        return True

    if isinstance(value, str) and not value.strip():
        return True

    return False


def validate_required_fields(record):
    """Checks fields required for the prediction pipeline.

    GTFS-Realtime permits some of these fields to be optional, but this
    ingestion system requires them because an accurate delay observation cannot be
    associated with a scheduled trip without trip_id, timestamp and position.

    Args:
        record: vehicle-position dictionary.

    Returns:
        ValidationResult.
    """
    required_fields = (
        "trip_id",
        "timestamp",
        "latitude",
        "longitude",
    )

    missing = [
        field
        for field in required_fields
        if field not in record or _is_missing(record[field])
    ]

    if missing:
        return ValidationResult(
            valid=False,
            reason=MISSING_REQUIRED_FIELDS,
            details="Missing required field(s): " + ", ".join(missing),
        )

    return ValidationResult(valid=True)


def validate_position_inside_sa(record):
    """Checks whether latitude/longitude lie within the coarse SA bounding box.


    Args:
        record: vehicle-position dictionary.

    Returns:
        ValidationResult.
    """
    try:
        latitude = float(record["latitude"])
        longitude = float(record["longitude"])
    except (TypeError, ValueError):
        return ValidationResult(
            valid=False,
            reason=POSITION_OUTSIDE_SA,
            details=(
                "Latitude and longitude must be numeric: "
                f"latitude={record.get('latitude')!r}, "
                f"longitude={record.get('longitude')!r}"
            ),
        )

    inside = (
        config.SA_LAT_MIN <= latitude <= config.SA_LAT_MAX
        and config.SA_LON_MIN <= longitude <= config.SA_LON_MAX
    )

    if not inside:
        return ValidationResult(
            valid=False,
            reason=POSITION_OUTSIDE_SA,
            details=(
                "Position outside South Australia bounds: "
                f"latitude={latitude}, longitude={longitude}"
            ),
        )

    return ValidationResult(valid=True)


def validate_timestamp_fresh(record, now=None):
    """Checks whether the vehicle-position timestamp is sufficiently fresh.

    GTFS-Realtime VehiclePosition timestamps are POSIX/Unix timestamps in UTC.
    No Adelaide timezone conversion is required because both values represent
    seconds since the Unix epoch.

    Args:
        record: vehicle-position dictionary.
        now: Optional Unix timestamp. Used by tests to make them deterministic.

    Returns:
        ValidationResult.
    """
    if now is None:
        now = time.time()

    try:
        timestamp = int(record["timestamp"])
    except (TypeError, ValueError):
        return ValidationResult(
            valid=False,
            reason=STALE_TIMESTAMP,
            details=f"Invalid timestamp: {record.get('timestamp')!r}",
        )

    age = float(now) - timestamp

    if age > config.POSITION_MAX_AGE_SECONDS:
        return ValidationResult(
            valid=False,
            reason=STALE_TIMESTAMP,
            details=(
                f"Vehicle position is {age:.1f} seconds old; "
                f"maximum allowed age is "
                f"{config.POSITION_MAX_AGE_SECONDS} seconds"
            ),
        )

    # Negative age means the source timestamp is ahead of our system clock.
    if age < -config.POSITION_FUTURE_TOLERANCE_SECONDS:
        return ValidationResult(
            valid=False,
            reason=FUTURE_TIMESTAMP,
            details=(
                f"Vehicle timestamp is {-age:.1f} seconds in the future; "
                f"maximum clock-skew allowance is "
                f"{config.POSITION_FUTURE_TOLERANCE_SECONDS} seconds"
            ),
        )

    return ValidationResult(valid=True)


def validate_trip_exists(record, conn):
    """Checks that trip_id exists in the current scheduled timetable.

    scheduled_stop_times is replaced when the static GTFS version changes,
    so the table represents the current selected timetable.

    Args:
        record: vehicle-position dictionary.
        conn: Open SQLite connection.

    Returns:
        ValidationResult.
    """
    trip_id = str(record["trip_id"])

    exists = conn.execute(
        """
        SELECT 1
        FROM scheduled_stop_times
        WHERE trip_id = ?
        LIMIT 1
        """,
        (trip_id,),
    ).fetchone()

    if exists is None:
        return ValidationResult(
            valid=False,
            reason=TRIP_NOT_FOUND,
            details=(
                f"trip_id {trip_id!r} is not present in "
                "scheduled_stop_times"
            ),
        )

    return ValidationResult(valid=True)


def validate_position(record, conn, now=None):
    """Runs all T07 rejection rules against one vehicle position.

    Validation is deliberately ordered from cheapest/general checks to the
    database lookup:

        1. required fields
        2. South Australia position
        3. timestamp freshness
        4. trip exists

    Args:
        record: realtime vehicle-position dictionary.
        conn: Open SQLite connection.
        now: Optional Unix timestamp for deterministic testing.

    Returns:
        ValidationResult. The first failed rule determines the rejection
        reason.
    """
    checks = (
        lambda: validate_required_fields(record),
        lambda: validate_position_inside_sa(record),
        lambda: validate_timestamp_fresh(record, now=now),
        lambda: validate_trip_exists(record, conn),
    )

    for check in checks:
        result = check()

        if not result.valid:
            return result

    return ValidationResult(valid=True)


def quarantine_record(conn, record, result, now=None):
    """Writes a rejected vehicle-position record to quarantine.

    Args:
        conn: Open SQLite connection.
        record: Original normalised vehicle-position dictionary.
        result: Failed ValidationResult.
        now: Optional Unix timestamp, primarily useful for testing.

    Raises:
        ValueError: If called with a successful ValidationResult.
    """
    if result.valid:
        raise ValueError(
            "Cannot quarantine a record that passed validation"
        )

    if now is None:
        now = int(time.time())

    raw_record = json.dumps(
        record,
        default=str,
        sort_keys=True,
    )

    conn.execute(
        """
        INSERT INTO quarantine (
            quarantined_at,
            entity_id,
            vehicle_id,
            trip_id,
            route_id,
            timestamp,
            latitude,
            longitude,
            reason,
            details,
            raw_record
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(now),
            record.get("entity_id"),
            record.get("vehicle_id"),
            record.get("trip_id"),
            record.get("route_id"),
            _safe_int(record.get("timestamp")),
            _safe_float(record.get("latitude")),
            _safe_float(record.get("longitude")),
            result.reason,
            result.details,
            raw_record,
        ),
    )


def validate_or_quarantine(record, conn, now=None):
    """Validates one record and quarantines it if invalid.

    This is the function normally called from Stage 3's collection loop.

    Args:
        record: realtime vehicle-position dictionary.
        conn: Open SQLite connection.
        now: Optional Unix timestamp for deterministic testing.

    Returns:
        True if valid, False if quarantined.
    """
    result = validate_position(
        record,
        conn,
        now=now,
    )

    if result.valid:
        return True

    quarantine_record(
        conn,
        record,
        result,
        now=now,
    )

    return False


def _safe_int(value):
    """Converts a value to int, returning None when conversion fails."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    """Converts a value to float, returning None when conversion fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
