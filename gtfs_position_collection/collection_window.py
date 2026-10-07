# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         gtfs_position_collection/collection_window.py
# Date:         07-10-2026
# Description:  When to collect: first to last scheduled bus of the chosen routes at the chosen stops.
# Usage:        from gtfs_position_collection.collection_window import CollectionWindow
"""When to collect: first to last scheduled bus of the chosen routes at the chosen stops.

A service day's window is the earliest and latest arrival_time (stop_times.txt)
of the chosen routes' trips at the chosen stops, for the services running that
day, widened by COLLECTION_MARGIN_MINUTES on both sides. GTFS times count from
the start of the service day and can pass midnight ("25:10:00"), so after
midnight the previous service day's window is checked as well.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared import config
from shared.timetable import find_service_ids_running_on_date, read_gtfs

ADELAIDE_TZ = ZoneInfo("Australia/Adelaide")


def convert_gtfs_time_to_seconds(gtfs_time):
    """Turns a GTFS "HH:MM:SS" (hours may pass 24) into seconds after the service day starts."""
    hours, minutes, seconds = (int(part) for part in gtfs_time.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def find_scheduled_window_seconds(service_day, chosen_route_ids, chosen_stop_ids,
                                  metro_timetable_path=config.TIMETABLE_DIR):
    """Finds the first and last scheduled arrival of chosen trips at chosen stops on one day.

    Args:
        service_day: datetime.date of the service day.
        chosen_route_ids: Set of GTFS route_ids (every variant, e.g. "G10A").
        chosen_stop_ids: Set of GTFS stop_ids.
        metro_timetable_path: Timetable folder or zip (see read_gtfs).

    Returns:
        Tuple (first_seconds, last_seconds) after the service day starts, or
        None when none of the chosen trips run that day.
    """
    services = find_service_ids_running_on_date(
        metro_timetable_path, service_day)
    trips = read_gtfs(metro_timetable_path, "trips.txt",
                      columns=["route_id", "service_id", "trip_id"])
    chosen_trip_ids = set(trips.trip_id[trips.route_id.isin(chosen_route_ids)
                                        & trips.service_id.isin(services)])
    stop_times = read_gtfs(metro_timetable_path, "stop_times.txt",
                           columns=["trip_id", "stop_id", "arrival_time"])
    chosen_arrivals = stop_times.arrival_time[stop_times.trip_id.isin(chosen_trip_ids)
                                              & stop_times.stop_id.isin(chosen_stop_ids)]
    if chosen_arrivals.empty:
        return None
    arrival_seconds = chosen_arrivals.map(convert_gtfs_time_to_seconds)
    return int(arrival_seconds.min()), int(arrival_seconds.max())


class CollectionWindow:
    """Answers "should the collector poll now?" and caches one window per service day."""

    def __init__(self, chosen_route_ids, chosen_stop_ids,
                 metro_timetable_path=config.TIMETABLE_DIR,
                 margin_minutes=config.COLLECTION_MARGIN_MINUTES):
        self.chosen_route_ids = set(chosen_route_ids)
        self.chosen_stop_ids = set(chosen_stop_ids)
        self.metro_timetable_path = metro_timetable_path
        self.margin_seconds = margin_minutes * 60
        self.windows_by_service_day = {}

    def get_window_seconds(self, service_day):
        """Returns the (first, last) seconds of one service day, margin included, or None."""
        if service_day not in self.windows_by_service_day:
            window = find_scheduled_window_seconds(
                service_day, self.chosen_route_ids, self.chosen_stop_ids,
                self.metro_timetable_path)
            if window is not None:
                window = (window[0] - self.margin_seconds,
                          window[1] + self.margin_seconds)
            self.windows_by_service_day[service_day] = window
        return self.windows_by_service_day[service_day]

    def is_open(self, now=None):
        """True if now falls inside today's window or the tail of yesterday's (after midnight).

        Args:
            now: Timezone-aware datetime; defaults to the current Adelaide time.
        """
        now = now or datetime.now(ADELAIDE_TZ)
        for service_day in (now.date(), now.date() - timedelta(days=1)):
            window = self.get_window_seconds(service_day)
            if window is None:
                continue
            service_day_start = datetime.combine(
                service_day, datetime.min.time(), now.tzinfo)
            seconds_into_service_day = (
                now - service_day_start).total_seconds()
            if window[0] <= seconds_into_service_day <= window[1]:
                return True
        return False

    def describe(self, service_day):
        """Returns e.g. "04:42-24:41 (incl. 30 min margin)" for log lines (GTFS-style hours)."""
        window = self.get_window_seconds(service_day)
        if window is None:
            return "no chosen trips run"
        start, end = ("%02d:%02d" % (max(0, second) // 3600, max(0, second) % 3600 // 60)
                      for second in window)
        return "%s-%s (incl. %d min margin)" % (start, end, self.margin_seconds // 60)
