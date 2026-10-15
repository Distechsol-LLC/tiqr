import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from tiqr.models import Role, User

_HASHER = PasswordHasher()
# One message for every login failure, so callers cannot tell an unknown user from a bad password.
INVALID_CREDENTIALS = "Invalid username or password"
# How long a verified login can stand in for the password before the next command asks again.
SESSION_LIFETIME = timedelta(minutes=5)


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Session:
    """A recent successful login. The token is an HMAC, so the password itself is never stored."""

    username: str
    expires_at: datetime
    token: str


def session_token(secret_key: str, user_id: UUID, expires_at: datetime) -> str:
    message = f"{user_id}|{int(expires_at.timestamp())}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def new_user(username: str, password: str, role: Role) -> User:
    username = username.strip()
    if not username:
        raise ValueError("Username is required")
    if not password.strip():
        raise ValueError("Password must not be empty")
    return User(uuid4(), username, _HASHER.hash(password), Role(role))


def verify_password(user: User, password: str) -> None:
    if not password.strip():
        raise AuthenticationError(INVALID_CREDENTIALS)
    try:
        _HASHER.verify(user.password_hash, password)
    except VerificationError as exc:
        raise AuthenticationError(INVALID_CREDENTIALS) from exc
