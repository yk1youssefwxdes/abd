from __future__ import annotations

import datetime
import os
import secrets
from typing import Final

import json
from .hardware import get_fingerprint_hash
from .license_utils import (
    decrypt_license_file,
    encrypt_license_payload,
    get_license_secret,
)
from .paths import get_license_file_path, get_base_dir, get_licenses_dir, get_data_dir



_LICENSE_FILE_NAME: Final[str] = "license.enc"
_LICENSE_EXTRA_SECRET_ENV: Final[str] = "LICENSE_EXTRA_SECRET"
_LICENSE_FINGERPRINT_ENV: Final[str] = "LICENSE_FINGERPRINT"   # cloud override
_WILDCARD_FINGERPRINT: Final[str] = "*"                        # matches any device
_ERROR_MESSAGE: Final[str] = "Cette copie du logiciel n'est pas autorisée sur cet appareil."


def _is_cloud_environment() -> bool:
    """Return True if running on a cloud/container platform or explicit auto-license requested."""
    cloud_indicators = (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RENDER",
        "HEROKU_APP_ID",
        "FLY_APP_NAME",
        "KUBERNETES_SERVICE_HOST",
        "DYNO",
    )
    if any(os.getenv(var) for var in cloud_indicators):
        return True
    if os.getenv("AUTO_LICENSE", "").lower() in ("true", "1", "yes"):
        return True
    return False


def _auto_generate_cloud_license() -> dict:
    """Generate and write a valid wildcard license for server/cloud deployment."""
    payload = {
        "START_DATE": "2020-01-01",
        "END_DATE": "2099-12-31",
        "LICENSED_FINGERPRINT": _WILDCARD_FINGERPRINT,
    }
    secret_key = get_license_secret()
    extra_secret = os.getenv(_LICENSE_EXTRA_SECRET_ENV, "")
    if extra_secret:
        secret_key += extra_secret

    encrypted = encrypt_license_payload(payload, secret_key, _LICENSE_FILE_NAME)
    content = json.dumps(encrypted, indent=2)

    for target_dir in [get_base_dir(), get_licenses_dir(), get_data_dir()]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / _LICENSE_FILE_NAME).write_text(content, encoding="utf-8")
        except Exception:
            pass

    return payload


_VALIDATED_IN_PROCESS: bool = False


def _reset_validation_cache() -> None:
    """Reset the in-process validation cache (useful for testing and license updates)."""
    global _VALIDATED_IN_PROCESS
    _VALIDATED_IN_PROCESS = False


def _load_license_data() -> dict:
    # Cloud / auto-license: always generate a wildcard license without checking local files.
    if _is_cloud_environment() or os.getenv("AUTO_LICENSE", "").lower() in ("true", "1", "yes"):
        return _auto_generate_cloud_license()

    candidate_paths = [
        get_licenses_dir() / "license.enc",
        get_data_dir() / "license.enc",
        get_base_dir() / "license.enc",
    ]

    secret_key = get_license_secret()
    extra_secret = os.getenv(_LICENSE_EXTRA_SECRET_ENV, "")
    if extra_secret:
        secret_key += extra_secret

    for license_path in candidate_paths:
        if not license_path.is_file():
            continue
        try:
            data = decrypt_license_file(license_path, secret_key)
            if isinstance(data, dict):
                return data
        except Exception:
            continue

    # If no file decrypted successfully, die
    _die("Fichier de licence manquant ou invalide. Veuillez contacter : 0715125245")


def _die(message: str = _ERROR_MESSAGE) -> None:
    raise SystemExit(message)


def validate_or_exit() -> None:
    """
    Validate device fingerprint and license dates.

    Cloud / container deployment:
      Set the LICENSE_FINGERPRINT environment variable to the value stored
      in the license file's LICENSED_FINGERPRINT field (or use '*' for a
      wildcard license).  This bypasses hardware detection, which is
      unreliable in ephemeral containers where the hostname changes on
      every restart.
    """
    global _VALIDATED_IN_PROCESS
    if _VALIDATED_IN_PROCESS:
        return True

    license_data = _load_license_data()

    licensed_fingerprint = license_data.get("LICENSED_FINGERPRINT")
    if not isinstance(licensed_fingerprint, str):
        _die("Empreinte de licence invalide.")

    # If the license was issued with the wildcard '*', or AUTO_LICENSE is set, skip fingerprint check.
    if licensed_fingerprint != _WILDCARD_FINGERPRINT and not os.getenv("AUTO_LICENSE", "").lower() in ("true", "1", "yes"):
        # Allow an environment variable to override hardware detection.
        # Use this on cloud/container platforms where hardware IDs are
        # ephemeral.  Set LICENSE_FINGERPRINT to the hash stored in the
        # license file.
        env_fingerprint = os.getenv(_LICENSE_FINGERPRINT_ENV, "")
        if env_fingerprint:
            current_fingerprint = env_fingerprint
        else:
            try:
                current_fingerprint = get_fingerprint_hash()
            except Exception:
                _die()

        if not secrets.compare_digest(current_fingerprint, licensed_fingerprint):
            _die()

    start_date_str = license_data.get("START_DATE")
    end_date_str = license_data.get("END_DATE")
    if not isinstance(start_date_str, str) or not isinstance(end_date_str, str):
        _die("Dates de licence invalides.")

    try:
        start_date = datetime.date.fromisoformat(start_date_str)
        end_date = datetime.date.fromisoformat(end_date_str)
    except Exception:
        _die("Dates de licence invalides.")

    today = datetime.date.today()

    # Cloud environments auto-generate perpetual licenses; skip date check for cloud deployments.
    # On local environments, all licenses (wildcard or machine-locked) must respect their validity dates.
    if not _is_cloud_environment():
        if today < start_date:
            _die("La licence n'est pas encore active.")

        if today > end_date:
            _die("Votre période d'essai a expiré. Veuillez contacter : 0715125245")

    _VALIDATED_IN_PROCESS = True
    return True