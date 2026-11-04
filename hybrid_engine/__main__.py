# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         hybrid_engine/__main__.py
# Date:         01-11-2026
# Description:  Command line: ask the hybrid engine about a route at a stop.
# Usage:        python -m hybrid_engine ask status G10 3474 --at "2026-10-30 08:10"
"""Command line: ask the hybrid engine about a route at a stop.

Two questions:
  status <route> <stop>    each bus due at the stop: verdict, confidence, action, reasons
  bunching <route> [stop]  consecutive buses predicted to bunch or leave a long gap,
                           at every chosen stop of the route (or one stop)

Only the replay mode (--at, from stored data) exists so far. Live mode needs
Adelaide Metro's trip_updates and service_alerts and is not built yet.
"""

import argparse
import sqlite3
import sys
from datetime import datetime

import pandas as pd

from hybrid_engine import engine
from hybrid_engine.facts import TIME_FORMAT, load_timepoints
from shared import config

PAIR_EVENTS = [("bunching", "bunching_leader", "the gap will close"),
               ("long gap", "long_gap_leader", "the gap will open")]


def resolve_stop(conn, route, stop):
    """Finds the stop id for a stop id or a stop name of the route.

    Raises:
        SystemExit: if the stop is not a chosen stop of the route.
    """
    found = conn.execute(
        "SELECT stop_id, stop_name FROM stops WHERE route = ? "
        "AND (stop_id = ? OR lower(stop_name) = lower(?))", (route, stop, stop)).fetchone()
    if found is None:
        sys.exit("%r is not a chosen stop of route %s" % (stop, route))
    return found


def route_stops(conn, route):
    """The chosen stops of a route, in their rank order.

    Raises:
        SystemExit: if the route is not a chosen route.
    """
    found = conn.execute("SELECT stop_id, stop_name FROM stops WHERE route = ? "
                         "ORDER BY stop_rank_on_route", (route,)).fetchall()
    if not found:
        sys.exit("%r is not a chosen route" % route)
    return found


def outcome_line(result, outcome):
    """What really happened, and whether the verdict and warnings were right.

    Only printed after the answer: the rows the model and rules saw had the
    outcome removed (engine.rows_at).
    """
    actual = outcome["delay_class"]
    parts = ["verdict %s" % ("right" if result["verdict"] == actual else "wrong")]
    parts += ["%s warning %s" % (warned, "right" if warned == actual else "wrong")
              for warned in result["warnings"]]
    return "Actually: arrived %s (%+.1f min, %s) -> %s" % (
        outcome["observed_arrival"][11:16], outcome["delay_min"], actual, ", ".join(parts))


def pair_outcome_line(event, leader_outcome, follower_outcome, headway_min):
    """Whether a predicted bunching or long gap really happened.

    Uses the same test as hybrid_vs_ml: an observed gap under BUNCH_FRAC of
    the scheduled headway is bunching, over GAP_FRAC is a long gap.
    """
    gap = (datetime.strptime(follower_outcome["observed_arrival"], TIME_FORMAT)
           - datetime.strptime(leader_outcome["observed_arrival"], TIME_FORMAT)
           ).total_seconds() / 60
    if event == "bunching":
        real = gap < config.BUNCH_FRAC * headway_min
    else:
        real = gap > config.GAP_FRAC * headway_min
    if gap < 0:
        apart = "the follower arrived %.1f min before the leader" % -gap
    else:
        apart = "arrived %.1f min apart" % gap
    return "Actually: %s (scheduled %.0f) -> %s %s" % (
        apart, headway_min, event, "was real" if real else "did not happen")


def print_status(route, stop_name, at, rows, answers, outcomes=None):
    """Prints one answer block per bus, with its reasoning trace.

    Args:
        outcomes: Optional dict of (trip_id, stop_id, service_date) to the
            stored observed_arrival, delay_min and delay_class, printed last.
    """
    print("%s at %s, %s (replay from stored data)" % (route, stop_name, at))
    if rows.empty:
        print("No chosen bus due in the next %d minutes." % config.QUERY_WITHIN_MINUTES)
        return
    for row in rows.to_dict("records"):
        result = answers[row["id"]]
        print("\nTrip %s, due %s  ·  verdict: %s  ·  confidence: %s  ·  action: %s"
              % (row["trip_id"], row["scheduled_arrival"][11:16], result["verdict"],
                 result["confidence"], result["action"]))
        for line in result["trace"]:
            print("  - " + line)
        outcome = (outcomes or {}).get((row["trip_id"], row["stop_id"], row["service_date"]))
        if outcome is not None:
            print("  " + outcome_line(result, outcome))


