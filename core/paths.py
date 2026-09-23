"""
Central Path and Customer Data Directory Abstraction for School ERP.

Separates immutable application code (Program Files / workspace) from
mutable customer data (ProgramData / data directory).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


ENV_DATA_DIR = "SCHOOL_ERP_DATA_DIR"
DEFAULT_WINDOWS_PROGRAMDATA = r"C:\ProgramData"
APP_SUBDIR_NAME = "SchoolERP"


def get_base_dir() -> Path:
    """Return the absolute Path to the application root directory."""
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """
    Return the path to the mutable customer data directory.

    Order of resolution:
    1. Explicit environment variable: SCHOOL_ERP_DATA_DIR
    2. Windows production: %PROGRAMDATA%/SchoolERP (e.g. C:\\ProgramData\\SchoolERP)
    3. Linux / Development default: <BASE_DIR>/data
    """
    env_dir = os.environ.get(ENV_DATA_DIR)
    if env_dir:
        return Path(env_dir).resolve()

    if sys.platform == "win32":
        program_data = os.environ.get("PROGRAMDATA", DEFAULT_WINDOWS_PROGRAMDATA)
        return Path(program_data) / APP_SUBDIR_NAME

    return get_base_dir() / "data"


def get_database_dir() -> Path:
    """Return directory containing SQLite database and WAL files."""
    return get_data_dir() / "database"


def get_database_path() -> Path:
    """
    Return the path to the active SQLite database file.
    Prefers 'database.sqlite3' inside get_database_dir(), with backward
    compatibility check for 'db.sqlite3'.
    """
    db_dir = get_database_dir()
    db_sqlite3 = db_dir / "db.sqlite3"
    database_sqlite3 = db_dir / "database.sqlite3"

    if database_sqlite3.exists():
        return database_sqlite3
    if db_sqlite3.exists():
        return db_sqlite3
    return database_sqlite3


def get_media_dir() -> Path:
    """Return customer uploads / media directory."""
    return get_data_dir() / "media"


def get_backups_dir() -> Path:
    """Return database backups directory."""
    return get_data_dir() / "backups"


def get_whatsapp_session_dir() -> Path:
    """Return WhatsApp authentication and Puppeteer browser profile directory."""
    return get_data_dir() / "whatsapp_session"


def get_logs_dir() -> Path:
    """Return application log directory."""
    return get_data_dir() / "logs"


def get_config_dir() -> Path:
    """Return customer runtime configuration directory."""
    return get_data_dir() / "config"


def get_messages_dir() -> Path:
    """Return customer editable message templates directory."""
    return get_data_dir() / "messages"


def get_licenses_dir() -> Path:
    """Return directory for license files."""
    return get_data_dir() / "licenses"


def get_license_file_path() -> Path:
    """
    Locate the license file.
    Checks in:
    1. <DATA_DIR>/licenses/license.enc
    2. <DATA_DIR>/license.enc
    3. <BASE_DIR>/license.enc (application bundled default)
    """
    p1 = get_licenses_dir() / "license.enc"
    if p1.is_file():
        return p1

    p2 = get_data_dir() / "license.enc"
    if p2.is_file():
        return p2

    p3 = get_base_dir() / "license.enc"
    return p3


def ensure_data_directories() -> None:
    """Create all required customer data directories if they do not exist."""
    directories = [
        get_data_dir(),
        get_database_dir(),
        get_media_dir(),
        get_backups_dir(),
        get_whatsapp_session_dir(),
        get_logs_dir(),
        get_config_dir(),
        get_messages_dir(),
        get_licenses_dir(),
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> None:
    """
    Safely and idempotently copy/migrate existing legacy files from project root
    to the new customer data directory structure.
    Does not overwrite existing data in the destination.
    """
    ensure_data_directories()
    base_dir = get_base_dir()
    data_dir = get_data_dir()

    # Avoid self-copy if data_dir is base_dir
    if base_dir.resolve() == data_dir.resolve():
        return

    # 1. Database migration: db.sqlite3 -> database/database.sqlite3
    legacy_db = base_dir / "db.sqlite3"
    target_db = get_database_path()
    if legacy_db.is_file() and not target_db.exists():
        try:
            target_dest = get_database_dir() / "database.sqlite3"
            shutil.copy2(legacy_db, target_dest)
            # Copy WAL / SHM sidecars if present
            for ext in ("-wal", "-shm"):
                sidecar = base_dir / f"db.sqlite3{ext}"
                if sidecar.is_file():
                    shutil.copy2(sidecar, get_database_dir() / f"database.sqlite3{ext}")
        except Exception:
            pass

    # 2. Media migration: media/ -> data/media/
    legacy_media = base_dir / "media"
    target_media = get_media_dir()
    if legacy_media.is_dir() and legacy_media.resolve() != target_media.resolve():
        try:
            for item in legacy_media.iterdir():
                dest_item = target_media / item.name
                if not dest_item.exists():
                    if item.is_dir():
                        shutil.copytree(item, dest_item)
                    else:
                        shutil.copy2(item, dest_item)
        except Exception:
            pass

    # 3. Messages templates: messages/ -> data/messages/
    legacy_messages = base_dir / "messages"
    target_messages = get_messages_dir()
    if legacy_messages.is_dir() and legacy_messages.resolve() != target_messages.resolve():
        try:
            for item in legacy_messages.iterdir():
                dest_item = target_messages / item.name
                if not dest_item.exists():
                    if item.is_dir():
                        shutil.copytree(item, dest_item)
                    else:
                        shutil.copy2(item, dest_item)
        except Exception:
            pass

    # 4. Backups: backups/ -> data/backups/
    legacy_backups = base_dir / "backups"
    target_backups = get_backups_dir()
    if legacy_backups.is_dir() and legacy_backups.resolve() != target_backups.resolve():
        try:
            for item in legacy_backups.iterdir():
                dest_item = target_backups / item.name
                if not dest_item.exists() and item.is_file():
                    shutil.copy2(item, dest_item)
        except Exception:
            pass

    # 5. Local config: run_server_config.json -> data/config/run_server_config.json
    legacy_config = base_dir / "run_server_config.json"
    target_config = get_config_dir() / "run_server_config.json"
    if legacy_config.is_file() and not target_config.exists():
        try:
            shutil.copy2(legacy_config, target_config)
        except Exception:
            pass

    # 6. WhatsApp session: whatsapp_service/whatsapp_session -> data/whatsapp_session
    legacy_wa = base_dir / "whatsapp_service" / "whatsapp_session"
    target_wa = get_whatsapp_session_dir()
    if legacy_wa.is_dir() and legacy_wa.resolve() != target_wa.resolve():
        try:
            if not any(target_wa.iterdir()) if target_wa.exists() else True:
                for item in legacy_wa.iterdir():
                    dest_item = target_wa / item.name
                    if not dest_item.exists():
                        if item.is_dir():
                            shutil.copytree(item, dest_item)
                        else:
                            shutil.copy2(item, dest_item)
        except Exception:
            pass

    # 7. License: license.enc -> data/licenses/license.enc
    legacy_license = base_dir / "license.enc"
    target_license = get_licenses_dir() / "license.enc"
    if legacy_license.is_file() and not target_license.exists():
        try:
            shutil.copy2(legacy_license, target_license)
        except Exception:
            pass
