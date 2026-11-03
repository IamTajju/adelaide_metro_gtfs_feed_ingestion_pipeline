# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         delay_model/scoring.py
# Date:         03-11-2026
# Description:  Metrics for the delay-class models and their CV summaries.
# Usage:        from delay_model.scoring import proba_metrics, score_model
"""Metrics for the delay-class models and their CV summaries.

Log-loss and Brier score rate the probabilities the Prolog layer reads;
macro-F1 and late recall rate the most likely class. Scikit-learn scorers
must be "higher is better", so score_model negates the losses and
summarise / best_summary turn them back positive.
"""

import numpy as np
from sklearn.metrics import f1_score, log_loss, recall_score

CLASSES = ["early", "on_time", "late"]
METRICS = ["log_loss", "brier", "macro_f1", "late_recall"]
LOSSES = {"log_loss", "brier"}  # Lower is better; scorers return them negated.


# --- Probability metrics --- #
def multiclass_log_loss(y_true, proba, classes):
    """Mean negative log of the probability given to the true class."""
    return float(log_loss(y_true, proba, labels=classes))


def multiclass_brier(y_true, proba, classes):
    """Mean squared distance between the one-hot truth and the probabilities."""
    truth = np.asarray(y_true)[:, None] == np.asarray(classes)[None, :]
    return float(np.mean(np.sum((truth - proba) ** 2, axis=1)))


# --- Label metrics --- #
def macro_f1(y_true, y_pred):
    """F1 averaged over the three classes, each counting equally."""
    return float(f1_score(y_true, y_pred, labels=CLASSES, average="macro", zero_division=0))


def late_recall(y_true, y_pred):
    """Share of the truly late buses that were predicted late."""
    return float(recall_score(y_true, y_pred, labels=["late"], average="macro",
                              zero_division=0))


# ---- Helper functions for scoring and summarising CV results --- #

def label_metrics(y_true, y_pred):
    """Macro-F1 and recall of "late" for predicted labels."""
    return {"macro_f1": macro_f1(y_true, y_pred),
            "late_recall": late_recall(y_true, y_pred)}


def proba_metrics(y_true, proba, classes):
    """Log-loss, Brier score and the label metrics of the most likely class."""
    pred = np.asarray(classes)[np.argmax(proba, axis=1)]
    return {"log_loss": multiclass_log_loss(y_true, proba, classes),
            "brier": multiclass_brier(y_true, proba, classes),
            "macro_f1": macro_f1(y_true, pred),
            "late_recall": late_recall(y_true, pred)}


def score_model(estimator, X, y):
    """Scorer for GridSearchCV and cross_validate: every metric, higher is better."""
    scores = proba_metrics(y, estimator.predict_proba(X), estimator.classes_)
    return {name: -value if name in LOSSES else value for name, value in scores.items()}


def summarise(scores):
    """Mean and spread of cross_validate scores, losses turned back positive."""
    summary = {}
    for name in METRICS:
        values = np.asarray(scores["test_" + name])
        values = -values if name in LOSSES else values
        summary[name] = {"mean": float(values.mean()), "sd": float(values.std())}
    return summary


def best_summary(search):
    """CV mean and spread of a search's best configuration."""
    results, index = search.cv_results_, search.best_index_
    summary = {}
    for name in METRICS:
        mean = results["mean_test_" + name][index]
        summary[name] = {"mean": float(-mean if name in LOSSES else mean),
                         "sd": float(results["std_test_" + name][index])}
    return summary
