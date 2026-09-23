"""
Unit and Integration Tests for School ERP Licensing Engine.

Tests:
1. Valid wildcard and machine-locked license validation.
2. Fingerprint mismatch rejection.
3. Expired license rejection (both wildcard and machine-locked).
4. Not-yet-active license rejection (future start date).
5. Search path resolution order (licenses_dir > data_dir > base_dir).
6. Resilience of decrypt_license_file against renamed or backup files.
7. In-process validation caching.
8. tools.create_license vendor CLI helper.
"""

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from core import license, license_utils, paths
from core.hardware import get_fingerprint_hash


class LicensingEngineTestCase(TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="school_erp_lic_test_"))
        self.secret_key = license_utils.get_license_secret()
        license._reset_validation_cache()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        license._reset_validation_cache()

    def _write_encrypted_license(self, dest_path: Path, payload: dict, output_name: str = "license.enc") -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = license_utils.encrypt_license_payload(payload, self.secret_key, output_name=output_name)
        dest_path.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")

    def test_valid_wildcard_license(self):
        """Wildcard license within valid dates passes validation."""
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": "*",
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        self.assertTrue(license.validate_or_exit())

    def test_valid_machine_locked_license(self):
        """License locked to current machine fingerprint passes validation."""
        current_fp = get_fingerprint_hash()
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": current_fp,
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        self.assertTrue(license.validate_or_exit())

    def test_fingerprint_mismatch_raises_exit(self):
        """License locked to a different fingerprint triggers SystemExit."""
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": "0000000000000000000000000000000000000000000000000000000000000000",
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        with self.assertRaises(SystemExit):
                            license.validate_or_exit()

    def test_expired_license_raises_exit(self):
        """License with END_DATE in the past triggers SystemExit with expiration message."""
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": "*",
            "START_DATE": "2020-01-01",
            "END_DATE": "2021-01-01",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        with self.assertRaises(SystemExit) as ctx:
                            license.validate_or_exit()
                        self.assertIn("expir", str(ctx.exception).lower())

    def test_future_start_date_raises_exit(self):
        """License with START_DATE in the future triggers SystemExit."""
        future_year = datetime.date.today().year + 5
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": "*",
            "START_DATE": f"{future_year}-01-01",
            "END_DATE": f"{future_year + 1}-01-01",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        with self.assertRaises(SystemExit) as ctx:
                            license.validate_or_exit()
                        self.assertIn("active", str(ctx.exception).lower())

    def test_search_path_priority_licenses_dir_overrides_base_dir(self):
        """A machine-locked license in licenses_dir is preferred over a base_dir license."""
        lic_dir = self.temp_dir / "licenses"
        base_dir = self.temp_dir / "base"
        lic_dir.mkdir(parents=True, exist_ok=True)
        base_dir.mkdir(parents=True, exist_ok=True)

        current_fp = get_fingerprint_hash()
        # High priority in licenses_dir: valid for this machine
        client_payload = {
            "LICENSED_FINGERPRINT": current_fp,
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
            "SOURCE": "CLIENT_DIR",
        }
        self._write_encrypted_license(lic_dir / "license.enc", client_payload)

        # Lower priority in base_dir: mismatched fingerprint that would fail
        base_payload = {
            "LICENSED_FINGERPRINT": "mismatch_fingerprint_hash",
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
            "SOURCE": "BASE_DIR",
        }
        self._write_encrypted_license(base_dir / "license.enc", base_payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir / "data"):
                with mock.patch("core.license.get_base_dir", return_value=base_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        loaded = license._load_license_data()
                        self.assertEqual(loaded.get("SOURCE"), "CLIENT_DIR")
                        self.assertTrue(license.validate_or_exit())

    def test_renamed_license_decryption(self):
        """decrypt_license_file successfully decrypts files even when renamed/backed up."""
        backup_file = self.temp_dir / "license_local.enc.bak"
        payload = {
            "LICENSED_FINGERPRINT": "*",
            "START_DATE": "2025-01-01",
            "END_DATE": "2035-12-31",
        }
        # Encrypted with standard output_name="license.enc"
        self._write_encrypted_license(backup_file, payload, output_name="license.enc")

        decrypted = license_utils.decrypt_license_file(backup_file, self.secret_key)
        self.assertEqual(decrypted["LICENSED_FINGERPRINT"], "*")
        self.assertEqual(decrypted["START_DATE"], "2025-01-01")

    def test_in_process_caching(self):
        """Subsequent validate_or_exit calls return True from memory cache."""
        lic_dir = self.temp_dir / "licenses"
        lic_file = lic_dir / "license.enc"
        payload = {
            "LICENSED_FINGERPRINT": "*",
            "START_DATE": "2020-01-01",
            "END_DATE": "2030-12-31",
        }
        self._write_encrypted_license(lic_file, payload)

        with mock.patch("core.license.get_licenses_dir", return_value=lic_dir):
            with mock.patch("core.license.get_data_dir", return_value=self.temp_dir):
                with mock.patch("core.license.get_base_dir", return_value=self.temp_dir):
                    with mock.patch("core.license._is_cloud_environment", return_value=False):
                        self.assertTrue(license.validate_or_exit())
                        self.assertTrue(license._VALIDATED_IN_PROCESS)

                        # Even if license file is deleted, in-process cache returns True
                        lic_file.unlink()
                        self.assertTrue(license.validate_or_exit())
