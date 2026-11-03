# Student Name: Mauro Turci
# Student FAN:  turc0022
# File:         delay_model/train.py
# Date:         01-11-2026
# Description:  Trains, compares and saves the delay-class models.
# Usage:        python -m delay_model [--quick]
"""Trains, compares and saves the delay-class models.

Reads the delay_features table and predicts early / on_time / late. The
last TEST_DAYS service dates are held out and scored once; the rest is
cross-validated in folds grouped by date, because buses on the same day
share weather and incidents.

Compared: two baselines (class priors, and "same class as the previous
stop" as a rule and as a logistic regression on that delay alone) and three
tuned models (logistic regression, random forest, gradient boosting) with
small fixed grids. The winner has the lowest mean CV log-loss, because the
Prolog layer reads its probabilities; no class weights are used for the
same reason. Sigmoid calibration is kept only if it lowers CV log-loss.

Everything lands in MODELS_DIR: model.joblib, metrics.json, cv_results.csv,
lr_coefficients.csv, permutation_importance.csv and reliability.png.
docs/A2_FEATURE_DECISIONS.md explains each choice.
"""

import argparse
import json
import sqlite3

import joblib
import matplotlib
matplotlib.use("Agg")  # Write PNGs only; no window.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import (GridSearchCV, StratifiedGroupKFold,
                                     cross_validate)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from delay_features.main import delay_class
from delay_model.scoring import (CLASSES, LOSSES, METRICS, best_summary, label_metrics,
                                 multiclass_log_loss, proba_metrics, score_model, summarise)
from shared import config

CATEGORICAL = ["route", "stop_id", "quadrant", "window", "day_type"]
NUMERIC = ["headway_min", "prev_stop_delay_min", "precipitation_mm"]
FLAG = ["has_prev_stop"]
FEATURES = CATEGORICAL + NUMERIC + FLAG
TARGET = "delay_class"
SEED = 42


def preprocessor(categorical=CATEGORICAL, numeric=NUMERIC, flag=FLAG):
    """One-hot categories, scaled numbers, the flag passed through as 0/1."""
    return ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
        ("numeric", StandardScaler(), numeric),
        ("flag", "passthrough", flag)])


def candidate_models(quick=False):
    """Returns {name: (pipeline, grid)} for the three tuned models.

    Args:
        quick: Keep only the first value of every grid, for dry runs.
    """
    models = {
        "logistic_regression": (
            LogisticRegression(max_iter=2000),
            {"model__C": [0.01, 0.1, 1, 10]}),
        "random_forest": (
            RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1),
            {"model__max_depth": [6, None], "model__min_samples_leaf": [5, 20, 50],
             "model__max_features": ["sqrt", 0.5]}),
        # Early stopping would hold out random rows, mixing days across the split.
        "gradient_boosting": (
            HistGradientBoostingClassifier(early_stopping=False, l2_regularization=1.0,
                                           random_state=SEED),
            {"model__learning_rate": [0.05, 0.1], "model__max_iter": [100, 300],
             "model__max_leaf_nodes": [7, 15], "model__min_samples_leaf": [20, 50]}),
    }
    result = {}
    for name, (estimator, grid) in models.items():
        if quick:
            grid = {key: values[:1] for key, values in grid.items()}
        result[name] = (Pipeline([("prepare", preprocessor()), ("model", estimator)]), grid)
    return result


def baseline_models():
    """Returns {name: pipeline} for the two probabilistic baselines."""
    return {
        "most_common_class": Pipeline([("prepare", preprocessor()),
                                       ("model", DummyClassifier(strategy="prior"))]),
        # "Same as the previous stop", with probabilities, so it can be
        # compared on log-loss and Brier as well.
        "persistence_lr": Pipeline([("prepare", preprocessor([], ["prev_stop_delay_min"])),
                                    ("model", LogisticRegression(max_iter=2000))]),
    }


def persistence_rule(frame, fallback):
    """Predicts the previous stop's class, or fallback where there is none."""
    previous = frame["prev_stop_delay_min"].map(delay_class)
    return np.where(frame["has_prev_stop"] == 1, previous, fallback)


def load_features(conn):
    """Reads the delay_features table."""
    return pd.read_sql_query("SELECT * FROM delay_features", conn)


