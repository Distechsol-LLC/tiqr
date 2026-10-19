import hashlib
import hmac
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from typing import NoReturn
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from tiqr.core.models import Role, User

_HASHER = PasswordHasher()
# One message for every login failure, so an unknown user looks like a bad password.
INVALID_CREDENTIALS = "Invalid username or password"
# How long a verified login stands in for the password.
SESSION_LIFETIME = timedelta(minutes=5)
# Browser sessions end after this long without a request, and after the lifetime regardless.
WEB_SESSION_IDLE = timedelta(minutes=30)
WEB_SESSION_LIFETIME = timedelta(hours=12)
# Requests this close together skip the seen-time write, so reads stay reads.
WEB_SESSION_TOUCH = timedelta(minutes=1)
SIGNED_OUT = "Not signed in, or the session has ended"
DEACTIVATED = "This account is deactivated"


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Session:
    """A recent successful login; the token is an HMAC, never the password."""

    username: str
    expires_at: datetime
    token: str


def session_token(secret_key: str, user: User, expires_at: datetime) -> str:
    # The password hash is signed too, so a password reset ends the cached login.
    message = f"{user.id}|{user.password_hash}|{int(expires_at.timestamp())}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def new_web_token() -> str:
    """A random browser session or CSRF token."""
    return secrets.token_urlsafe(32)


def web_token_hash(token: str) -> str:
    """What the database keeps instead of the token, so a copy of it signs nobody in."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    if not password.strip():
        raise ValueError("Password must not be empty")
    return _HASHER.hash(password)


def new_user(username: str, password: str, role: Role) -> User:
    username = username.strip()
    if not username:
        raise ValueError("Username is required")
    return User(uuid4(), username, hash_password(password), Role(role))


def verify_password(user: User, password: str) -> None:
    if not password.strip():
        raise AuthenticationError(INVALID_CREDENTIALS)
    try:
        _HASHER.verify(user.password_hash, password)
    except VerificationError as exc:
        raise AuthenticationError(INVALID_CREDENTIALS) from exc


@cache
def _decoy_hash() -> str:
    # Made on first use, so commands that never log anybody in skip the cost.
    return _HASHER.hash(secrets.token_hex(16))


def reject_unknown_user(password: str) -> NoReturn:
    """Refuse after as long as a real check takes, so timing can't reveal which usernames exist."""
    # A blank password skips the hash for real users too, so it does here.
    if password.strip():
        with suppress(VerificationError):
            _HASHER.verify(_decoy_hash(), password)
    raise AuthenticationError(INVALID_CREDENTIALS)
