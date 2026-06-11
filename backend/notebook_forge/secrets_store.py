"""Secret lookup: OS keychain first (via keyring), env var fallback.

Locked decision: secrets live in the keychain; the settings table records
only which keys exist and their last-verified status. Nothing here ever
writes a secret to disk, DB or logs.
"""

from __future__ import annotations

import os

KEYRING_SERVICE = "notebook-forge"


def get_secret(name: str, env: str | None = None) -> str | None:
    try:
        import keyring

        value = keyring.get_password(KEYRING_SERVICE, name)
        if value:
            return value
    except Exception:
        pass
    if env:
        return os.environ.get(env) or None
    return None
