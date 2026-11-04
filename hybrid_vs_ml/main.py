# Student Name: Joel Bates
# Student FAN:  bate0218
# File:         hybrid_vs_ml/main.py
# Date:         01-11-2026
# Description:  Scores what the Prolog layer adds on the held-out test days.
# Usage:        python -m hybrid_vs_ml
"""Scores what the Prolog layer adds on the held-out test days.

Runs the saved model and reasoner/rules.pl over the same last TEST_DAYS
dates make train held out, and scores against the real arrivals:

1. safety.csv: recall and false-alarm rate of late and early warnings for
   ML argmax, ML with the same P_WARN threshold, and the hybrid. Any gap
   between the last two comes from the rules alone, not from the threshold.
2. confidence.csv: accuracy and coverage per confidence level, for the
   rules and for the ML probability alone.
3. bunching.csv: bunching and long gaps between consecutive buses, against
   the observed gaps, for the timetable, a persistence pair and the hybrid.
4. cases/: the report's test cases, each replayed through `ask --at`.
5. metrics.json: a summary of the above.

Operator estimates and service alerts were never stored, so every offline
answer takes the rules' "no operator estimate" branch. Those rules are
covered by reasoner/test_rules.pl and the constructed cases only.
"""

import json
import shutil
import sqlite3
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from delay_features.main import delay_class
from delay_model.train import FEATURES, SEED, TARGET, load_features, split_by_date
from hybrid_engine import engine
from hybrid_engine.facts import TIME_FORMAT, follows_pairs, load_timepoints
from shared import config

PROB_COLUMNS = ["p_early", "p_on_time", "p_late"]
CLASS_OF = {"p_early": "early", "p_on_time": "on_time", "p_late": "late"}
LIMITATION = ("Adelaide Metro trip_updates and service_alerts were not stored, so every "
              "offline answer uses the rules' no-operator branch. The operator and alert "
              "rules are checked by reasoner/test_rules.pl and the constructed cases only.")


def ml_class(rows):
    """The ML argmax class per row."""
    return rows[PROB_COLUMNS].idxmax(axis=1).map(CLASS_OF).to_numpy()


def system_warnings(rows, answers):
    """Which rows each system warns late and early.

    ml_threshold uses the same P_WARN as the rules, so any difference to
    the hybrid comes from the rules (the timing-point veto), not the cut-off.
    """
    argmax = ml_class(rows)
    hybrid = [answers[key]["warnings"] for key in rows["id"]]
    return {
        "ml_argmax": {"late": argmax == "late", "early": argmax == "early"},
        "ml_threshold": {"late": (rows["p_late"] >= config.P_WARN).to_numpy(),
                         "early": (rows["p_early"] >= config.P_WARN).to_numpy()},
        "hybrid": {"late": np.array(["late" in found for found in hybrid]),
                   "early": np.array(["early" in found for found in hybrid])},
    }


def warning_rates(actual, warned_late, warned_early):
    """Recall and false-alarm rate of the late and early warnings."""
    def share(among, hits):
        return float(hits[among].mean()) if among.any() else float("nan")
    late, early = actual == "late", actual == "early"
    return {"late_recall": share(late, warned_late),
            "late_false_alarm": share(~late, warned_late),
            "early_recall": share(early, warned_early),
            "early_false_alarm": share(~early, warned_early)}


def bootstrap(rows, statistic, resamples=config.BOOTSTRAP_RESAMPLES):
    """95% intervals of statistic(row positions), resampling whole trips (trip + date)."""
    rng = np.random.default_rng(SEED)
    groups = list(rows.groupby(["trip_id", "service_date"]).indices.values())
    draws = {}
    for _ in range(resamples):
        picked = np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))])
        for name, value in statistic(picked).items():
            draws.setdefault(name, []).append(value)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # A resample without any late bus.
        return {name: (float(np.nanpercentile(values, 2.5)), float(np.nanpercentile(values, 97.5)))
                for name, values in draws.items()}


