# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         hybrid_engine/facts.py
# Date:         01-11-2026
# Description:  Turns predicted bus rows into Prolog facts for reasoner/rules.pl.
# Usage:        from hybrid_engine import facts
"""Turns predicted bus rows into Prolog facts for reasoner/rules.pl.

One builder for both `ask` and `make hybrid_vs_ml`, so the evaluated system is
the one that answers queries. The fact shapes are listed at the top of
reasoner/rules.pl.
"""

import pandas as pd

from shared import config

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def atom(value):
    """Writes a value as a quoted Prolog atom."""
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return "'%s'" % text


def load_timepoints(conn):
    """Reads the (trip_id, stop_id) pairs that are timing points."""
    rows = conn.execute(
        "SELECT DISTINCT trip_id, stop_id FROM scheduled_stop_times WHERE timepoint = '1'")
    return set(rows.fetchall())


def follows_pairs(rows):
    """Finds consecutive scheduled buses of a route at a stop, both in rows.

    Two buses are consecutive when the follower's scheduled gap to the
    leader equals its scheduled headway, so no bus ran between them.

    Args:
        rows: DataFrame with id, service_date, route, stop_id,
            scheduled_arrival and headway_min columns.

    Returns:
        List of (follower_id, leader_id) tuples.
    """
    pairs = []
    frame = rows.assign(scheduled=pd.to_datetime(rows["scheduled_arrival"], format=TIME_FORMAT))
    for _, group in frame.sort_values("scheduled").groupby(
            ["service_date", "route", "stop_id"]):
        records = group.to_dict("records")
        for leader, follower in zip(records, records[1:]):
            gap = (follower["scheduled"] - leader["scheduled"]).total_seconds() / 60
            if abs(gap - follower["headway_min"]) <= 0.5:
                pairs.append((follower["id"], leader["id"]))
    return pairs


def build_facts(rows, seen_stops, timepoints, extra=()):
    """Writes the facts of one query or evaluation batch.

    Args:
        rows: DataFrame with id, route, stop_id, trip_id, service_date,
            scheduled_arrival, headway_min, window, has_prev_stop and the
            p_early, p_on_time and p_late columns.
        seen_stops: Stop ids of the training data.
        timepoints: Set of (trip_id, stop_id) timing points.
        extra: Further fact lines, e.g. live eta/3 and alert/3 facts.

    Returns:
        List of Prolog clause lines.
    """
    lines = [
        "param(p_warn, %r)." % config.P_WARN,
        "param(conf_medium, %r)." % config.CONF_MEDIUM,
        "param(near_stops, %r)." % config.NEAR_STOPS,
        "param(early_minutes, %r)." % config.EARLY_MINUTES,
        "param(late_minutes, %r)." % config.LATE_MINUTES,
    ]
    lines += ["seen_stop(%s)." % atom(stop) for stop in sorted(seen_stops)]
    for row in rows.to_dict("records"):
        key = row["id"]
        lines.append("row(%d, %s, %s, %s)." % (key, atom(row["route"]), atom(row["stop_id"]),
                                               atom(row["trip_id"])))
        lines.append("prob(%d, %r, %r, %r)." % (key, float(row["p_early"]),
                                                float(row["p_on_time"]), float(row["p_late"])))
        lines.append("has_prev(%d, %d)." % (key, int(row["has_prev_stop"])))
        if isinstance(row["window"], str):
            lines.append("in_window(%d)." % key)
        if (row["trip_id"], row["stop_id"]) in timepoints:
            lines.append("timepoint(%d)." % key)
    lines += ["follows(%d, %d)." % pair for pair in follows_pairs(rows)]
    lines += list(extra)
    return lines
