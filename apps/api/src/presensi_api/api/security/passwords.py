from __future__ import annotations

import secrets

from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()

# Random ephemeral input avoids a hardcoded dummy password in the source tree.
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    stored_hash = password_hash or _DUMMY_PASSWORD_HASH
    try:
        verified = password_hasher.verify(password, stored_hash)
    except Exception:
        # A damaged or unsupported stored hash is treated as invalid credentials.
        return False
    return verified and password_hash is not None
