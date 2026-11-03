# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         hybrid_engine/__main__.py
# Date:         01-11-2026
# Description:  Command line: ask the hybrid engine about a route at a stop.
# Usage:        python -m hybrid_engine ask status G10 "King William St" --at "2026-10-30 08:10"
"""Command line: ask the hybrid engine about a route at a stop.

Only the replay mode (--at, from stored data) exists so far. Live mode needs
Adelaide Metro's trip_updates and service_alerts and is not built yet.
"""

import argparse
import sqlite3
import sys

import pandas as pd

from hybrid_engine import engine
from hybrid_engine.facts import load_timepoints
from shared import config


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


def print_status(route, stop_name, at, rows, answers, outcomes=None):
    """Prints one answer block per bus, with its reasoning trace.

    Args:
        outcomes: Optional dict of (trip_id, service_date) to the stored
            observed_arrival, delay_min and delay_class, printed last.
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
        outcome = (outcomes or {}).get((row["trip_id"], row["service_date"]))
        if outcome is not None:
            print("  " + outcome_line(result, outcome))


def main(argv=None):
    """Parses the query and prints the answer."""
    parser = argparse.ArgumentParser(prog="python -m hybrid_engine")
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="ask a question")
    ask.add_argument("query", choices=["status"])
    ask.add_argument("route")
    ask.add_argument("stop", help="stop id or stop name")
    ask.add_argument("--at", help='answer from stored data, e.g. "2026-10-30 08:10"')
    args = parser.parse_args(argv)
    if args.at is None:
        sys.exit("Live mode needs Adelaide Metro trip_updates and is not built yet; use --at.")

    at = engine.normalise_time(args.at)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        stop_id, stop_name = resolve_stop(conn, args.route, args.stop)
        features = pd.read_sql_query("SELECT * FROM delay_features", conn)
        timepoints = load_timepoints(conn)
    finally:
        conn.close()
    rows = engine.rows_at(features, at, args.route, stop_id)
    answers = {}
    if not rows.empty:
        rows, answers = engine.answer(rows, engine.load_model(), timepoints)
    at_stop = features[features["stop_id"] == stop_id]
    outcomes = {(record["trip_id"], record["service_date"]): record
                for record in at_stop[["trip_id", "service_date"] + engine.OUTCOME_COLUMNS]
                .to_dict("records")}
    print_status(args.route, stop_name, at, rows, answers, outcomes)


if __name__ == "__main__":
    main()
