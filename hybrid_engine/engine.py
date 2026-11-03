# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         hybrid_engine/engine.py
# Date:         01-11-2026
# Description:  Predict, turn into facts, reason: the hybrid answer for bus rows.
# Usage:        from hybrid_engine import engine
"""Predict, turn into facts, reason: the hybrid answer for bus rows.

rows_at() is the replay (`--at`) view of the stored data: only buses not
yet at the stop by the query time, and only what was known then.
"""

from datetime import datetime, timedelta

import joblib

from delay_model.train import FEATURES
from hybrid_engine.facts import TIME_FORMAT, build_facts
from hybrid_engine.prolog import run_rules
from shared import config

# Known only after the bus arrives; never shown to the rules.
OUTCOME_COLUMNS = ["observed_arrival", "delay_min", "delay_class"]


def load_model(path=config.MODELS_DIR / "model.joblib"):
    """Loads the bundle make train saved.

    Raises:
        RuntimeError: if make train has not been run.
    """
    if not path.exists():
        raise RuntimeError("%s is missing; run `make train` first" % path)
    return joblib.load(path)


def predict(bundle, rows):
    """Adds p_early, p_on_time and p_late columns from the saved model."""
    proba = bundle["model"].predict_proba(rows[FEATURES])
    columns = {name: proba[:, index] for index, name in enumerate(bundle["classes"])}
    return rows.assign(p_early=columns["early"], p_on_time=columns["on_time"],
                       p_late=columns["late"])


def answer(rows, bundle, timepoints, extra_facts=()):
    """Predicts and reasons about the rows in one Prolog batch.

    Args:
        rows: Feature rows with an id column (unique integers).
        bundle: The saved model bundle.
        timepoints: Set of (trip_id, stop_id) timing points.
        extra_facts: Further fact lines (live estimates, alerts, test facts).

    Returns:
        Tuple (rows with probabilities, dict of id to answer).
    """
    predicted = predict(bundle, rows)
    facts = build_facts(predicted, bundle["seen_stops"], timepoints, extra_facts)
    return predicted, run_rules(facts)


def normalise_time(text):
    """Turns "YYYY-MM-DD HH:MM[:SS]" into "YYYY-MM-DD HH:MM:SS"."""
    for pattern in (TIME_FORMAT, "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, pattern).strftime(TIME_FORMAT)
        except ValueError:
            continue
    raise ValueError("time must look like 2026-10-30 08:10, got %r" % text)


def rows_at(features, at, route=None, stop_id=None, within=config.QUERY_WITHIN_MINUTES):
    """The stored buses a query at time `at` would see, with only what was known then.

    A bus is included when it is due within `within` minutes and had not
    reached the stop yet. Its previous-stop delay is kept only if that stop
    was passed by `at`; otherwise the row looks like a first stop. The
    outcome columns are dropped.

    Args:
        features: DataFrame of the delay_features table.
        at: "YYYY-MM-DD HH:MM:SS" query time.
        route, stop_id: Optional filters.
        within: Minutes to look ahead.

    Returns:
        DataFrame of the matching rows with an id column.
    """
    until = (datetime.strptime(at, TIME_FORMAT) + timedelta(minutes=within)).strftime(TIME_FORMAT)
    keep = (features["scheduled_arrival"] <= until) & (features["observed_arrival"] > at)
    if route is not None:
        keep &= features["route"] == route
    if stop_id is not None:
        keep &= features["stop_id"] == stop_id
    rows = features[keep].copy()
    known = rows["prev_stop_observed"].notna() & (rows["prev_stop_observed"] <= at)
    rows["has_prev_stop"] = rows["has_prev_stop"].where(known, 0)
    rows["prev_stop_delay_min"] = rows["prev_stop_delay_min"].where(known, 0.0)
    rows = rows.drop(columns=OUTCOME_COLUMNS).sort_values("scheduled_arrival")
    return rows.reset_index(drop=True).assign(id=lambda frame: frame.index + 1)
