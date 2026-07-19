"""Backup / restore disaster-recovery tests.

Covers the audit gaps vs the sibling bot:
  * backup is consistent (Online Backup API, not a raw copy)
  * backup passes PRAGMA integrity_check
  * restore is a faithful round-trip (data survives)
  * corrupt backups are refused on restore
  * per-category retention trims old files
"""

import os
import sqlite3

import pytest

from db_backup import (
    create_backup,
    restore_backup,
    verify_backup,
)


@pytest.fixture()
def live_db(tmp_path, monkeypatch):
    """Point the module at a temp live DB with known data, return its path."""
    db_path = tmp_path / "bot.db"
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, city TEXT, amount REAL)")
    con.execute("INSERT INTO trades (city, amount) VALUES ('Ankara', 12.5)")
    con.execute("INSERT INTO trades (city, amount) VALUES ('Oslo', 7.0)")
    con.commit()
    con.close()

    monkeypatch.setattr("db_backup.DB_PATH", str(db_path))
    monkeypatch.setattr("db_backup.DB_DIR", str(tmp_path))
    monkeypatch.setattr("db_backup.BACKUP_DIR", str(tmp_path / "backups"))
    import db_backup as _dbmod

    monkeypatch.setattr(_dbmod, "BACKUP_DIR", str(tmp_path / "backups"))
    return str(db_path)


def _row_count(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    finally:
        con.close()


def test_backup_is_created_and_verified(live_db):
    path = create_backup("startup")
    assert path is not None
    assert os.path.exists(path)
    assert verify_backup(path) is True  # passes integrity_check


def test_restore_round_trip(live_db):
    path = create_backup("startup")
    assert path is not None

    # Mutate the live DB, then restore from backup and confirm data returns.
    con = sqlite3.connect(f"file:{live_db}?mode=rwc", uri=True)
    con.execute("DELETE FROM trades")
    con.commit()
    con.close()
    assert _row_count(live_db) == 0

    assert restore_backup(path) is True
    assert _row_count(live_db) == 2


def test_corrupt_backup_refused(live_db):
    path = create_backup("startup")
    assert path is not None
    # Scramble the backup file.
    with open(path, "wb") as fh:
        fh.write(b"not a sqlite database at all")
    assert verify_backup(path) is False
    # Restore must refuse a corrupt backup rather than clobber the live DB.
    before = _row_count(live_db)
    assert restore_backup(path) is False
    assert _row_count(live_db) == before


def test_per_category_retention(live_db, monkeypatch):
    import db_backup as _dbmod

    monkeypatch.setattr("db_backup.MAX_BACKUPS_PER_CATEGORY", 3)
    for i in range(6):
        create_backup("scheduled")
    cat_files = [f for f in os.listdir(_dbmod.BACKUP_DIR) if f.startswith("bot_scheduled_") and f.endswith(".db")]
    assert len(cat_files) == 3  # oldest 3 trimmed, newest 3 kept


def test_offsite_copy_to_separate_directory(live_db, tmp_path, monkeypatch):
    import db_backup as _dbmod

    offsite = tmp_path / "offsite"
    monkeypatch.setattr(_dbmod, "OFFSITE_DIR", str(offsite))
    monkeypatch.setattr("db_backup.OFFSITE_DIR", str(offsite))

    path = create_backup("startup")
    assert path is not None

    gz_files = [f for f in os.listdir(offsite) if f.endswith(".db.gz")]
    assert len(gz_files) == 1  # latest compressed backup copied offsite
    assert os.path.exists(os.path.join(str(offsite), gz_files[0]))
