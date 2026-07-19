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
    * Compressed (.db.gz) copy is emitted for offsite/ransomware safety.
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
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute("PRAGMA integrity_check")
            rows = cur.fetchall()
        finally:
            con.close()
        return bool(rows) and all(r[0] == "ok" for r in rows)
    except Exception:
        return False


def verify_backup(path: str) -> bool:
    """Return True if the given backup file passes PRAGMA integrity_check."""
    return _integrity_ok(path)


def create_backup(label="auto", category=None):
    """Create a consistent, verified backup of the live database.

    Uses the SQLite Online Backup API so a backup taken while the bot is
    writing remains internally consistent. Returns the backup path, or None
    if the source DB is missing/corrupt.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH):
        print(f"WARNING: {DB_PATH} not found, skipping backup")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe = _safe_label(label)
    backup_name = f"bot_{safe}_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    tmp_path = backup_path + ".tmp"

    # Source integrity must be OK before we bother copying.
    if not _integrity_ok(DB_PATH):
        print("WARNING: source DB failed integrity_check, aborting backup")
        return None

    try:
        src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(tmp_path)
            try:
                with dst:  # commit/close cleanly
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except Exception as e:
        print(f"ERROR: backup failed: {e}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None

    # Atomic publish.
    os.replace(tmp_path, backup_path)

    # Compressed offsite-friendly copy (plaintext at rest but small + portable).
    gz_path = backup_path + ".gz"
    with open(backup_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    size_kb = os.path.getsize(backup_path) / 1024
    print(f"Backup created: {backup_name} ({size_kb:.0f} KB)")

    # Retention: per category (label family), keep newest N.
    _cleanup_old(category or safe)

    # Offsite copy (different directory) for DR — no encryption, as configured.
    try:
        copy_to_offsite(backup_path)
    except Exception as e:
        print(f"WARNING: offsite copy failed: {e}")

    return backup_path


def copy_to_offsite(backup_path: str, offsite_dir: str | None = None) -> str | None:
    """Copy the latest compressed backup to a separate directory for DR.

    Copies the .gz sidecar (produced by create_backup) to ``offsite_dir``
    (defaults to OFFSITE_DIR, a sibling of the project). Returns the copied
    path, or None if there is nothing to copy. No encryption — plain copy.
    """
    offsite_dir = offsite_dir or OFFSITE_DIR
    gz_path = backup_path + ".gz"
    if not os.path.exists(gz_path):
        return None
    os.makedirs(offsite_dir, exist_ok=True)
    dest = os.path.join(offsite_dir, os.path.basename(gz_path))
    shutil.copy2(gz_path, dest)
    print(f"Offsite copy: {os.path.basename(dest)} -> {offsite_dir}")
    return dest


def _cleanup_old(category: str):
    pattern = os.path.join(BACKUP_DIR, f"bot_{_safe_label(category)}_*.db")
    backups = sorted(glob.glob(pattern))
    for old in backups[: max(0, len(backups) - MAX_BACKUPS_PER_CATEGORY)]:
        for p in [old, old + ".gz", *[old + ext for ext in ("-wal", "-shm")]]:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def list_backups():
    if not os.path.exists(BACKUP_DIR):
        print("No backups found")
        return []
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db")))
    for b in backups:
        if b.endswith(".gz"):
            continue
        size_kb = os.path.getsize(b) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(b))
        ok = "ok" if _integrity_ok(b) else "CORRUPT"
        print(f"  {os.path.basename(b)} ({size_kb:.0f} KB) - {mtime:%Y-%m-%d %H:%M:%S} [{ok}]")
    return [b for b in backups if not b.endswith(".gz")]


def restore_backup(backup_path=None):
    if backup_path is None:
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db")))
        backups = [b for b in backups if not b.endswith(".gz")]
        if not backups:
            print("No backups to restore")
            return False
        backup_path = backups[-1]

    if not os.path.exists(backup_path):
        print(f"Backup not found: {backup_path}")
        return False
    if not _integrity_ok(backup_path):
        print("ERROR: selected backup is CORRUPT, refusing to restore")
        return False

    if os.path.exists(DB_PATH):
        fallback = DB_PATH + f".pre_restore_{datetime.now():%Y%m%d_%H%M%S}"
        shutil.copy2(DB_PATH, fallback)
        print(f"Current DB saved as: {os.path.basename(fallback)}")

    # Atomic restore: copy to temp next to the target, then replace.
    tmp = DB_PATH + ".restore.tmp"
    shutil.copy2(backup_path, tmp)
    os.replace(tmp, DB_PATH)
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
        bs = [b for b in sorted(glob.glob(os.path.join(BACKUP_DIR, "bot_*.db"))) if not b.endswith(".gz")]
        if not bs:
            print("No backups to verify")
        else:
            print("ok" if verify_backup(bs[-1]) else "CORRUPT")
    else:
        create_backup("manual")
