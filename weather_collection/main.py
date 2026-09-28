# Student Name: Saad Albaieji
# Student FAN:  alba0202
# File:         weather_collection/main.py
# Date:         28-09-2026
# Description:  Hourly weather from Open-Meteo for the collection windows.
# Usage:        python -m weather_collection [YYYY-MM-DD]
"""Hourly weather from Open-Meteo for the collection windows.

Downloads the hourly temperature, precipitation, wind speed and weather code
of one Adelaide day. The day is yesterday by default, because the weather is
fetched the morning after the vehicle positions were collected.

The rows come from the forecast endpoint with a start and end date instead
of the ERA5 archive endpoint, because the archive lags a few days behind the
present and returns empty values for yesterday.
"""

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from shared import config

# Weather point: the middle of the CBD box the route selection uses.
LATITUDE = round((config.CBD_NORTH + config.CBD_SOUTH) / 2, 4)
LONGITUDE = round((config.CBD_WEST + config.CBD_EAST) / 2, 4)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = ("temperature_2m", "precipitation",
                 "wind_speed_10m", "weather_code")
LOCAL_TZ = ZoneInfo("Australia/Adelaide")


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


def main():
    """Fetches the hourly weather of one collection day."""
    if len(sys.argv) > 1:
        day = date.fromisoformat(sys.argv[1])
    else:
        day = datetime.now(LOCAL_TZ).date() - timedelta(days=1)
    rows = rows_from_payload(fetch_hourly(day))
    print("%s: %d hourly weather rows fetched" % (day, len(rows)))


if __name__ == "__main__":
    main()