def safety_table(rows, answers, resamples=config.BOOTSTRAP_RESAMPLES):
    """Warning recall and false alarms per system, with 95% intervals."""
    actual = rows[TARGET].to_numpy()
    records = []
    for system, warned in system_warnings(rows, answers).items():
        def statistic(picked, warned=warned):
            return warning_rates(actual[picked], warned["late"][picked], warned["early"][picked])
        values = statistic(np.arange(len(rows)))
        intervals = bootstrap(rows, statistic, resamples)
        for metric, value in values.items():
            records.append({"system": system, "metric": metric, "value": value,
                            "ci_low": intervals[metric][0], "ci_high": intervals[metric][1]})
    return pd.DataFrame(records)


def confidence_table(rows, answers):
    """Accuracy and coverage per confidence level: the rules vs the ML probability alone."""
    correct = ml_class(rows) == rows[TARGET].to_numpy()
    top = rows[PROB_COLUMNS].max(axis=1).to_numpy()
    levels = {
        "hybrid": np.array([answers[key]["confidence"] for key in rows["id"]]),
        "ml_probability_only": np.where(top >= config.CONF_MEDIUM, "medium", "low"),
    }
    records = []
    for system, level_of in levels.items():
        for level in ("high", "medium", "low"):
            mask = level_of == level
            if mask.any():
                records.append({"system": system, "level": level, "rows": int(mask.sum()),
                                "coverage": float(mask.mean()),
                                "accuracy": float(correct[mask].mean())})
    return pd.DataFrame(records)


def persistence_class(row):
    """The previous stop's class, or None at a first stop."""
    return delay_class(row["prev_stop_delay_min"]) if row["has_prev_stop"] == 1 else None


def pair_rule(leader_class, follower_class):
    """The bunching and long-gap rules of reasoner/rules.pl on two classes."""
    bunching = ((leader_class == "late" and follower_class != "late")
                or (follower_class == "early" and leader_class != "early"))
    long_gap = ((leader_class == "early" and follower_class != "early")
                or (follower_class == "late" and leader_class != "late"))
    return bunching, long_gap


def bus_pairs(rows, answers):
    """Consecutive bus pairs whose warning could come before the leader arrived.

    A row's prediction exists once its previous stop was passed (or at any
    time for a first stop). Pairs where that came after the leader's arrival
    are left out: there the warning would be too late to act on.
    """
    by_id = rows.set_index("id")
    records = []
    for follower_id, leader_id in follows_pairs(rows):
        leader, follower = by_id.loc[leader_id], by_id.loc[follower_id]
        ready = [bus["prev_stop_observed"] for bus in (leader, follower) if bus["has_prev_stop"] == 1]
        if ready and max(ready) >= leader["observed_arrival"]:
            continue
        gap = (datetime.strptime(follower["observed_arrival"], TIME_FORMAT)
               - datetime.strptime(leader["observed_arrival"], TIME_FORMAT)).total_seconds() / 60
        headway = follower["headway_min"]
        persistence = pair_rule(persistence_class(leader), persistence_class(follower))
        answer = answers[follower_id]
        records.append({
            "leader_id": leader_id, "follower_id": follower_id, "route": follower["route"],
            "stop_id": follower["stop_id"], "service_date": follower["service_date"],
            "observed_gap_min": round(gap, 2), "headway_min": headway,
            "bunching": gap < config.BUNCH_FRAC * headway,
            "long_gap": gap > config.GAP_FRAC * headway,
            "persistence_bunching": persistence[0], "persistence_long_gap": persistence[1],
            "hybrid_bunching": answer["bunching_leader"] == leader_id,
            "hybrid_long_gap": answer["long_gap_leader"] == leader_id,
        })
    return pd.DataFrame(records, columns=[
        "leader_id", "follower_id", "route", "stop_id", "service_date", "observed_gap_min",
        "headway_min", "bunching", "long_gap", "persistence_bunching", "persistence_long_gap",
        "hybrid_bunching", "hybrid_long_gap"])