def split_by_date(frame, test_days=config.TEST_DAYS):
    """Holds out the last test_days service dates as the test set.

    Raises:
        RuntimeError: if there are not more dates than test_days.
    """
    dates = sorted(frame["service_date"].unique())
    if len(dates) <= test_days:
        raise RuntimeError("only %d service dates; need more than %d to hold out a test set"
                           % (len(dates), test_days))
    is_test = frame["service_date"].isin(dates[-test_days:])
    return frame[~is_test].reset_index(drop=True), frame[is_test].reset_index(drop=True)


def date_folds(train, folds=(config.CV_FOLDS, config.FALLBACK_FOLDS),
               min_late=config.MIN_LATE_PER_FOLD):
    """Builds CV splits grouped by date and stratified by class.

    Tries each fold count in turn and keeps the first where every validation
    fold holds at least min_late late rows. If none does, the last one is
    used with a warning, so a dry run on little data still finishes.

    Returns:
        Tuple (list of (train_index, validation_index), late rows per fold).

    Raises:
        RuntimeError: if there are fewer dates than the smallest fold count.
    """
    dates = train["service_date"].nunique()
    if dates < min(folds):
        raise RuntimeError("only %d training dates; need at least %d for CV"
                           % (dates, min(folds)))
    for n_splits in folds:
        if dates < n_splits:
            continue
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
        splits = list(splitter.split(train, train[TARGET], train["service_date"]))
        lates = [int((train[TARGET].iloc[val] == "late").sum()) for _, val in splits]
        if min(lates) >= min_late:
            return splits, lates
    print("WARNING: a CV fold holds only %d late rows (want %d); scores will be noisy"
          % (min(lates), min_late))
    return splits, lates


def cross_validate_baselines(train, splits):
    """CV scores of the baselines on the same folds as the tuned models."""
    X, y = train[FEATURES], train[TARGET]
    summary = {name: summarise(cross_validate(model, X, y, cv=splits, scoring=score_model))
               for name, model in baseline_models().items()}
    rule = {name: [] for name in ("macro_f1", "late_recall")}
    for fit_index, val_index in splits:
        fallback = y.iloc[fit_index].mode()[0]
        scores = label_metrics(y.iloc[val_index], persistence_rule(train.iloc[val_index], fallback))
        for name, value in scores.items():
            rule[name].append(value)
    summary["persistence_rule"] = {name: {"mean": float(np.mean(values)),
                                          "sd": float(np.std(values))}
                                   for name, values in rule.items()}
    return summary


def tune_models(train, splits, quick=False):
    """Grid-searches the three models; refits each best on all training rows.

    Returns:
        Tuple ({name: fitted GridSearchCV}, DataFrame of every configuration).
    """
    X, y = train[FEATURES], train[TARGET]
    searches, tables = {}, []
    for name, (pipeline, grid) in candidate_models(quick).items():
        search = GridSearchCV(pipeline, grid, scoring=score_model, refit="log_loss",
                              cv=splits, n_jobs=-1)
        search.fit(X, y)
        searches[name] = search
        table = pd.DataFrame(search.cv_results_)
        keep = ["params"] + ["mean_test_" + m for m in METRICS] + ["std_test_" + m for m in METRICS]
        table = table[keep].assign(model=name)
        for metric in LOSSES:
            table["mean_test_" + metric] = -table["mean_test_" + metric]
        tables.append(table)
    return searches, pd.concat(tables, ignore_index=True)


def choose_calibration(estimator, train, splits):
    """Compares the winner raw and sigmoid-calibrated on CV log-loss.

    Returns:
        Tuple (unfitted estimator to keep, dict of both CV log-losses).
    """
    X, y = train[FEATURES], train[TARGET]
    calibrated = CalibratedClassifierCV(clone(estimator), method="sigmoid", cv=3)
    raw_loss = summarise(cross_validate(clone(estimator), X, y, cv=splits,
                                        scoring=score_model))["log_loss"]["mean"]
    calibrated_loss = summarise(cross_validate(calibrated, X, y, cv=splits,
                                               scoring=score_model))["log_loss"]["mean"]
    choice = calibrated if calibrated_loss < raw_loss else clone(estimator)
    return choice, {"raw_log_loss": raw_loss, "sigmoid_log_loss": calibrated_loss,
                    "calibrated": bool(calibrated_loss < raw_loss)}


