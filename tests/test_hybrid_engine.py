# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_hybrid_engine.py
# Date:         01-11-2026
# Description:  Tests for the facts builder, the Prolog bridge, replays and the evaluation.
# Usage:        python -m pytest tests
"""Tests for the facts builder, the Prolog bridge, replays and the evaluation."""

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from delay_features.main import day_type, delay_class
from delay_model.train import train
from evaluate.main import bus_pairs, evaluate, pair_rule, warning_rates
from hybrid_engine import engine
from hybrid_engine.facts import TIME_FORMAT, build_facts, follows_pairs
from shared import config

pytestmark = pytest.mark.skipif(shutil.which("swipl") is None, reason="SWI-Prolog not installed")

STOPS = ["S1", "S2", "S3"]


def stamp(moment):
    return moment.strftime(TIME_FORMAT)


def timed_features(days=12, seed=0):
    """delay_features rows with real timings: buses every 10 min over 3 stops, 5 min apart."""
    rng = np.random.default_rng(seed)
    rows = []
    for offset in range(days):
        day = date(2026, 10, 20) + timedelta(days=offset)
        rain = float(rng.choice([0.0, 0.0, 2.0]))
        for route in ("G10", "300"):
            for start_hour, window in ((7, "am"), (16, "pm")):
                for trip in range(10):
                    start = datetime(day.year, day.month, day.day, start_hour, 10) \
                        + timedelta(minutes=10 * trip)
                    delay = float(rng.normal(1, 3)) + rain
                    previous = None
                    for index, stop in enumerate(STOPS):
                        if index:
                            delay = 0.8 * delay + float(rng.normal(0.5, 1.5))
                        scheduled = start + timedelta(minutes=5 * index)
                        observed = scheduled + timedelta(minutes=delay)
                        rows.append({
                            "trip_id": "%s_%s_%d_%d" % (route, day, start_hour, trip),
                            "stop_id": stop, "service_date": day.isoformat(), "route": route,
                            "quadrant": "N", "window": window,
                            "day_type": day_type(day.isoformat()), "headway_min": 10.0,
                            "prev_stop_delay_min": previous[0] if previous else 0.0,
                            "has_prev_stop": int(previous is not None),
                            "precipitation_mm": rain, "delay_min": round(delay, 2),
                            "delay_class": delay_class(delay),
                            "scheduled_arrival": stamp(scheduled), "observed_arrival": stamp(observed),
                            "prev_stop_observed": previous[1] if previous else None})
                        previous = (round(delay, 2), stamp(observed))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    """A quick model trained on the synthetic rows, as make train would save it."""
    out_dir = tmp_path_factory.mktemp("models")
    features = timed_features()
    train(features, out_dir=out_dir, quick=True, resamples=20)
    return features, engine.load_model(out_dir / "model.joblib")