def print_bunching(route, stops, at, rows, answers, outcomes=None):
    """Prints the bus pairs the rules flag, stop by stop.

    Args:
        stops: List of (stop_id, stop_name) to report on.
        outcomes: As in print_status.
    """
    print("%s bunching check, %s (replay from stored data)" % (route, at))
    by_id = rows.set_index("id") if not rows.empty else rows
    for stop_id, stop_name in stops:
        print("\n%s (%s)" % (stop_name, stop_id))
        here = rows[rows["stop_id"] == stop_id] if not rows.empty else rows
        if here.empty:
            print("  No chosen bus due in the next %d minutes." % config.QUERY_WITHIN_MINUTES)
            continue
        flagged = 0
        for row in here.to_dict("records"):
            result = answers[row["id"]]
            for event, key, meaning in PAIR_EVENTS:
                if result[key] is None:
                    continue
                flagged += 1
                leader = by_id.loc[result[key]]
                print("  Trip %s due %s behind trip %s due %s: %s, %s"
                      % (row["trip_id"], row["scheduled_arrival"][11:16], leader["trip_id"],
                         leader["scheduled_arrival"][11:16], event, meaning))
                print("    p(late) leader %.2f, follower %.2f  ·  p(early) leader %.2f, "
                      "follower %.2f  ·  action: %s"
                      % (leader["p_late"], row["p_late"], leader["p_early"], row["p_early"],
                         result["action"]))
                lookup = outcomes or {}
                ahead = lookup.get((leader["trip_id"], stop_id, row["service_date"]))
                behind = lookup.get((row["trip_id"], stop_id, row["service_date"]))
                if ahead is not None and behind is not None:
                    print("    " + pair_outcome_line(event, ahead, behind, row["headway_min"]))
        if not flagged:
            print("  No bunching or long gaps predicted in the next %d minutes."
                  % config.QUERY_WITHIN_MINUTES)


def main(argv=None):
    """Parses the query and prints the answer."""
    parser = argparse.ArgumentParser(prog="python -m hybrid_engine")
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="ask a question")
    ask.add_argument("query", choices=["status", "bunching"])
    ask.add_argument("route")
    ask.add_argument("stop", nargs="?",
                     help="stop id or stop name (needed for status; optional for bunching)")
    ask.add_argument("--at", help='answer from stored data, e.g. "2026-10-30 08:10"')
    args = parser.parse_args(argv)
    if args.query == "status" and args.stop is None:
        ask.error("status needs a stop")
    if args.at is None:
        sys.exit("Live mode needs Adelaide Metro trip_updates and is not built yet; use --at.")

    at = engine.normalise_time(args.at)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        if args.stop is not None:
            stops = [resolve_stop(conn, args.route, args.stop)]
        else:
            stops = route_stops(conn, args.route)
        features = pd.read_sql_query("SELECT * FROM delay_features", conn)
        timepoints = load_timepoints(conn)
    finally:
        conn.close()
    one_stop = stops[0][0] if args.stop is not None else None
    rows = engine.rows_at(features, at, args.route, one_stop)
    answers = {}
    if not rows.empty:
        rows, answers = engine.answer(rows, engine.load_model(), timepoints)
    on_route = features[features["route"] == args.route]
    outcomes = {(record["trip_id"], record["stop_id"], record["service_date"]): record
                for record in on_route[["trip_id", "stop_id", "service_date"]
                                       + engine.OUTCOME_COLUMNS].to_dict("records")}
    if args.query == "status":
        print_status(args.route, stops[0][1], at, rows, answers, outcomes)
    else:
        print_bunching(args.route, stops, at, rows, answers, outcomes)


if __name__ == "__main__":
    main()