def bootstrap_intervals(test, proba, classes, baseline_proba, baseline_classes,
                        resamples=config.BOOTSTRAP_RESAMPLES):
    """95% intervals of the test metrics, resampling whole trips (trip + date).

    The gain is the persistence-LR log-loss minus the model's log-loss, so a
    positive gain means the model beats the baseline.
    """
    rng = np.random.default_rng(SEED)
    groups = list(test.groupby(["trip_id", "service_date"]).indices.values())
    y = test[TARGET].to_numpy()
    draws = {name: [] for name in METRICS + ["log_loss_gain"]}
    for _ in range(resamples):
        rows = np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))])
        scores = proba_metrics(y[rows], proba[rows], classes)
        for name, value in scores.items():
            draws[name].append(value)
        baseline = multiclass_log_loss(y[rows], baseline_proba[rows], baseline_classes)
        draws["log_loss_gain"].append(baseline - scores["log_loss"])
    return {name: [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
            for name, values in draws.items()}


def evaluate_test(model, baselines, train, test, resamples=config.BOOTSTRAP_RESAMPLES):
    """Scores the final model and the baselines once on the held-out days."""
    X, y = test[FEATURES], test[TARGET]
    proba = model.predict_proba(X)
    persistence = baselines["persistence_lr"]
    persistence_proba = persistence.predict_proba(X)
    fallback = train[TARGET].mode()[0]
    result = {
        "rows": int(len(test)),
        "model": proba_metrics(y, proba, model.classes_),
        "intervals_95": bootstrap_intervals(test, proba, model.classes_, persistence_proba,
                                            persistence.classes_, resamples),
        "confusion_matrix": {"labels": CLASSES, "rows_true_cols_predicted": confusion_matrix(
            y, model.classes_[np.argmax(proba, axis=1)], labels=CLASSES).tolist()},
        "baselines": {name: proba_metrics(y, base.predict_proba(X), base.classes_)
                      for name, base in baselines.items()},
        "by_has_prev_stop": {},
    }
    result["baselines"]["persistence_rule"] = label_metrics(y, persistence_rule(test, fallback))
    result["model"]["accuracy"] = float(accuracy_score(y, model.classes_[np.argmax(proba, axis=1)]))
    for flag in (0, 1):
        part = test[test["has_prev_stop"] == flag]
        if part.empty:
            continue
        result["by_has_prev_stop"][str(flag)] = {
            "rows": int(len(part)),
            "model": proba_metrics(part[TARGET], model.predict_proba(part[FEATURES]),
                                   model.classes_),
            "persistence_lr": proba_metrics(part[TARGET],
                                            persistence.predict_proba(part[FEATURES]),
                                            persistence.classes_),
            "persistence_rule": label_metrics(part[TARGET], persistence_rule(part, fallback)),
        }
    return result


def lr_coefficients(search):
    """Coefficients of the tuned logistic regression, one column per class."""
    pipeline = search.best_estimator_
    names = pipeline.named_steps["prepare"].get_feature_names_out()
    model = pipeline.named_steps["model"]
    return pd.DataFrame(model.coef_.T, index=names, columns=model.classes_)


def gb_permutation_importance(search, test):
    """Rise in test log-loss when each input of the boosted model is shuffled."""
    importance = permutation_importance(
        search.best_estimator_, test[FEATURES], test[TARGET],
        scoring=lambda est, X, y: score_model(est, X, y)["log_loss"],
        n_repeats=10, random_state=SEED)
    return pd.DataFrame({"feature": FEATURES, "mean_loss_increase": importance.importances_mean,
                         "sd": importance.importances_std}).sort_values(
                             "mean_loss_increase", ascending=False)


def plot_reliability(model, test, path):
    """One-vs-rest reliability curves of the final model on the test days."""
    proba = model.predict_proba(test[FEATURES])
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="perfect")
    for index, name in enumerate(model.classes_):
        hit = (test[TARGET] == name).to_numpy()
        if hit.all() or not hit.any():
            continue
        observed, predicted = calibration_curve(hit, proba[:, index], n_bins=10,
                                                strategy="quantile")
        ax.plot(predicted, observed, marker="o", label=name)
    ax.set_xlabel("predicted probability")
    ax.set_ylabel("observed share")
    ax.set_title("Reliability on the test days")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def train(features, out_dir=config.MODELS_DIR, quick=False,
          resamples=config.BOOTSTRAP_RESAMPLES):
    """Runs the whole comparison and writes every output to out_dir.

    Args:
        features: DataFrame of the delay_features table.
        out_dir: Folder for the model, metrics, tables and plot.
        quick: One configuration per model, for dry runs.
        resamples: Bootstrap resamples for the test-set intervals.

    Returns:
        The metrics dict that is also written to metrics.json.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    train_rows, test_rows = split_by_date(features)
    splits, fold_lates = date_folds(train_rows)
    searches, cv_table = tune_models(train_rows, splits, quick)
    cv_summary = cross_validate_baselines(train_rows, splits)
    cv_summary.update({name: best_summary(search) for name, search in searches.items()})

    winner = min(searches, key=lambda name: cv_summary[name]["log_loss"]["mean"])
    final, calibration = choose_calibration(searches[winner].best_estimator_, train_rows, splits)
    final.fit(train_rows[FEATURES], train_rows[TARGET])
    baselines = {name: model.fit(train_rows[FEATURES], train_rows[TARGET])
                 for name, model in baseline_models().items()}

    metrics = {
        "rows": {"train": int(len(train_rows)), "test": int(len(test_rows))},
        "dates": {"train": sorted(train_rows["service_date"].unique().tolist()),
                  "test": sorted(test_rows["service_date"].unique().tolist())},
        "class_counts": {"train": train_rows[TARGET].value_counts().to_dict(),
                         "test": test_rows[TARGET].value_counts().to_dict()},
        "cv_folds": len(splits),
        "late_rows_per_fold": fold_lates,
        "cv": cv_summary,
        "best_params": {name: search.best_params_ for name, search in searches.items()},
        "winner": winner,
        "calibration": calibration,
        "test": evaluate_test(final, baselines, train_rows, test_rows, resamples),
    }
    joblib.dump({"model": final, "name": winner, "classes": list(final.classes_),
                 "features": FEATURES, "calibrated": calibration["calibrated"],
                 "train_dates": metrics["dates"]["train"],
                 "seen_stops": sorted(train_rows["stop_id"].unique().tolist())},
                out_dir / "model.joblib")
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    cv_table.to_csv(out_dir / "cv_results.csv", index=False)
    lr_coefficients(searches["logistic_regression"]).to_csv(out_dir / "lr_coefficients.csv")
    gb_permutation_importance(searches["gradient_boosting"], test_rows).to_csv(
        out_dir / "permutation_importance.csv", index=False)
    plot_reliability(final, test_rows, out_dir / "reliability.png")
    return metrics


def print_summary(metrics):
    """Prints the CV comparison and the test result."""
    print("%d train rows (%d dates), %d test rows (%d dates), %d CV folds, late per fold %s"
          % (metrics["rows"]["train"], len(metrics["dates"]["train"]), metrics["rows"]["test"],
             len(metrics["dates"]["test"]), metrics["cv_folds"], metrics["late_rows_per_fold"]))
    print("\nCV (mean ± sd)      log_loss       brier          macro_f1       late_recall")
    for name, scores in metrics["cv"].items():
        cells = ["%.3f ± %.3f" % (scores[m]["mean"], scores[m]["sd"]) if m in scores
                 else "      -      " for m in METRICS]
        print("%-19s %s" % (name, "  ".join(cells)))
    test = metrics["test"]
    print("\nwinner: %s (%s)" % (metrics["winner"], "sigmoid-calibrated"
                                 if metrics["calibration"]["calibrated"] else "raw"))
    for name in METRICS:
        low, high = test["intervals_95"][name]
        print("test %-12s %.3f  [%.3f, %.3f]" % (name, test["model"][name], low, high))
    low, high = test["intervals_95"]["log_loss_gain"]
    print("log-loss gain over persistence_lr: %.3f  [%.3f, %.3f]"
          % (test["baselines"]["persistence_lr"]["log_loss"] - test["model"]["log_loss"],
             low, high))


def main(argv=None):
    """Trains on the delay_features table and saves the results."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="one configuration per model, to check the pipeline end to end")
    args = parser.parse_args(argv)
    conn = sqlite3.connect(config.DB_PATH)
    try:
        features = load_features(conn)
    finally:
        conn.close()
    metrics = train(features, quick=args.quick)
    print_summary(metrics)
    print("\nsaved to %s" % config.MODELS_DIR)


if __name__ == "__main__":
    main()
