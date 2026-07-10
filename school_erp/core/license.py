from __future__ import annotations

import datetime
import os
import secrets
from typing import Final

from .hardware import get_fingerprint_hash
from .license_utils import (
    decrypt_license_file,
    get_project_root,
    get_license_secret,
)



_LICENSE_FILE_NAME: Final[str] = "license.enc"
_LICENSE_EXTRA_SECRET_ENV: Final[str] = "LICENSE_EXTRA_SECRET"
_ERROR_MESSAGE: Final[str] = "This copy of the application is not licensed for this device."


def _load_license_data() -> dict:
    project_root = get_project_root()
    license_path = project_root / _LICENSE_FILE_NAME
    if not license_path.exists():
        _die("License file missing.")

    secret_key = get_license_secret()
    extra_secret = os.getenv(_LICENSE_EXTRA_SECRET_ENV, "")
    if extra_secret:
        secret_key += extra_secret

    try:
        data = decrypt_license_file(license_path, secret_key)
    except Exception:
        _die("Invalid license file.")

    if not isinstance(data, dict):
        _die("Invalid license content.")

    return data


def _die(message: str = _ERROR_MESSAGE) -> None:
    raise SystemExit(message)


def validate_or_exit() -> None:
    """
    Validate device fingerprint and license dates.
    """

    try:
        current_fingerprint = get_fingerprint_hash()
    except Exception:
        _die()

    license_data = _load_license_data()

    licensed_fingerprint = license_data.get("LICENSED_FINGERPRINT")
    if not isinstance(licensed_fingerprint, str):
        _die("Invalid license fingerprint.")

    if not secrets.compare_digest(current_fingerprint, licensed_fingerprint):
        _die()

    start_date_str = license_data.get("START_DATE")
    end_date_str = license_data.get("END_DATE")
    if not isinstance(start_date_str, str) or not isinstance(end_date_str, str):
        _die("Invalid license dates.")

    try:
        start_date = datetime.date.fromisoformat(start_date_str)
        end_date = datetime.date.fromisoformat(end_date_str)
    except Exception:
        _die("Invalid license dates.")

    today = datetime.date.today()

    if today < start_date:
        _die("License not active yet.")

    if today > end_date:
        _die("Trial period expired. Please contact the vendor in 0661345595.")

    return True