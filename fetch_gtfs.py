#!/usr/bin/env python3
"""Fetch an Adelaide Metro GTFS feed and write it to CSV.

    pip install gtfs-realtime-bindings
    python3 fetch_gtfs.py vehicle_positions

Feeds: https://gtfs.adelaidemetro.com.au/#/gtfs
"""

import csv
import io
import os
import sys
import urllib.request
import zipfile

from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2

BASE = "https://gtfs.adelaidemetro.com.au/v1"
FEEDS = {
    "vehicle_positions": "/realtime/vehicle_positions",
    "trip_updates": "/realtime/trip_updates",
    "service_alerts": "/realtime/service_alerts",
    "version": "/static/latest/version.txt",
    "timetable": "/static/latest/google_transit.zip",
}


def rows_from(obj, prefix=""):
    """Flatten a decoded entity; a repeated sub-message becomes one row each."""
    rows = [{}]
    for key, value in obj.items():
        name = prefix + key
        if isinstance(value, dict):
            subs = rows_from(value, name + ".")
        elif isinstance(value, list) and isinstance(value[0], dict):
            subs = [r for item in value for r in rows_from(item, name + ".")]
        else:
            subs = [{name: value}]
        rows = [dict(row, **sub) for row in rows for sub in subs]
    return rows


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in FEEDS:
        sys.exit("usage: fetch_gtfs.py {%s}" % "|".join(FEEDS))

    body = urllib.request.urlopen(BASE + FEEDS[name], timeout=60).read()
    os.makedirs("data", exist_ok=True)

    if name == "timetable":
        # The static timetable is a zip of GTFS text files, already CSV-shaped.
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            zf.extractall("data/timetable")
        print("data/timetable/: %s" % ", ".join(sorted(os.listdir("data/timetable"))))
        return

    if name == "version":
        rows = [{"version": body.decode().strip()}]
    else:
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(body)
        rows = [r for e in MessageToDict(feed)["entity"] for r in rows_from(e)]

    columns = list(dict.fromkeys(k for row in rows for k in row))
    with open("data/%s.csv" % name, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print("data/%s.csv: %d rows" % (name, len(rows)))


if __name__ == "__main__":
    main()