def pair_scores(pairs):
    """Precision and recall per event and system; left empty below MIN_EVENTS real events."""
    records = []
    for event in ("bunching", "long_gap"):
        truth = pairs[event].to_numpy(dtype=bool)
        flags = {"timetable": np.zeros(len(pairs), dtype=bool),
                 "persistence_pair": pairs["persistence_" + event].to_numpy(dtype=bool),
                 "hybrid": pairs["hybrid_" + event].to_numpy(dtype=bool)}
        enough = truth.sum() >= config.MIN_EVENTS
        for system, flagged in flags.items():
            hits = int((flagged & truth).sum())
            records.append({
                "event": event, "system": system, "pairs": len(pairs),
                "real_events": int(truth.sum()), "flagged": int(flagged.sum()), "hits": hits,
                "precision": hits / flagged.sum() if enough and flagged.any() else None,
                "recall": hits / truth.sum() if enough else None})
    return pd.DataFrame(records)


def pick_cases(rows, answers, pairs):
    """Picks the real test cases deterministically: [(name, row id, leader id or None)]."""
    argmax = ml_class(rows)
    actual = rows[TARGET].to_numpy()
    ordered = rows[PROB_COLUMNS].to_numpy()
    ordered.sort(axis=1)
    frame = rows.assign(argmax=argmax, top=ordered[:, -1], margin=ordered[:, -1] - ordered[:, -2],
                        correct=argmax == actual)

    def best(mask, column, largest=True):
        chosen = frame[mask].sort_values([column, "id"], ascending=[not largest, True])
        return None if chosen.empty else int(chosen["id"].iloc[0])

    vetoed_early = frame["id"].map(lambda key: answers[key]["early_vetoed"]) & (actual == "early")
    false_alarm = frame["id"].map(lambda key: "late" in answers[key]["warnings"]) \
        & (actual != "late") & frame["correct"]
    cases = [
        ("confident_correct", best(frame["correct"], "top")),
        ("confident_wrong", best(~frame["correct"], "top")),
        ("near_tie", best(frame["top"] > 0, "margin", largest=False)),
        ("missing_previous_stop", best(frame["has_prev_stop"] == 0, "p_late")),
        ("heaviest_rain", best(frame["top"] > 0, "precipitation_mm")),
        ("missed_early", best((actual == "early") & (argmax == "on_time"), "p_early")),
        ("rules_make_it_worse", best(vetoed_early, "p_early") or best(false_alarm, "p_late")),
    ]
    cases = [(name, key, None) for name, key in cases if key is not None]
    for column in ("hybrid_bunching", "bunching"):
        found = pairs[pairs[column]] if not pairs.empty else pairs
        if not found.empty:
            pair = found.iloc[0]
            cases.append(("bunching_pair", int(pair["follower_id"]), int(pair["leader_id"])))
            break
    return cases


def replay_time(row, leader=None):
    """A query time when every bus of the case was known but none had arrived."""
    times = [bus["prev_stop_observed"] for bus in (row, leader)
             if bus is not None and bus["has_prev_stop"] == 1]
    if times:
        return max(times)
    first = min(row["scheduled_arrival"], row["observed_arrival"])
    return (datetime.strptime(first, TIME_FORMAT) - timedelta(minutes=5)).strftime(TIME_FORMAT)


def case_record(name, kind, row, prediction, result, command=None, outcome=None, note=None):
    """The data of one case, as written to its JSON file."""
    return {"case": name, "kind": kind, "note": note, "reproduce": command,
            "input": {column: row[column] for column in
                      ["trip_id", "service_date", "scheduled_arrival"] + FEATURES},
            "ml_probabilities": {CLASS_OF[c]: round(float(prediction[c]), 3) for c in PROB_COLUMNS},
            "answer": {key: result[key] for key in
                       ("ml_class", "verdict", "confidence", "warnings", "guards", "action")},
            "trace": result["trace"], "outcome": outcome}


