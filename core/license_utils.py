from __future__ import annotations

import ast
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

LICENSE_FORMAT_VERSION = 1
KDF_ITERATIONS = 320000
KDF_LENGTH = 32
KDF_SALT_PREFIX = b"school_erp-license-v1:"


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_settings_path(project_root: Path | None = None) -> Path:
    root = project_root if project_root is not None else get_project_root()
    return root / "school_erp" / "settings.py"


LICENSE_SECRET = "Z9EPpLc1OM7yv2FO0sv0jlezIQ8YLf2Foj7ZFlMqf08"

def get_license_secret() -> str:
    return LICENSE_SECRET


def derive_license_key(secret_key: str, associated_data: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KDF_LENGTH,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(secret_key.encode("utf-8") + associated_data)


def _build_associated_data(output_name: str) -> bytes:
    return KDF_SALT_PREFIX + output_name.encode("utf-8")


def encrypt_license_payload(payload: dict, secret_key: str, output_name: str = "license.enc") -> dict:
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    associated_data = _build_associated_data(output_name)
    key = derive_license_key(secret_key, associated_data, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=associated_data)

    return {
        "version": LICENSE_FORMAT_VERSION,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_license_file(path: Path, secret_key: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != LICENSE_FORMAT_VERSION:
        raise RuntimeError("Unsupported license format version")

    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    ciphertext = base64.b64decode(payload["ciphertext"])

    # Attempt decryption with canonical 'license.enc' associated data first,
    # then fallback to path.name if different (e.g. for backups or custom names).
    candidate_names = ["license.enc"]
    if path.name not in candidate_names:
        candidate_names.append(path.name)

    last_error: Exception | None = None
    for name in candidate_names:
        try:
            associated_data = _build_associated_data(name)
            key = derive_license_key(secret_key, associated_data, salt)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data=associated_data)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to decrypt license payload")
