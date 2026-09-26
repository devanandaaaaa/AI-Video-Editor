import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return base64.b64encode(salt + derived).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        decoded = base64.b64decode(stored.encode("ascii"))
        return hmac.compare_digest(hash_password(password, decoded[:16]), stored)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=7)).isoformat()
