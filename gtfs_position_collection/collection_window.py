# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         gtfs_position_collection/collection_window.py
# Date:         21-10-2026
# Description:  When to collect: the daily collection windows in config.COLLECTION_WINDOWS.
# Usage:        from gtfs_position_collection.collection_window import CollectionWindow
"""When to collect: the daily collection windows in config.COLLECTION_WINDOWS.

Each window is a ("HH:MM", "HH:MM") pair of Adelaide clock times, the same
every day. The collector polls inside a window and sleeps until the next one
opens, so one run collects every window of every day without being restarted.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from shared import config

ADELAIDE_TZ = ZoneInfo("Australia/Adelaide")


def convert_clock_time_to_seconds(clock_time):
    """Turns "HH:MM" into seconds after midnight."""
    hours, minutes = (int(part) for part in clock_time.split(":"))
    return hours * 3600 + minutes * 60


class CollectionWindow:
    """Answers "should the collector poll now?" and "how long until it should?"."""

    def __init__(self, windows=config.COLLECTION_WINDOWS):
        self.windows = windows
        self.windows_seconds = sorted(
            (convert_clock_time_to_seconds(start), convert_clock_time_to_seconds(end))
            for start, end in windows)

    def open_window(self, now=None):
        """Returns the ("HH:MM", "HH:MM") window now falls inside, or None.

        Args:
            now: Timezone-aware datetime; defaults to the current Adelaide time.
        """
        now = now or datetime.now(ADELAIDE_TZ)
        seconds_into_day = now.hour * 3600 + now.minute * 60 + now.second
        for start, end in self.windows:
            if (convert_clock_time_to_seconds(start) <= seconds_into_day
                    < convert_clock_time_to_seconds(end)):
                return (start, end)
        return None

    def is_open(self, now=None):
        """True if now falls inside one of the windows."""
        return self.open_window(now) is not None

    def seconds_until_open(self, now=None):
        """Seconds until the next window opens (0 if one is open now)."""
        now = now or datetime.now(ADELAIDE_TZ)
        if self.is_open(now):
            return 0
        midnight = datetime.combine(now.date(), datetime.min.time(), now.tzinfo)
        for day_offset in (0, 1):
            for start, _ in self.windows_seconds:
                opens = midnight + timedelta(days=day_offset, seconds=start)
                if opens > now:
                    return (opens - now).total_seconds()
        raise ValueError("config.COLLECTION_WINDOWS is empty")

    def describe(self):
        """Returns e.g. "07:00-09:00, 12:00-14:00, 16:00-18:00" for log lines."""
        return ", ".join("%s-%s" % window for window in self.windows)