def case_markdown(number, record):
    """One case as a markdown page for the report."""
    lines = ["# Case %02d: %s (%s)" % (number, record["case"], record["kind"]), ""]
    if record["note"]:
        lines += [record["note"], ""]
    if record["reproduce"]:
        lines += ["Reproduce: `%s`" % record["reproduce"], ""]
    lines += ["## Input", "", "| field | value |", "|---|---|"]
    lines += ["| %s | %s |" % item for item in record["input"].items()]
    probabilities = record["ml_probabilities"]
    lines += ["", "## ML prediction", "",
              "early %.3f · on_time %.3f · late %.3f → **%s**"
              % (probabilities["early"], probabilities["on_time"], probabilities["late"],
                 record["answer"]["ml_class"]),
              "", "## Hybrid answer", ""]
    lines += ["- %s: %s" % item for item in record["answer"].items() if item[0] != "ml_class"]
    lines += ["", "## Reasoning trace", ""] + ["%d. %s" % (i, line) for i, line in
                                                enumerate(record["trace"], start=1)]
    if record["outcome"]:
        lines += ["", "## What actually happened", ""]
        lines += ["- %s: %s" % item for item in record["outcome"].items()]
    return "\n".join(lines) + "\n"


def real_cases(rows, answers, pairs, features, bundle, timepoints):
    """Replays each picked test row through the same path as `ask --at`."""
    by_id = rows.set_index("id")
    records = []
    for name, key, leader_key in pick_cases(rows, answers, pairs):
        row = by_id.loc[key]
        leader = by_id.loc[leader_key] if leader_key is not None else None
        at = replay_time(row, leader)
        seen = engine.rows_at(features, at, row["route"], row["stop_id"])
        predicted, replayed = engine.answer(seen, bundle, timepoints)
        match = predicted[(predicted["trip_id"] == row["trip_id"])
                          & (predicted["service_date"] == row["service_date"])].iloc[0]
        command = ('python -m hybrid_engine ask status %s %s --at "%s"'
                   % (row["route"], row["stop_id"], at))
        outcome = {"observed_arrival": row["observed_arrival"],
                   "delay_min": row["delay_min"], "delay_class": row[TARGET]}
        records.append(case_record(name, "real, test day", match, match,
                                   replayed[int(match["id"])], command, outcome))
    return records


def constructed_cases(rows, bundle, timepoints):
    """Cases with injected facts, for situations the stored data cannot show."""
    base = rows.sort_values("id").iloc[[0]].assign(id=1)
    route, stop = base["route"].iloc[0], base["stop_id"].iloc[0]
    variants = [
        ("unseen_stop", base.assign(stop_id="UNSEEN_STOP"), [],
         "Stop id changed to one the model never trained on."),
        ("outside_window", base.assign(window=None), [],
         "Scheduled outside every collection window, where there is no training data."),
    ]
    predicted = engine.predict(bundle, base)
    late_class = predicted["p_late"].iloc[0] >= predicted[["p_early", "p_on_time"]].max(axis=1).iloc[0]
    operator_delay = 0 if late_class else 8
    variants.append(("operator_disagrees_far_with_closure", base,
                     ["eta(1, %d, 6)." % operator_delay,
                      "alert('%s', closure, '%s')." % (route, stop)],
                     "Injected live facts: an operator estimate of %+d min that disagrees with "
                     "ML, 6 stops away, and a closure alert at the stop." % operator_delay))
    records = []
    for name, frame, extra, note in variants:
        predicted, answers = engine.answer(frame, bundle, timepoints, extra)
        records.append(case_record(name, "constructed, injected facts", predicted.iloc[0],
                                   predicted.iloc[0], answers[1], note=note))
    return records


