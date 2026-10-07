# Student Name: Joel Bates
# Student FAN:  BATE0218
# File:         gtfs_position_collection/validate.py
# Date:         07-10-2026
# Description:  Validates and quarantines realtime GTFS vehicle positions.
# Usage:        from gtfs_position_collection import validate

"""Validation and quarantine layer for GTFS-Realtime vehicle positions."""

import json
import time
from dataclasses import dataclass

from shared import config


MISSING_REQUIRED_FIELDS = "missing_required_fields"
POSITION_OUTSIDE_SA = "position_outside_sa"
STALE_TIMESTAMP = "stale_timestamp"
FUTURE_TIMESTAMP = "future_timestamp"
TRIP_NOT_FOUND = "trip_not_found"


# The feed decoder currently produces flattened names such as
# trip_route_id and position_latitude. The simpler aliases are retained
# so the validator is not tied to one particular decoder representation.
FIELD_ALIASES = {
    "entity_id": ("entity_id",),
    "vehicle_id": ("vehicle_id",),
    "trip_id": ("trip_trip_id", "trip_id"),
    "route_id": ("trip_route_id", "route_id"),
    "timestamp": ("timestamp",),
    "latitude": ("position_latitude", "latitude"),
    "longitude": ("position_longitude", "longitude"),
}


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating one realtime vehicle position."""

    valid: bool
    reason: str | None = None
    details: str | None = None


def _value(record, logical_field):
    """Returns a logical field from any of its recognised aliases.

    Args:
        record: Feed row dictionary.
        logical_field: Canonical field name such as 'trip_id'.

    Returns:
        Value from the first matching field, otherwise None.
    """
    for field_name in FIELD_ALIASES[logical_field]:
        try:
            return record[field_name]
        except (KeyError, IndexError, TypeError):
            continue

    return None


def _is_missing(value):
    """Returns whether a required value is missing."""
    if value is None:
        return True

    if isinstance(value, str) and not value.strip():
        return True

    return False


def _safe_int(value):
    """Converts a value to int, returning None on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    """Converts a value to float, returning None on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_required_fields(record):
    """Checks fields required by this project's collection pipeline."""
    required_fields = (
        "trip_id",
        "timestamp",
        "latitude",
        "longitude",
    )

    missing = [
        field
        for field in required_fields
        if _is_missing(_value(record, field))
    ]

    if missing:
        return ValidationResult(
            valid=False,
            reason=MISSING_REQUIRED_FIELDS,
            details="Missing required field(s): " + ", ".join(missing),
        )

    return ValidationResult(valid=True)


def validate_position_inside_sa(record):
    """Checks that the vehicle position lies inside the SA bounding box."""
    latitude = _safe_float(_value(record, "latitude"))
    longitude = _safe_float(_value(record, "longitude"))

    if latitude is None or longitude is None:
        return ValidationResult(
            valid=False,
            reason=POSITION_OUTSIDE_SA,
            details=(
                "Latitude and longitude must be numeric: "
                f"latitude={_value(record, 'latitude')!r}, "
                f"longitude={_value(record, 'longitude')!r}"
            ),
        )

    inside_sa = (
        config.SA_LAT_MIN <= latitude <= config.SA_LAT_MAX
        and config.SA_LON_MIN <= longitude <= config.SA_LON_MAX
    )

    if not inside_sa:
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
    """Checks that the vehicle observation timestamp is sufficiently fresh."""
    if now is None:
        now = time.time()

    timestamp = _safe_int(_value(record, "timestamp"))

    if timestamp is None:
        return ValidationResult(
            valid=False,
            reason=STALE_TIMESTAMP,
            details=(
                f"Invalid timestamp: "
                f"{_value(record, 'timestamp')!r}"
            ),
        )

    age = float(now) - timestamp

    if age > config.POSITION_MAX_AGE_SECONDS:
        return ValidationResult(
            valid=False,
            reason=STALE_TIMESTAMP,
            details=(
                f"Vehicle position is {age:.1f} seconds old; "
                f"maximum is {config.POSITION_MAX_AGE_SECONDS} seconds"
            ),
        )
    # Negative age means the source timestamp is ahead of our system clock.
    if age < -config.POSITION_FUTURE_TOLERANCE_SECONDS:
        return ValidationResult(
            valid=False,
            reason=FUTURE_TIMESTAMP,
            details=(
                f"Vehicle timestamp is {-age:.1f} seconds in the future; "
                f"maximum tolerance is "
                f"{config.POSITION_FUTURE_TOLERANCE_SECONDS} seconds"
            ),
        )

    return ValidationResult(valid=True)


def validate_trip_exists(record, conn):
    """Checks that the realtime trip exists in scheduled_stop_times."""
    trip_id = _value(record, "trip_id")

    row = conn.execute(
        """
        SELECT 1
        FROM scheduled_stop_times
        WHERE trip_id = ?
        LIMIT 1
        """,
        (str(trip_id),),
    ).fetchone()

    if row is None:
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
    """Runs all validation rules against one vehicle position.

    Rules are deliberately ordered so inexpensive checks occur before
    the database lookup.

    Args:
        record: One normalised vehicle-position feed row.
        conn: Open SQLite connection.
        now: Optional Unix timestamp for deterministic testing.

    Returns:
        ValidationResult containing the first failed rule, or valid=True.
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
    """Stores one rejected vehicle-position record in quarantine."""
    if result.valid:
        raise ValueError(
            "Cannot quarantine a record that passed validation"
        )

    if now is None:
        now = int(time.time())

    # Convert to a normal dict in case the row is another mapping type.
    raw_record = json.dumps(
        dict(record),
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
            _value(record, "entity_id"),
            _value(record, "vehicle_id"),
            _value(record, "trip_id"),
            _value(record, "route_id"),
            _safe_int(_value(record, "timestamp")),
            _safe_float(_value(record, "latitude")),
            _safe_float(_value(record, "longitude")),
            result.reason,
            result.details,
            raw_record,
        ),
    )


def validate_positions(rows, conn, now=None):
    """Validates a batch of relevant realtime vehicle positions.

    Invalid rows are written to quarantine. Valid rows are returned
    unchanged so they can continue to store_positions().

    Args:
        rows: Relevant vehicle-position rows from filters.keep_relevant().
        conn: Open SQLite database connection.
        now: Optional Unix timestamp. If omitted, the current time is
            captured once for the whole feed snapshot.

    Returns:
        Tuple:
            valid_rows: List of rows that passed all validation rules.
            quarantined_count: Number of rows rejected and quarantined.
    """
    if now is None:
        now = time.time()

    valid_rows = []
    quarantined_count = 0

    # Quarantine all bad records from one feed snapshot transactionally.
    with conn:
        for record in rows:
            result = validate_position(
                record,
                conn,
                now=now,
            )

            if result.valid:
                valid_rows.append(record)
                continue

            quarantine_record(
                conn,
                record,
                result,
                now=now,
            )

            quarantined_count += 1

    return valid_rows, quarantined_count