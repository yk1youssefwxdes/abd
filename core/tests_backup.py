"""
Unit tests for the SQLite Database Backup Service.

All tests use temporary SQLite databases and directories to ensure complete
isolation from production customer data.
"""

from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase

from core.services.backup import (
    create_database_backup,
    get_default_db_path,
    verify_database_backup,
)


class SQLiteBackupServiceTestCase(TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create a sample source database inside the temp directory
        self.source_db_path = self.temp_path / "test_source.sqlite3"
        self._init_sample_database(self.source_db_path)

        # Destination backup directory
        self.dest_backup_dir = self.temp_path / "backups"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _init_sample_database(self, db_path: Path):
        """Helper to set up a populated sample SQLite DB."""
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT, name TEXT);")
            cursor.execute("CREATE TABLE core_student (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);")
            cursor.execute("INSERT INTO django_migrations (app, name) VALUES ('core', '0001_initial');")
            cursor.execute("INSERT INTO core_student (first_name, last_name) VALUES ('Jean', 'Dupont');")
            conn.commit()
        finally:
            conn.close()

    def test_successful_backup(self):
        """Test that a backup of a valid database succeeds and passes verification."""
        result = create_database_backup(
            destination_dir=self.dest_backup_dir,
            db_path=self.source_db_path,
            expected_tables=["django_migrations", "core_student"],
        )

        self.assertTrue(result.success, f"Backup failed with error: {result.error}")
        self.assertIsNotNone(result.backup_path)
        self.assertTrue(result.backup_path.exists())
        self.assertEqual(result.backup_path.suffix, ".sqlite3")

    def test_data_integrity(self):
        """Test that data in the source database is faithfully copied to the backup snapshot."""
        result = create_database_backup(
            destination_dir=self.dest_backup_dir,
            db_path=self.source_db_path,
            expected_tables=["django_migrations", "core_student"],
        )

        self.assertTrue(result.success)

        # Connect to backup and check records
        conn = sqlite3.connect(result.backup_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT first_name, last_name FROM core_student;")
            row = cursor.fetchone()
            self.assertEqual(row, ("Jean", "Dupont"))
        finally:
            conn.close()

    def test_valid_backup_verification(self):
        """Test that verify_database_backup passes on a valid backup file."""
        is_valid, error = verify_database_backup(
            self.source_db_path,
            expected_tables=["django_migrations", "core_student"],
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_corrupt_non_sqlite_backup_rejection(self):
        """Test that verify_database_backup rejects corrupt or non-SQLite files."""
        corrupt_file = self.temp_path / "corrupt.sqlite3"
        corrupt_file.write_text("THIS IS NOT A VALID SQLITE DATABASE")

        is_valid, error = verify_database_backup(
            corrupt_file,
            expected_tables=["core_student"],
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        # Handle SQLite database error when attempting to open a non-sqlite file
        self.assertTrue(
            "integrity check failed" in error or "SQLite error during verification" in error,
            f"Unexpected error message: {error}"
        )

    def test_missing_source_database(self):
        """Test clean failure when source database file does not exist."""
        missing_db = self.temp_path / "non_existent.sqlite3"

        result = create_database_backup(
            destination_dir=self.dest_backup_dir,
            db_path=missing_db,
        )

        self.assertFalse(result.success)
        self.assertIn("does not exist", result.error)

    def test_automatic_destination_directory_creation(self):
        """Test that nested non-existent backup directories are created safely."""
        nested_dest_dir = self.temp_path / "nested" / "deep" / "backups"
        self.assertFalse(nested_dest_dir.exists())

        result = create_database_backup(
            destination_dir=nested_dest_dir,
            db_path=self.source_db_path,
            expected_tables=["core_student"],
        )

        self.assertTrue(result.success)
        self.assertTrue(nested_dest_dir.exists())
        self.assertTrue(result.backup_path.exists())

    def test_failed_backup_cleanup(self):
        """Test that failed backups clean up temporary files and leave no stray files."""
        # Force a failure during verification by requiring a table that doesn't exist
        result = create_database_backup(
            destination_dir=self.dest_backup_dir,
            db_path=self.source_db_path,
            expected_tables=["non_existent_table_xyz"],
        )

        self.assertFalse(result.success)
        self.assertIn("missing expected table", result.error)

        # Check that no temporary files (.tmp) or failed backups were left behind
        temp_files = list(self.dest_backup_dir.glob("*.tmp"))
        self.assertEqual(len(temp_files), 0, f"Stray temporary files found: {temp_files}")

    def test_source_database_unmodified(self):
        """Test that backup operations do not modify the source database or its records."""
        initial_mtime = self.source_db_path.stat().st_mtime_ns

        # Count records before
        conn = sqlite3.connect(self.source_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM core_student;")
        count_before = cursor.fetchone()[0]
        conn.close()

        result = create_database_backup(
            destination_dir=self.dest_backup_dir,
            db_path=self.source_db_path,
            expected_tables=["core_student"],
        )
        self.assertTrue(result.success)

        # Count records after
        conn = sqlite3.connect(self.source_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM core_student;")
        count_after = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count_before, count_after)
