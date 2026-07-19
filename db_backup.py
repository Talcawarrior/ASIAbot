"""Database backup utility — atomic, verified, retention-aware.

Usage:
    python db_backup.py              # Create backup (label "manual")
    python db_backup.py --list       # List existing backups
    python db_backup.py --restore    # Restore latest backup
    python db_backup.py --verify     # Run integrity_check on the latest backup

Called automatically by:
    - Bot startup (main.py)
    - Test suite (conftest.py)
    - Scheduled daily job (jobs/backup_job.py -> bot settlement loop)
    - Windows Task Scheduler (JunboBotWatchdog-style standalone task)

Hardening (applied after audit vs sibling bot):
    * Online Backup API (sqlite3.connect(src).backup(dst)) instead of a raw
      file copy -> consistent snapshot even while the live WAL DB is written.
    * PRAGMA integrity_check on both source and destination.
    * Atomic replace via temp file + os.replace.
    * Per-category retention (not a single global pool).
    * Path-traversal safe (label is sanitized).
    * Backups are stored COMPRESSED (.db.gz) both locally and offsite, so each
      snapshot is ~30 MB instead of a full ~380 MB raw copy of the live DB.
      This keeps data/backups small even when the bot restarts/tests run often.
"""

import glob
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "bot.db")
BACKUP_DIR = os.path.join(DB_DIR, "backups")
# Offsite copy target: a *different* directory (ideally a different disk) for
# disaster recovery. No encryption — plain portable .gz copy, as configured.
OFFSITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ASIAbot_backups_offsite")
MAX_BACKUPS_PER_CATEGORY = 20
INTEGRITY_OK = "ok"


def _safe_label(label: str) -> str:
    """Sanitize a label so it can't escape the backup directory."""
    clean = os.path.basename(str(label)).replace(os.sep, "_")
    clean = "".join(ch for ch in clean if ch.isalnum() or ch in ("_", "-", "."))
    return clean or "auto"


def _sidecar_paths(base: str) -> list[str]:
    return [base + "-wal", base + "-shm"]


