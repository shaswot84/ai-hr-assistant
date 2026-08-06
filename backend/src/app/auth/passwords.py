from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (stdlib only, no deps).

    Returns a self-describing string: ``pbkdf2_sha256$<iterations>$<salt>$<hash>``
    (salt and hash are base64-encoded). A random 16-byte salt is generated per call.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "$".join(
        (
            _ALGORITHM,
            str(_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    """Compare a candidate password against a stored hash produced by `hash_password`.

    Uses ``hmac.compare_digest`` (constant-time) and tolerates any stored
    iteration count so hashes can be upgraded over time without invalidating users.
    """
    try:
        algorithm, iterations, salt_b64, hash_b64 = stored.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(digest, expected)
