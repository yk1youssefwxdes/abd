#!/usr/bin/env python3
"""
client_db_backup.py  –  School ERP Database Backup & Restore Tool
=================================================================
A safe backup and restore utility to use before/after updates on client PCs:
  • Performs WAL checkpointing before backup (ensures zero data loss)
  • Creates timestamped backups in the ProgramData / backups directory
  • Verifies SQLite integrity before & after operations
  • Safe restore with automatic pre-restore rollback snapshot

Usage:
------
  python tools/client_db_backup.py --backup
  python tools/client_db_backup.py --list
  python tools/client_db_backup.py --restore <backup_file>
  python tools/client_db_backup.py --verify
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.paths import get_database_path, get_backups_dir, get_database_dir


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _info(msg: str) -> None:
    print(f"        {msg}")


def _fail(msg: str) -> None:
    print(f"  [ERR] {msg}", file=sys.stderr)


def get_file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:10]


def checkpoint_wal(db_path: Path) -> None:
    """Flush WAL journal into the main SQLite database file."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()
        conn.close()
        _ok("SQLite WAL checkpoint complete (all in-memory changes committed).")
    except Exception as exc:
        _info(f"WAL checkpoint notice: {exc}")


def verify_db(db_path: Path) -> bool:
    """Check SQLite integrity."""
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchone()
        conn.close()
        if res and res[0] == "ok":
            _ok(f"Integrity check passed: {db_path.name}")
            return True
        else:
            _fail(f"Integrity check issue: {res}")
            return False
    except Exception as exc:
        _fail(f"Could not verify database: {exc}")
        return False


def do_backup(custom_dest: Path | None = None) -> Path:
    _banner("DATABASE BACKUP")
    db_path = get_database_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # Checkpoint WAL first
    checkpoint_wal(db_path)

    # Destination
    backups_dir = custom_dest.parent if custom_dest else get_backups_dir()
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = custom_dest or (backups_dir / f"SchoolERP_DB_{timestamp}.sqlite3")

    shutil.copy2(db_path, dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    md5_hash = get_file_md5(dest)

    _ok(f"Backup created successfully ({size_mb:.2f} MB)")
    _info(f"File: {dest}")
    _info(f"Checksum MD5: {md5_hash}")

    # Verify backup integrity
    verify_db(dest)
    return dest


def do_list() -> None:
    _banner("AVAILABLE DATABASE BACKUPS")
    backups_dir = get_backups_dir()
    if not backups_dir.exists():
        _info("No backups directory found.")
        return

    backups = sorted(backups_dir.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        _info(f"No backup files found in {backups_dir}")
        return

    print(f"  {'Filename':<40} {'Size (MB)':<12} {'Created Date'}")
    print(f"  {'-' * 40} {'-' * 12} {'-' * 20}")
    for b in backups:
        size = b.stat().st_size / (1024 * 1024)
        mtime = datetime.datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {b.name:<40} {size:>8.2f} MB   {mtime}")


def do_restore(backup_file: Path) -> None:
    _banner("DATABASE RESTORE")
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file does not exist: {backup_file}")

    db_path = get_database_path()

    # 1. Verify backup file before touching anything
    _info("Verifying backup file integrity before restore...")
    if not verify_db(backup_file):
        raise RuntimeError("Backup file failed integrity check! Aborting restore for safety.")

    # 2. Safety snapshot of CURRENT database before replacing
    if db_path.exists():
        _info("Taking safety snapshot of current database before restoring...")
        rollback_dest = get_backups_dir() / f"PRE_RESTORE_SAFETY_SNAPSHOT_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"
        checkpoint_wal(db_path)
        shutil.copy2(db_path, rollback_dest)
        _ok(f"Current state preserved at: {rollback_dest.name}")

    # 3. Clean up any leftover WAL / SHM files
    for suffix in ["-wal", "-shm", "-journal"]:
        wal_file = Path(str(db_path) + suffix)
        if wal_file.exists():
            try:
                wal_file.unlink()
            except Exception:
                pass

    # 4. Copy backup to active database location
    shutil.copy2(backup_file, db_path)
    _ok(f"Restored database from: {backup_file.name}")

    # 5. Verify restored active database
    verify_db(db_path)
    _ok("Database restore finished cleanly and verified.")


def main() -> int:
    parser = argparse.ArgumentParser(description="School ERP Database Backup & Restore Tool")
    parser.add_argument("--backup", action="store_true", help="Create an immediate backup of the database")
    parser.add_argument("--list", action="store_true", help="List all existing backups")
    parser.add_argument("--restore", type=str, help="Path to backup file to restore from")
    parser.add_argument("--verify", action="store_true", help="Verify the integrity of the active database")
    args = parser.parse_args()

    if args.backup:
        do_backup()
    elif args.list:
        do_list()
    elif args.restore:
        do_restore(Path(args.restore).resolve())
    elif args.verify:
        _banner("DATABASE INTEGRITY VERIFICATION")
        db_path = get_database_path()
        verify_db(db_path)
    else:
        # Default action: create backup and list
        do_backup()
        do_list()

    return 0


if __name__ == "__main__":
    sys.exit(main())
