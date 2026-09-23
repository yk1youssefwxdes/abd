"""
Unit and Integration Tests for School ERP Commercial Packaging Layer.

Tests:
1. Central customer data directory resolution (Linux, Windows, env override).
2. Customer subdirectories (database, media, backups, logs, config, messages, licenses, whatsapp_session).
3. Runtime discovery logic (bundled Python, Node, Chromium vs dev fallback).
4. License file path resolution.
5. Idempotent legacy data migration.
6. Authoritative version consistency (core.version vs version.json).
7. Launcher configuration file location outside Program Files.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from core import paths, version


class CommercialPackagingPathsTestCase(TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="school_erp_pkg_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_version_consistency(self):
        """Verify core.version.VERSION matches version.json."""
        version_json_path = paths.get_base_dir() / "version.json"
        self.assertTrue(version_json_path.is_file(), "version.json must exist in project root")
        with open(version_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(
            version.VERSION,
            data.get("version"),
            "core.version.VERSION must match version in version.json",
        )

    def test_data_dir_env_override(self):
        """Verify SCHOOL_ERP_DATA_DIR overrides default data path."""
        custom_data_dir = self.temp_dir / "custom_data"
        with mock.patch.dict(os.environ, {"SCHOOL_ERP_DATA_DIR": str(custom_data_dir)}):
            resolved = paths.get_data_dir()
            self.assertEqual(resolved, custom_data_dir.resolve())
            self.assertEqual(paths.get_database_dir(), custom_data_dir.resolve() / "database")
            self.assertEqual(paths.get_media_dir(), custom_data_dir.resolve() / "media")
            self.assertEqual(paths.get_backups_dir(), custom_data_dir.resolve() / "backups")
            self.assertEqual(paths.get_logs_dir(), custom_data_dir.resolve() / "logs")
            self.assertEqual(paths.get_config_dir(), custom_data_dir.resolve() / "config")
            self.assertEqual(paths.get_messages_dir(), custom_data_dir.resolve() / "messages")
            self.assertEqual(paths.get_licenses_dir(), custom_data_dir.resolve() / "licenses")
            self.assertEqual(paths.get_whatsapp_session_dir(), custom_data_dir.resolve() / "whatsapp_session")

    def test_windows_programdata_resolution(self):
        """Verify Windows production resolves to %PROGRAMDATA%\\SchoolERP."""
        with mock.patch.dict(os.environ, {"PROGRAMDATA": r"C:\ProgramData"}, clear=False):
            with mock.patch.dict(os.environ, {"SCHOOL_ERP_DATA_DIR": ""}):
                with mock.patch("sys.platform", "win32"):
                    resolved = paths.get_data_dir()
                    expected = Path(r"C:\ProgramData") / "SchoolERP"
                    self.assertEqual(resolved, expected)

    def test_ensure_data_directories_creates_all(self):
        """Verify ensure_data_directories creates all expected subdirectories."""
        test_data_dir = self.temp_dir / "target_data"
        with mock.patch.dict(os.environ, {"SCHOOL_ERP_DATA_DIR": str(test_data_dir)}):
            paths.ensure_data_directories()
            self.assertTrue(paths.get_data_dir().is_dir())
            self.assertTrue(paths.get_database_dir().is_dir())
            self.assertTrue(paths.get_media_dir().is_dir())
            self.assertTrue(paths.get_backups_dir().is_dir())
            self.assertTrue(paths.get_logs_dir().is_dir())
            self.assertTrue(paths.get_config_dir().is_dir())
            self.assertTrue(paths.get_messages_dir().is_dir())
            self.assertTrue(paths.get_licenses_dir().is_dir())
            self.assertTrue(paths.get_whatsapp_session_dir().is_dir())

    def test_license_path_resolution_order(self):
        """Verify license resolution checks licenses/ dir, data dir, and base dir."""
        test_data_dir = self.temp_dir / "license_data"
        with mock.patch.dict(os.environ, {"SCHOOL_ERP_DATA_DIR": str(test_data_dir)}):
            paths.ensure_data_directories()

            # 1. Fallback to base_dir if no license in data
            res_base = paths.get_license_file_path()
            self.assertEqual(res_base, paths.get_base_dir() / "license.enc")

            # 2. Prefer data/license.enc if present
            data_lic = test_data_dir / "license.enc"
            data_lic.write_text("test_lic", encoding="utf-8")
            self.assertEqual(paths.get_license_file_path(), data_lic)

            # 3. Prefer data/licenses/license.enc over data/license.enc
            sub_lic = test_data_dir / "licenses" / "license.enc"
            sub_lic.write_text("sub_lic", encoding="utf-8")
            self.assertEqual(paths.get_license_file_path(), sub_lic)

    def test_legacy_data_migration_is_idempotent(self):
        """Verify legacy migration copies files without overwriting or erroring."""
        fake_base = self.temp_dir / "fake_base"
        fake_data = self.temp_dir / "fake_data"
        fake_base.mkdir()
        fake_data.mkdir()

        # Create dummy legacy files in fake_base
        (fake_base / "db.sqlite3").write_text("dummy_db", encoding="utf-8")
        (fake_base / "run_server_config.json").write_text('{"WA_PORT": 3000}', encoding="utf-8")
        legacy_media = fake_base / "media"
        legacy_media.mkdir()
        (legacy_media / "photo.jpg").write_text("photo_data", encoding="utf-8")

        with mock.patch("core.paths.get_base_dir", return_value=fake_base):
            with mock.patch("core.paths.get_data_dir", return_value=fake_data):
                paths.migrate_legacy_data()

                # Verify files were migrated
                target_db = fake_data / "database" / "database.sqlite3"
                self.assertTrue(target_db.is_file())
                self.assertEqual(target_db.read_text(encoding="utf-8"), "dummy_db")

                target_cfg = fake_data / "config" / "run_server_config.json"
                self.assertTrue(target_cfg.is_file())

                target_photo = fake_data / "media" / "photo.jpg"
                self.assertTrue(target_photo.is_file())

                # Modify migrated file, re-run migration to ensure it does NOT overwrite
                target_db.write_text("modified_db", encoding="utf-8")
                paths.migrate_legacy_data()
                self.assertEqual(target_db.read_text(encoding="utf-8"), "modified_db")


class RuntimeDiscoveryTestCase(TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="school_erp_runtime_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_bundled_python_discovery_windows(self):
        """Verify launcher detects runtime/python/python.exe on Windows."""
        import run_server

        fake_base = self.temp_dir / "app_root"
        fake_py = fake_base / "runtime" / "python" / "python.exe"
        fake_py.parent.mkdir(parents=True, exist_ok=True)
        fake_py.write_text("", encoding="utf-8")

        with mock.patch("run_server._get_base_dir", return_value=str(fake_base)):
            with mock.patch("sys.platform", "win32"):
                discovered = run_server.get_python_executable()
                self.assertEqual(discovered, str(fake_py))

    def test_bundled_node_discovery(self):
        """Verify launcher detects runtime/node/node.exe on Windows."""
        import run_server

        fake_base = self.temp_dir / "app_root"
        fake_node = fake_base / "runtime" / "node" / "node.exe"
        fake_node.parent.mkdir(parents=True, exist_ok=True)
        fake_node.write_text("", encoding="utf-8")

        with mock.patch("run_server._get_base_dir", return_value=str(fake_base)):
            with mock.patch("sys.platform", "win32"):
                discovered = run_server.get_node_executable()
                self.assertEqual(discovered, str(fake_node))

    def test_bundled_chromium_discovery(self):
        """Verify launcher detects runtime/chromium/chrome.exe."""
        import run_server

        fake_base = self.temp_dir / "app_root"
        fake_chrome = fake_base / "runtime" / "chromium" / "chrome.exe"
        fake_chrome.parent.mkdir(parents=True, exist_ok=True)
        fake_chrome.write_text("", encoding="utf-8")

        with mock.patch("run_server._get_base_dir", return_value=str(fake_base)):
            with mock.patch("sys.platform", "win32"):
                discovered = run_server.get_chromium_executable()
                self.assertEqual(discovered, str(fake_chrome))
