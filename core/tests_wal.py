"""
Phase 2: SQLite WAL Mode & Concurrency Configuration Tests.

These tests verify the actual SQLite session configuration as experienced
by Django's database connection — not merely the content of settings.py.

IMPORTANT: Django test database vs. production database
-------------------------------------------------------
Django's test runner creates an isolated SQLite database using a shared-memory
URI (file:memorydb_<alias>?mode=memory&cache=shared) unless TEST["NAME"] is
explicitly set to a file path.  WAL mode cannot be enabled for in-memory
SQLite databases — it is a fundamental SQLite limitation.  Therefore:

  - test_journal_mode_is_wal: SKIPPED for in-memory test databases;
    the WAL PRAGMA is validated to return 'memory' (in-memory) or 'wal'
    (file-backed production/test-file database) and never raises an error.
  - All other PRAGMA tests (synchronous, busy_timeout) apply to both
    in-memory and file-backed databases and are not skipped.

The production db.sqlite3 is NEVER accessed or modified by these tests.
Django's init_command is applied to whatever database the test runner creates.
"""

from unittest import TestCase as PureTestCase

from django.db import connection
from django.test import TestCase


def _is_in_memory_test_db() -> bool:
    """Return True if the current Django connection targets an in-memory SQLite DB."""
    db_name = str(connection.settings_dict.get("NAME", ""))
    # Django's test runner uses a shared-memory URI:
    #   file:memorydb_<alias>?mode=memory&cache=shared
    # or the literal :memory: string.
    return db_name == ":memory:" or "mode=memory" in db_name