def test_prolog_rule_tests_pass():
    done = subprocess.run(["swipl", "-q", "-g", "run_tests", "-t", "halt",
                           str(config.ROOT / "reasoner" / "test_rules.pl")],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_follows_pairs_needs_the_scheduled_gap_to_match_the_headway():
    rows = pd.DataFrame({
        "id": [1, 2, 3], "service_date": ["2026-10-28"] * 3, "route": ["G10"] * 3,
        "stop_id": ["S1"] * 3, "headway_min": [10.0, 10.0, 10.0],
        "scheduled_arrival": ["2026-10-28 08:00:00", "2026-10-28 08:10:00",
                              "2026-10-28 08:30:00"]})
    # 2 follows 1; 3 is 20 min after 2, so a bus between them was not observed.
    assert follows_pairs(rows) == [(2, 1)]


def test_pair_rule_matches_the_prolog_rules():
    assert pair_rule("late", "on_time") == (True, False)
    assert pair_rule("on_time", "early") == (True, False)
    assert pair_rule("on_time", "late") == (False, True)
    assert pair_rule("early", "on_time") == (False, True)
    assert pair_rule(None, None) == (False, False)


def test_outcome_line_scores_the_verdict_and_each_warning():
    from hybrid_engine.__main__ import outcome_line
    outcome = {"observed_arrival": "2026-10-30 08:11:00", "delay_min": 7.0,
               "delay_class": "late"}
    line = outcome_line({"verdict": "on_time", "warnings": ["late"]}, outcome)
    assert line == ("Actually: arrived 08:11 (+7.0 min, late) -> "
                    "verdict wrong, late warning right")
    line = outcome_line({"verdict": "late", "warnings": []}, outcome)
    assert line.endswith("-> verdict right")


def test_warning_rates():
    actual = np.array(["late", "late", "on_time", "early"])
    rates = warning_rates(actual, np.array([True, False, True, False]),
                          np.array([False, False, False, True]))
    assert rates["late_recall"] == 0.5
    assert rates["late_false_alarm"] == 0.5
    assert rates["early_recall"] == 1.0
    assert rates["early_false_alarm"] == 0.0


def test_replay_hides_what_was_not_known_yet():
    features = timed_features(days=1)
    trip = features[features["trip_id"] == features["trip_id"].iloc[0]]
    second = trip[trip["stop_id"] == "S2"].iloc[0]
    before = stamp(datetime.strptime(second["prev_stop_observed"], TIME_FORMAT)
                   - timedelta(minutes=1))
    after = second["prev_stop_observed"]

    early_view = engine.rows_at(features, before, "G10", "S2")
    late_view = engine.rows_at(features, after, "G10", "S2")
    row_before = early_view[early_view["trip_id"] == second["trip_id"]].iloc[0]
    row_after = late_view[late_view["trip_id"] == second["trip_id"]].iloc[0]
    assert row_before["has_prev_stop"] == 0 and row_before["prev_stop_delay_min"] == 0.0
    assert row_after["has_prev_stop"] == 1
    assert "delay_class" not in early_view and "observed_arrival" not in early_view


def test_replay_facts_ignore_the_outcome(trained):
    features, bundle = trained
    at = "2026-10-31 07:20:00"
    changed = features.copy()
    later = changed["observed_arrival"] > at
    changed.loc[later, "delay_min"] = 99.0
    changed.loc[later, "delay_class"] = "late"

    def facts(frame):
        rows = engine.predict(bundle, engine.rows_at(frame, at, "G10", "S3"))
        return build_facts(rows, bundle["seen_stops"], set())

    assert facts(features) == facts(changed)


def test_answer_runs_the_rules(trained):
    features, bundle = trained
    rows = engine.rows_at(features, "2026-10-31 07:20:00", "G10", "S3")
    predicted, answers = engine.answer(rows, bundle, set())
    assert set(answers) == set(predicted["id"])
    for answer in answers.values():
        assert answer["confidence"] in ("high", "medium", "low")
        assert answer["action"] in ("hold_bus", "notify_passengers", "flag_to_operator", "no_action")
        assert answer["trace"][0].startswith("ML predicts")


def test_bus_pairs_skip_warnings_that_come_too_late(trained):
    features, bundle = trained
    day = features[features["service_date"] == "2026-10-31"]
    rows = day.reset_index(drop=True).assign(id=lambda frame: frame.index + 1)
    rows, answers = engine.answer(rows, bundle, set())
    pairs = bus_pairs(rows, answers)
    by_id = rows.set_index("id")
    for pair in pairs.to_dict("records"):
        leader, follower = by_id.loc[pair["leader_id"]], by_id.loc[pair["follower_id"]]
        for bus in (leader, follower):
            if bus["has_prev_stop"] == 1:
                assert bus["prev_stop_observed"] < leader["observed_arrival"]


def test_evaluate_writes_every_output(trained, tmp_path):
    features, bundle = trained
    timepoints = {(trip, "S2") for trip in features["trip_id"].unique()}
    summary = evaluate(features, bundle, timepoints, out_dir=tmp_path, resamples=20)

    for name in ("safety.csv", "confidence.csv", "bunching.csv", "pairs.csv", "metrics.json"):
        assert (tmp_path / name).exists(), name
    safety = pd.read_csv(tmp_path / "safety.csv")
    assert set(safety["system"]) == {"ml_argmax", "ml_threshold", "hybrid"}
    assert "operator" in summary["limitation"]
    json.loads((tmp_path / "metrics.json").read_text(), parse_constant=pytest.fail)

    cases = sorted((tmp_path / "cases").glob("*.json"))
    names = [json.loads(path.read_text())["case"] for path in cases]
    assert "confident_correct" in names and "operator_disagrees_far_with_closure" in names
    for path in cases:
        record = json.loads(path.read_text())
        assert record["trace"] and record["answer"]["action"]
        assert path.with_suffix(".md").exists()
        if record["kind"].startswith("constructed"):
            assert record["outcome"] is None
        else:
            assert record["reproduce"].startswith("python -m hybrid_engine ask status")

    unseen = json.loads(next(p for p in cases if "unseen_stop" in p.name).read_text())
    assert "unseen_stop" in unseen["answer"]["guards"] and unseen["answer"]["confidence"] == "low"
