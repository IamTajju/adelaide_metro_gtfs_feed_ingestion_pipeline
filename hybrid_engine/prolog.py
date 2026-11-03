# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         hybrid_engine/prolog.py
# Date:         01-11-2026
# Description:  Runs reasoner/rules.pl on a batch of facts and reads the answers.
# Usage:        from hybrid_engine.prolog import run_rules
"""Runs reasoner/rules.pl on a batch of facts and reads the answers.

One swipl process per batch: the facts go to a temporary file, and
reasoner/run.pl prints one JSON answer per row.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from shared import config

RUN_PL = config.ROOT / "reasoner" / "run.pl"


def run_rules(fact_lines):
    """Answers every row in the facts.

    Args:
        fact_lines: Prolog clause lines, as facts.build_facts returns them.

    Returns:
        Dict of row id to its answer (ml_class, verdict, confidence,
        warnings, guards, early_vetoed, bunching_leader, long_gap_leader,
        hold_vetoed, action and trace).

    Raises:
        RuntimeError: if swipl is missing or the rules fail.
    """
    swipl = shutil.which("swipl")
    if swipl is None:
        raise RuntimeError("swipl not found; install SWI-Prolog")
    with tempfile.TemporaryDirectory() as folder:
        facts_file = Path(folder) / "facts.pl"
        facts_file.write_text("\n".join(fact_lines) + "\n")
        done = subprocess.run([swipl, "-q", "-g", "main", "-t", "halt", str(RUN_PL),
                               "--", str(facts_file)],
                              capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("Prolog failed:\n" + done.stderr)
    return {answer["id"]: answer for answer in json.loads(done.stdout)}