class WALConnectionConfigTestCase(TestCase):
    """
    Verify SQLite WAL configuration via the live Django test-database connection.

    Django's test runner creates an isolated test database.  The
    DATABASES["default"]["OPTIONS"] — including init_command — apply to
    that test database identically to the production database, with one
    exception: WAL mode cannot be enabled for in-memory databases.
    """

    def _pragma(self, name: str):
        """Execute a PRAGMA and return the scalar result."""
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA {name};")
            row = cursor.fetchone()
        return row[0] if row else None

    # ── Journal mode ─────────────────────────────────────────────────────────

    def test_journal_mode_is_wal_or_memory(self):
        """
        Verify journal_mode is 'wal' (file-backed DB) or 'memory' (in-memory DB).

        SQLite's PRAGMA journal_mode=WAL is silently ignored for in-memory
        databases and returns 'memory' instead.  This is a fundamental SQLite
        limitation, not a configuration error.

        Production database (db.sqlite3):
          PRAGMA journal_mode=WAL -> returns 'wal'.

        Django test database (in-memory URI):
          PRAGMA journal_mode=WAL is rejected by SQLite -> returns 'memory'.
          Django's init_command still executes without error; SQLite simply
          does not apply WAL to in-memory databases.

        This test asserts that journal_mode is one of {'wal', 'memory'} and
        never an unexpected mode (e.g., 'delete', 'truncate', 'persist').
        """
        journal_mode = self._pragma("journal_mode")
        self.assertIn(
            journal_mode,
            {"wal", "memory"},
            f"Unexpected journal_mode='{journal_mode}'. "
            f"Expected 'wal' (file-backed) or 'memory' (in-memory test DB).",
        )
        # Log which path we are on to make CI results self-explanatory
        if _is_in_memory_test_db():
            # Expected: WAL not applicable to in-memory DB
            self.assertEqual(
                journal_mode,
                "memory",
                "In-memory test database must report journal_mode='memory'.",
            )
        else:
            # File-backed database: WAL must be active
            self.assertEqual(
                journal_mode,
                "wal",
                f"File-backed database must report journal_mode='wal', got '{journal_mode}'.",
            )

    # ── Synchronous mode ─────────────────────────────────────────────────────

    def test_synchronous_is_normal(self):
        """
        synchronous must be NORMAL (1) — not FULL (2) or OFF (0).

        NORMAL is safe and sufficient for WAL mode: SQLite guarantees
        database integrity across crashes with NORMAL under WAL.  FULL is
        the conservative default for rollback-journal mode and adds
        unnecessary fsync overhead under WAL.

        This pragma applies to both file-backed and in-memory databases.

        SQLite encodes synchronous as an integer:
          0 = OFF, 1 = NORMAL, 2 = FULL, 3 = EXTRA
        """
        synchronous = self._pragma("synchronous")
        self.assertEqual(
            synchronous,
            1,
            f"Expected synchronous=1 (NORMAL), got {synchronous}. "
            "Check OPTIONS['init_command'] in DATABASES settings.",
        )

    # ── Busy timeout ─────────────────────────────────────────────────────────

    def test_busy_timeout_is_30000ms(self):
        """
        busy_timeout must be 30 000 ms (30 seconds).

        This value is set by two complementary mechanisms:
          1. OPTIONS['timeout'] = 30  ->  sqlite3.connect(timeout=30)
             CPython internally calls PRAGMA busy_timeout = 30000 ms
             when the connection is opened.
          2. 'PRAGMA busy_timeout=30000' in OPTIONS['init_command']
             confirms the value explicitly after connection init and
             makes the intent self-documenting.

        busy_timeout is a session-level setting; it is NOT stored in the
        database file.  This pragma applies to both file-backed and in-memory
        databases.
        """
        busy_timeout = self._pragma("busy_timeout")
        self.assertEqual(
            busy_timeout,
            30000,
            f"Expected busy_timeout=30000, got {busy_timeout}. "
            "Check OPTIONS['timeout'] and OPTIONS['init_command'].",
        )

    # ── Basic connectivity & query execution ─────────────────────────────────

    def test_django_connection_is_established(self):
        """Django can open a SQLite connection and execute a trivial query."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            result = cursor.fetchone()
        self.assertEqual(result, (1,))

    def test_existing_queries_continue_to_work(self):
        """ORM queries work correctly under WAL/memory mode."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        # Simple ORM query — just count; no inserts needed
        count = User.objects.count()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)

    # ── WAL mode write/read guard ─────────────────────────────────────────────

    def test_wal_mode_does_not_raise_on_write(self):
        """
        A write followed by a read must succeed under both WAL and memory mode.

        This guards against any regression where WAL initialization breaks
        write transactions.  It confirms that Django's init_command does not
        corrupt connection state for normal ORM operations.
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            username="wal_test_user",
            password="testpass123",
        )
        try:
            fetched = User.objects.get(pk=user.pk)
            self.assertEqual(fetched.username, "wal_test_user")
        finally:
            user.delete()


class WALSettingsValidationTestCase(PureTestCase):
    """
    Validate that the DATABASES settings contain the expected Phase 2 options.

    These checks verify the settings structure, not the live SQLite session.
    They complement WALConnectionConfigTestCase by catching misconfiguration
    early without requiring a database connection.
    """

    def _get_db_options(self):
        from django.conf import settings
        return settings.DATABASES.get("default", {}).get("OPTIONS", {})

    def test_engine_is_sqlite3(self):
        from django.conf import settings
        engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
        self.assertIn("sqlite3", engine, "DATABASES['default']['ENGINE'] must use SQLite.")

    def test_options_timeout_is_30(self):
        options = self._get_db_options()
        self.assertEqual(
            options.get("timeout"),
            30,
            "OPTIONS['timeout'] must be 30 (seconds) for the Python-level busy-wait.",
        )

    def test_init_command_contains_wal(self):
        options = self._get_db_options()
        init_cmd = options.get("init_command", "")
        self.assertIn(
            "journal_mode=WAL",
            init_cmd,
            "OPTIONS['init_command'] must include 'PRAGMA journal_mode=WAL'.",
        )

    def test_init_command_contains_synchronous_normal(self):
        options = self._get_db_options()
        init_cmd = options.get("init_command", "")
        self.assertIn(
            "synchronous=NORMAL",
            init_cmd,
            "OPTIONS['init_command'] must include 'PRAGMA synchronous=NORMAL'.",
        )

    def test_init_command_contains_busy_timeout(self):
        options = self._get_db_options()
        init_cmd = options.get("init_command", "")
        self.assertIn(
            "busy_timeout=30000",
            init_cmd,
            "OPTIONS['init_command'] must include 'PRAGMA busy_timeout=30000'.",
        )
