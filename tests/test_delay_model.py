# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         tests/test_delay_model.py
# Date:         01-11-2026
# Description:  Tests for training and comparing the delay-class models.
# Usage:        python -m pytest tests
"""Tests for training and comparing the delay-class models."""

import json
from datetime import date, timedelta

import joblib
import numpy as np
import pandas as pd
import pytest

from delay_features.main import delay_class
from delay_model.scoring import CLASSES, multiclass_brier
from delay_model.train import FEATURES, date_folds, persistence_rule, split_by_date, train


def synthetic_features(days=12, rows_per_day=80, seed=0):
    """A delay_features-shaped frame where delay mostly carries forward."""
    rng = np.random.default_rng(seed)
    rows = []
    for offset in range(days):
        day = (date(2026, 10, 20) + timedelta(days=offset)).isoformat()
        rain = rng.choice([0.0, 0.0, 2.0])
        for index in range(rows_per_day):
            has_prev = int(rng.random() < 0.65)
            prev = float(rng.normal(2, 3)) if has_prev else 0.0
            delay = 0.8 * prev + rng.normal(1, 2.5) + rain
            rows.append({
                "trip_id": "T%d" % (index // 3), "stop_id": "S%d" % (index % 3),
                "service_date": day, "route": rng.choice(["G10", "300", "H30"]),
                "quadrant": rng.choice(list("NESW")), "window": rng.choice(["am", "midday", "pm"]),
                "day_type": "weekend" if offset % 7 in (5, 6) else "weekday",
                "headway_min": float(rng.choice([7.5, 15.0, 30.0])),
                "prev_stop_delay_min": prev, "has_prev_stop": has_prev,
                "precipitation_mm": rain, "delay_min": delay, "delay_class": delay_class(delay)})
    return pd.DataFrame(rows)


def test_multiclass_brier():
    proba = np.array([[1.0, 0.0, 0.0], [0.5, 0.5, 0.0]])
    assert multiclass_brier(["a", "b"], proba, ["a", "b", "c"]) == pytest.approx(0.25)


def test_persistence_rule_uses_the_previous_stop_or_the_fallback():
    frame = pd.DataFrame({"prev_stop_delay_min": [7.0, -3.0, 0.0],
                          "has_prev_stop": [1, 1, 0]})
    assert list(persistence_rule(frame, "on_time")) == ["late", "early", "on_time"]


def test_split_holds_out_the_last_dates():
    features = synthetic_features(days=6, rows_per_day=5)
    train_rows, test_rows = split_by_date(features, test_days=2)
    assert sorted(test_rows["service_date"].unique()) == ["2026-10-24", "2026-10-25"]
    assert not set(train_rows["service_date"]) & set(test_rows["service_date"])


def test_split_needs_more_dates_than_the_test_days():
    with pytest.raises(RuntimeError, match="service dates"):
        split_by_date(synthetic_features(days=3, rows_per_day=5), test_days=3)


def test_folds_keep_each_date_on_one_side():
    train_rows, _ = split_by_date(synthetic_features())
    splits, lates = date_folds(train_rows)
    assert len(splits) == len(lates)
    for fit_index, val_index in splits:
        fit_dates = set(train_rows["service_date"].iloc[fit_index])
        assert not fit_dates & set(train_rows["service_date"].iloc[val_index])


def test_folds_fall_back_when_late_rows_are_thin():
    train_rows, _ = split_by_date(synthetic_features())
    splits, lates = date_folds(train_rows, folds=(5, 3), min_late=10**6)
    assert len(splits) == 3  # Neither count meets the minimum: warn, keep the last.


def test_train_writes_every_output(tmp_path):
    metrics = train(synthetic_features(), out_dir=tmp_path, quick=True, resamples=50)

    for name in ("model.joblib", "metrics.json", "cv_results.csv", "lr_coefficients.csv",
                 "permutation_importance.csv", "reliability.png"):
        assert (tmp_path / name).exists(), name
    assert json.loads((tmp_path / "metrics.json").read_text())["winner"] == metrics["winner"]

    assert metrics["winner"] in ("logistic_regression", "random_forest", "gradient_boosting")
    for name in ("most_common_class", "persistence_lr", "persistence_rule",
                 "logistic_regression", "random_forest", "gradient_boosting"):
        assert name in metrics["cv"]
    test = metrics["test"]
    assert test["intervals_95"]["log_loss"][0] <= test["model"]["log_loss"] \
        <= test["intervals_95"]["log_loss"][1]
    assert set(test["by_has_prev_stop"]) == {"0", "1"}

    saved = joblib.load(tmp_path / "model.joblib")
    assert saved["features"] == FEATURES and set(saved["classes"]) == set(CLASSES)
    proba = saved["model"].predict_proba(synthetic_features(days=1, rows_per_day=4)[FEATURES])
    assert np.allclose(proba.sum(axis=1), 1.0)