def records(frame):
    """Rows as dicts, with missing values as None so the JSON stays valid."""
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def compare(features, bundle, timepoints, out_dir=config.HYBRID_VS_ML_DIR,
             resamples=config.BOOTSTRAP_RESAMPLES):
    """Runs every score and writes the outputs to out_dir.

    Returns:
        The summary dict that is also written to metrics.json.
    """
    _, test_rows = split_by_date(features)
    rows = test_rows.reset_index(drop=True).assign(id=lambda frame: frame.index + 1)
    rows, answers = engine.answer(rows, bundle, timepoints)

    safety = safety_table(rows, answers, resamples)
    confidence = confidence_table(rows, answers)
    pairs = bus_pairs(rows, answers)
    scores = pair_scores(pairs)
    cases = real_cases(rows, answers, pairs, features, bundle, timepoints) \
        + constructed_cases(rows, bundle, timepoints)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "cases").mkdir(parents=True)
    safety.to_csv(out_dir / "safety.csv", index=False)
    confidence.to_csv(out_dir / "confidence.csv", index=False)
    scores.to_csv(out_dir / "bunching.csv", index=False)
    pairs.to_csv(out_dir / "pairs.csv", index=False)
    for number, record in enumerate(cases, start=1):
        stem = out_dir / "cases" / ("%02d_%s" % (number, record["case"]))
        stem.with_suffix(".json").write_text(json.dumps(record, indent=2, default=str))
        stem.with_suffix(".md").write_text(case_markdown(number, record))

    warned = system_warnings(rows, answers)
    summary = {
        "limitation": LIMITATION,
        "test_dates": sorted(rows["service_date"].unique().tolist()),
        "test_rows": int(len(rows)),
        "thresholds": {"p_warn": config.P_WARN, "conf_medium": config.CONF_MEDIUM,
                       "bunch_frac": config.BUNCH_FRAC, "gap_frac": config.GAP_FRAC,
                       "min_events": config.MIN_EVENTS},
        "hybrid_equals_threshold": bool(
            (warned["hybrid"]["late"] == warned["ml_threshold"]["late"]).all()
            and (warned["hybrid"]["early"] == warned["ml_threshold"]["early"]).all()),
        "early_warnings_vetoed": int(sum(answer["early_vetoed"] for answer in answers.values())),
        "holds_vetoed": int(sum(answer["hold_vetoed"] for answer in answers.values())),
        "guards": {guard: int(sum(guard in answer["guards"] for answer in answers.values()))
                   for guard in ("no_previous_stop", "unseen_stop", "outside_window")},
        "safety": records(safety),
        "confidence": records(confidence),
        "bunching": records(scores),
        "cases": [record["case"] for record in cases],
    }
    (out_dir / "metrics.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def share(value):
    """A rate for printing, or "-" when there is none."""
    return "-" if value is None else "%.3f" % value


def print_summary(summary):
    """Prints the headline numbers."""
    print(summary["limitation"])
    print("\n%d test rows on %s" % (summary["test_rows"], ", ".join(summary["test_dates"])))
    print("\nwarnings (value [95%% interval]); P_WARN = %.2f" % config.P_WARN)
    for record in summary["safety"]:
        print("  %-13s %-18s %.3f [%.3f, %.3f]" % (record["system"], record["metric"],
                                                  record["value"], record["ci_low"],
                                                  record["ci_high"]))
    print("hybrid warnings identical to the plain threshold: %s"
          % summary["hybrid_equals_threshold"])
    print("early warnings vetoed at timing points: %d, holds vetoed: %d"
          % (summary["early_warnings_vetoed"], summary["holds_vetoed"]))
    print("\nconfidence (accuracy, coverage)")
    for record in summary["confidence"]:
        print("  %-20s %-6s %.3f  %.3f  (%d rows)" % (record["system"], record["level"],
                                                     record["accuracy"], record["coverage"],
                                                     record["rows"]))
    print("\nbus pairs (precision and recall only with at least %d real events)"
          % config.MIN_EVENTS)
    for record in summary["bunching"]:
        print("  %-8s %-16s real %d, flagged %d, hits %d, precision %s, recall %s"
              % (record["event"], record["system"], record["real_events"], record["flagged"],
                 record["hits"], share(record["precision"]), share(record["recall"])))
    print("\n%d cases: %s" % (len(summary["cases"]), ", ".join(summary["cases"])))


def main():
    """Compares the hybrid with ML alone on the test days."""
    conn = sqlite3.connect(config.DB_PATH)
    try:
        features = load_features(conn)
        timepoints = load_timepoints(conn)
    finally:
        conn.close()
    summary = compare(features, engine.load_model(), timepoints)
    print_summary(summary)
    print("\nsaved to %s" % config.HYBRID_VS_ML_DIR)


if __name__ == "__main__":
    main()
