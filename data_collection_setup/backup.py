# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         data_collection_setup/backup.py
# Date:         21-10-2026
# Description:  Copies data/gtfs.db to a dated backup file, safely while the collector writes.
# Usage:        python -m data_collection_setup.backup [DEST_DIR]
"""Copies data/gtfs.db to a dated backup file, safely while the collector writes.

Uses SQLite's backup API, not a file copy, so the backup is consistent even
mid-write. DEST_DIR defaults to data/backups; point it at another disk or a
synced folder (Dropbox, OneDrive, iCloud Drive) so the live data survives
losing this computer.
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from shared import config


def backup_database(dest_dir, db_path=config.DB_PATH):
    """Writes <dest_dir>/gtfs-YYYY-MM-DD.db (replacing today's if it exists).

    Returns:
        Path of the backup file.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / ("gtfs-%s.db" % datetime.now().strftime("%Y-%m-%d"))
    source, dest = sqlite3.connect(db_path), sqlite3.connect(dest_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return dest_path


def main():
    dest_dir = sys.argv[1] if len(sys.argv) > 1 else config.DATA_DIR / "backups"
    print("backed up to", backup_database(dest_dir))


if __name__ == "__main__":
    main()
