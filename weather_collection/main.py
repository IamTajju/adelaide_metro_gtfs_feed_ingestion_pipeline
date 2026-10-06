# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         weather_collection/main.py
# Date:         28-09-2026
# Description:  Hourly weather from Open-Meteo for the collection windows.
# Usage:        python -m weather_collection [YYYY-MM-DD]
"""Hourly weather from Open-Meteo for the collection windows.

Downloads the hourly temperature, precipitation, wind speed and weather code
of one Adelaide day and stores them in the weather_hourly table of the
project database. The day is yesterday by default, because the weather is
fetched the morning after the vehicle positions were collected.

When the day already has pings in the positions table, only the hours of that
collection window are stored. Without pings the whole day is kept, so the
table is still fillable before the collector has run.

The rows come from the forecast endpoint with a start and end date instead
of the ERA5 archive endpoint, because the archive lags a few days behind the
present and returns empty values for yesterday.
"""

import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from shared import config

# The database file every stage of the project shares.
DB_PATH = config.DATA_DIR / "gtfs.db"

# Weather point: the middle of the CBD box the route selection uses.
LATITUDE = round((config.CBD_NORTH + config.CBD_SOUTH) / 2, 4)
LONGITUDE = round((config.CBD_WEST + config.CBD_EAST) / 2, 4)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = ("temperature_2m", "precipitation",
                 "wind_speed_10m", "weather_code")
LOCAL_TZ = ZoneInfo("Australia/Adelaide")

WEATHER_DDL = """CREATE TABLE IF NOT EXISTS weather_hourly (
    hour_local TEXT PRIMARY KEY,
    temperature_2m REAL,
    precipitation REAL,
    wind_speed_10m REAL,
    weather_code INTEGER
)"""


def fetch_hourly(day):
    """Downloads the hourly weather of one Adelaide day from Open-Meteo.

    Args:
        day: datetime.date of the day to fetch.

    Returns:
        The decoded JSON payload of the API.
    """
    query = urllib.parse.urlencode({
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(HOURLY_FIELDS),
        "timezone": "Australia/Adelaide",
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
    })
    with urllib.request.urlopen(WEATHER_URL + "?" + query, timeout=60) as resp:
        return json.load(resp)


def rows_from_payload(payload, hours=None):
    """Turns an Open-Meteo payload into one tuple per hour.

    Args:
        payload: Decoded JSON payload of the API.
        hours: Optional set of "YYYY-MM-DDTHH:00" strings to keep. None
            keeps every hour of the payload.

    Returns:
        List of (hour_local, temperature_2m, precipitation, wind_speed_10m,
        weather_code) tuples.
    """
    hourly = payload["hourly"]
    rows = []
    for i, hour_local in enumerate(hourly["time"]):
        if hours is not None and hour_local not in hours:
            continue
        rows.append((hour_local,
                     hourly["temperature_2m"][i],
                     hourly["precipitation"][i],
                     hourly["wind_speed_10m"][i],
                     hourly["weather_code"][i]))
    return rows


def collection_hours(conn, day):
    """Finds the hours of the day that actually have position pings.

    Args:
        conn: Open connection to the project database.
        day: datetime.date of the collection day.

    Returns:
        Set of "YYYY-MM-DDTHH:00" strings, or None when the database has no
        positions table or no pings on that day.
    """
    tables = {name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "positions" not in tables:
        return None
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    stamps = conn.execute(
        "SELECT DISTINCT timestamp FROM positions "
        "WHERE timestamp >= ? AND timestamp < ?",
        (int(start.timestamp()), int(end.timestamp()))).fetchall()
    if not stamps:
        return None
    return {datetime.fromtimestamp(stamp, LOCAL_TZ).strftime("%Y-%m-%dT%H:00")
            for (stamp,) in stamps}


def store_rows(conn, rows):
    """Writes the rows into weather_hourly, replacing hours already there.

    Args:
        conn: Open connection to the project database.
        rows: List of tuples in the order of the table columns.

    Returns:
        Number of rows written.
    """
    conn.execute(WEATHER_DDL)
    conn.executemany(
        "INSERT OR REPLACE INTO weather_hourly VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)


def main():
    """Stores the hourly weather of one collection day."""
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        day = datetime.now(LOCAL_TZ).date() - timedelta(days=1)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        hours = collection_hours(conn, day)
        rows = rows_from_payload(fetch_hourly(day), hours)
        written = store_rows(conn, rows)
        window = "whole day" if hours is None else "%d collection hours" % len(hours)
        print("%s: %d weather rows stored (%s)" % (day, written, window))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
