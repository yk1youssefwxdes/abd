"""
SQLite Database Backup Service.

Provides atomic, consistent SQLite database snapshots using Python's native
SQLite Online Backup API and performs read-only verification.
"""

from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import sqlite3
from typing import List, Optional, Tuple, Union

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_EXPECTED_TABLES = ["django_migrations", "core_student"]


@dataclass
class BackupResult:
    """Dataclass holding the result of a database backup operation."""
    success: bool
    backup_path: Optional[Path] = None
    error: Optional[str] = None
    timestamp: Optional[datetime] = None


def get_default_db_path(db_alias: str = "default") -> Path:
    """Retrieve the configured SQLite database file path from Django settings."""
    db_config = settings.DATABASES.get(db_alias)
    if not db_config:
        raise ValueError(f"Database alias '{db_alias}' is not configured in Django settings.")
    
    engine = db_config.get("ENGINE", "")
    if "sqlite3" not in engine:
        raise ValueError(f"Database alias '{db_alias}' uses engine '{engine}', expected SQLite.")
    
    db_name = db_config.get("NAME")
    if not db_name:
        raise ValueError(f"Database alias '{db_alias}' has no NAME configured.")
    
    return Path(db_name).resolve()


def verify_database_backup(
    backup_path: Union[str, Path],
    expected_tables: Optional[List[str]] = None,
    timeout: float = 10.0,
) -> Tuple[bool, Optional[str]]:
    """
    Verify an existing SQLite backup file using a read-only connection.

    Checks performed:
    1. Backup file existence and non-zero size.
    2. SQLite database readability and 'PRAGMA integrity_check'.
    3. Presence of expected application tables.
    4. Execution of a basic read query.

    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message_if_failed)
    """
    path = Path(backup_path).resolve()

    if not path.exists():
        return False, f"Backup file does not exist: {path}"

    if not path.is_file():
        return False, f"Backup path is not a file: {path}"

    if path.stat().st_size == 0:
        return False, f"Backup file is empty (0 bytes): {path}"

    tables_to_check = expected_tables if expected_tables is not None else DEFAULT_EXPECTED_TABLES

    conn: Optional[sqlite3.Connection] = None
    try:
        # Open in read-only mode using SQLite URI filename
        uri_path = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri_path, uri=True, timeout=timeout)
        cursor = conn.cursor()

        # 1. Integrity check
        cursor.execute("PRAGMA integrity_check;")
        integrity_result = cursor.fetchall()
        if not integrity_result or integrity_result[0][0] != "ok":
            error_details = ", ".join([r[0] for r in integrity_result]) if integrity_result else "No result"
            return False, f"SQLite integrity check failed: {error_details}"

        # 2. Table existence check
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing_tables = {row[0] for row in cursor.fetchall()}

        missing_tables = [t for t in tables_to_check if t not in existing_tables]
        if missing_tables:
            return False, f"Backup is missing expected table(s): {', '.join(missing_tables)}"

        # 3. Read query execution
        cursor.execute("SELECT 1;")
        read_test = cursor.fetchone()
        if not read_test or read_test[0] != 1:
            return False, "Basic read query execution failed."

        return True, None

    except sqlite3.Error as e:
        return False, f"SQLite error during verification: {e}"
    except Exception as e:
        return False, f"Unexpected error during verification: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def create_database_backup(
    destination_dir: Optional[Union[str, Path]] = None,
    db_alias: str = "default",
    db_path: Optional[Union[str, Path]] = None,
    expected_tables: Optional[List[str]] = None,
    timeout: float = 20.0,
) -> BackupResult:
    """
    Create a safe, atomic SQLite snapshot using SQLite's Online Backup API.

    1. Resolves source database path (from Django settings or parameter).
    2. Ensures target directory exists.
    3. Performs backup into a temporary file (`.tmp`).
    4. Verifies temporary backup file.
    5. Atomically renames temporary file to final `.sqlite3` backup file.
    6. Cleans up temporary file on failure.

    Returns:
        BackupResult object with success status, path, timestamp, or error message.
    """
    now = timezone.now() if settings.configured else datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")

    # 1. Resolve source database path
    try:
        if db_path is not None:
            source_path = Path(db_path).resolve()
        else:
            source_path = get_default_db_path(db_alias=db_alias)
    except Exception as e:
        logger.error(f"Failed to resolve SQLite database path: {e}")
        return BackupResult(success=False, error=str(e))

    if not source_path.exists() or not source_path.is_file():
        err_msg = f"Source database file does not exist: {source_path}"
        logger.error(err_msg)
        return BackupResult(success=False, error=err_msg)

    # 2. Resolve destination directory & filenames
    if destination_dir is None:
        from core.paths import get_backups_dir
        dest_dir = get_backups_dir()
    else:
        dest_dir = Path(destination_dir).resolve()

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        err_msg = f"Failed to create backup directory '{dest_dir}': {e}"
        logger.error(err_msg)
        return BackupResult(success=False, error=err_msg)

    final_filename = f"school_erp_{timestamp_str}.sqlite3"
    temp_filename = f"school_erp_{timestamp_str}.tmp"

    final_path = dest_dir / final_filename
    temp_path = dest_dir / temp_filename

    source_conn: Optional[sqlite3.Connection] = None
    temp_conn: Optional[sqlite3.Connection] = None

    try:
        # Open source connection in read-only mode to prevent accidental writes
        source_uri = f"file:{source_path.as_posix()}?mode=ro"
        source_conn = sqlite3.connect(source_uri, uri=True, timeout=timeout)

        # Open destination connection for temp file
        temp_conn = sqlite3.connect(temp_path, timeout=timeout)

        # Perform online backup
        with temp_conn:
            source_conn.backup(temp_conn)

    except sqlite3.Error as e:
        err_msg = f"SQLite backup operation failed: {e}"
        logger.error(err_msg)
        _cleanup_file(temp_path)
        return BackupResult(success=False, error=err_msg)
    except Exception as e:
        err_msg = f"Unexpected error during backup creation: {e}"
        logger.error(err_msg)
        _cleanup_file(temp_path)
        return BackupResult(success=False, error=err_msg)
    finally:
        if temp_conn is not None:
            try:
                temp_conn.close()
            except Exception:
                pass
        if source_conn is not None:
            try:
                source_conn.close()
            except Exception:
                pass

    # 3. Verify backup file
    is_valid, verify_error = verify_database_backup(
        temp_path,
        expected_tables=expected_tables,
        timeout=timeout,
    )

    if not is_valid:
        err_msg = f"Backup verification failed: {verify_error}"
        logger.error(err_msg)
        _cleanup_file(temp_path)
        return BackupResult(success=False, error=err_msg)

    # 4. Atomic rename from temp file to final file
    try:
        temp_path.replace(final_path)
    except Exception as e:
        err_msg = f"Failed to rename temp backup file to final path: {e}"
        logger.error(err_msg)
        _cleanup_file(temp_path)
        return BackupResult(success=False, error=err_msg)

    logger.info(f"Successfully created database backup: {final_path}")
    return BackupResult(
        success=True,
        backup_path=final_path,
        timestamp=now,
    )


def _cleanup_file(file_path: Path) -> None:
    """Safely remove a file if it exists."""
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to clean up temporary file '{file_path}': {e}")