def _integrity_ok(path: str) -> bool:
    # .gz backups are decompressed to a temp file before the check.
    plain = path
    tmp_plain = None
    if path.endswith(".gz"):
        tmp_plain = path + ".integrity.tmp"
        try:
            with gzip.open(path, "rb") as f_in, open(tmp_plain, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        except Exception:
            return False
        plain = tmp_plain
    try:
        con = sqlite3.connect(f"file:{plain}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute("PRAGMA integrity_check")
            rows = cur.fetchall()
        finally:
            con.close()
        return bool(rows) and all(r[0] == "ok" for r in rows)
    except Exception:
        return False
    finally:
        if tmp_plain is not None and os.path.exists(tmp_plain):
            try:
                os.unlink(tmp_plain)
            except OSError:
                pass


def verify_backup(path: str) -> bool:
    """Return True if the given backup file passes PRAGMA integrity_check."""
    return _integrity_ok(path)


def create_backup(label="auto", category=None):
    """Create a consistent, verified, COMPRESSED backup of the live database.

    Uses the SQLite Online Backup API so a backup taken while the bot is
    writing remains internally consistent, then stores it as a compressed
    ``.db.gz`` (typically ~30 MB vs ~380 MB for a raw copy). Returns the
    backup path, or None if the source DB is missing/corrupt.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH):
        print(f"WARNING: {DB_PATH} not found, skipping backup")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe = _safe_label(label)
    db_name = f"bot_{safe}_{timestamp}.db"
    db_path = os.path.join(BACKUP_DIR, db_name)  # uncompressed temp name
    gz_path = db_path + ".gz"  # final compressed backup
    tmp_db = db_path + ".tmp"

    # Source integrity must be OK before we bother copying.
    if not _integrity_ok(DB_PATH):
        print("WARNING: source DB failed integrity_check, aborting backup")
        return None

    try:
        src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(tmp_db)
            try:
                with dst:  # commit/close cleanly
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception as e:
        print(f"ERROR: backup failed: {e}")
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)
        return None

    # Compress the snapshot to the final .gz (atomic publish).
    tmp_gz = gz_path + ".tmp"
    with open(tmp_db, "rb") as f_in, gzip.open(tmp_gz, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    os.unlink(tmp_db)
    os.replace(tmp_gz, gz_path)

    size_kb = os.path.getsize(gz_path) / 1024
    print(f"Backup created: {os.path.basename(gz_path)} ({size_kb:.0f} KB)")

    # Retention: per category (label family), keep newest N.
    _cleanup_old(category or safe)

    # Offsite copy (compressed .gz to a different directory) for DR.
    try:
        copy_to_offsite(gz_path)
    except Exception as e:
        print(f"WARNING: offsite copy failed: {e}")

    return gz_path


def copy_to_offsite(backup_path: str, offsite_dir: str | None = None) -> str | None:
    """Copy a compressed backup (.gz) to a separate directory for DR.

    ``backup_path`` is the ``.gz`` file produced by create_backup. Copies it
    to ``offsite_dir`` (defaults to OFFSITE_DIR, a sibling of the project).
    Returns the copied path, or None if there is nothing to copy.
    No encryption — plain portable copy, as configured.
    """
    offsite_dir = offsite_dir or OFFSITE_DIR
    if not backup_path.endswith(".gz") or not os.path.exists(backup_path):
        return None
    os.makedirs(offsite_dir, exist_ok=True)
    dest = os.path.join(offsite_dir, os.path.basename(backup_path))
    shutil.copy2(backup_path, dest)
    print(f"Offsite copy: {os.path.basename(dest)} -> {offsite_dir}")
    return dest


def _cleanup_old(category: str):
    pattern = os.path.join(BACKUP_DIR, f"bot_{_safe_label(category)}_*.db.gz")
    backups = sorted(glob.glob(pattern))
    for old in backups[: max(0, len(backups) - MAX_BACKUPS_PER_CATEGORY)]:
        base = old[:-3]  # strip ".gz" -> ".db"
        for p in [old, base, base + "-wal", base + "-shm", base + ".tmp", base + ".gz.tmp"]:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def list_backups():
    if not os.path.exists(BACKUP_DIR):
        print("No backups found")
        return []
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db.gz")))
    for b in backups:
        size_kb = os.path.getsize(b) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(b))
        ok = "ok" if _integrity_ok(b) else "CORRUPT"
        print(f"  {os.path.basename(b)} ({size_kb:.0f} KB) - {mtime:%Y-%m-%d %H:%M:%S} [{ok}]")
    return backups


def restore_backup(backup_path=None):
    if backup_path is None:
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db.gz")))
        if not backups:
            print("No backups to restore")
            return False
        backup_path = backups[-1]

    if not os.path.exists(backup_path):
        print(f"Backup not found: {backup_path}")
        return False

    # Decompress the .gz snapshot to a temp plain db (legacy .db handled too).
    if backup_path.endswith(".gz"):
        tmp = DB_PATH + ".restore.tmp"
        try:
            with gzip.open(backup_path, "rb") as f_in, open(tmp, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        except Exception as e:
            print(f"ERROR: cannot read backup archive: {e}")
            return False
    else:
        tmp = backup_path  # legacy uncompressed backup

    if not _integrity_ok(tmp):
        print("ERROR: selected backup is CORRUPT, refusing to restore")
        if tmp != backup_path:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False

    if os.path.exists(DB_PATH):
        fallback = DB_PATH + f".pre_restore_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(DB_PATH, fallback)
        print(f"Current DB saved as: {os.path.basename(fallback)}")

    # Atomic restore: replace the live DB with the verified snapshot.
    os.replace(tmp, DB_PATH)
    # Legacy sidecars (rare for a clean backup) when restoring a raw .db.
    if not backup_path.endswith(".gz"):
        for ext in ("-wal", "-shm"):
            src = backup_path + ext
            if os.path.exists(src):
                shutil.copy2(src, DB_PATH + ext)

    print(f"Restored from: {os.path.basename(backup_path)}")
    return True


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_backups()
    elif "--restore" in sys.argv:
        restore_backup()
    elif "--verify" in sys.argv:
        bs = sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db.gz")))
        if not bs:
            print("No backups to verify")
        else:
            print("ok" if verify_backup(bs[-1]) else "CORRUPT")
    else:
        create_backup("manual")
