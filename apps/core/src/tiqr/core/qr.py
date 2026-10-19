import base64
import hashlib
import hmac
import re
from datetime import date

PAYLOAD_LENGTH = 32
DAILY_CAPACITY = 99_999
PREFIX_LENGTH = 3
DEFAULT_PREFIX = "TQR"
# Payload layout: prefix, ":", YYMMDD-NNNNN, ":", signature.
SIGNATURE_LENGTH = PAYLOAD_LENGTH - PREFIX_LENGTH - len(":YYMMDD-NNNNN:")
_PREFIX = re.compile(rf"[!-~]{{{PREFIX_LENGTH}}}")


def validate_prefix(prefix: str) -> None:
    # ":" and "-" delimit the payload, so they stay out.
    if not _PREFIX.fullmatch(prefix) or any(mark in prefix for mark in ":-"):
        raise ValueError(
            f"Ticket prefix must be {PREFIX_LENGTH} printable ASCII characters without ':' or '-'"
        )


def _serial_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(prefix)}-([0-9]{{6}})-([0-9]{{5}})")


def _payload_pattern(prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"{re.escape(prefix)}:([0-9]{{6}})-([0-9]{{5}}):([A-Za-z0-9_-]{{{SIGNATURE_LENGTH}}})"
    )


def make_serial(counter: int, when: date, prefix: str = DEFAULT_PREFIX) -> str:
    if not 1 <= counter <= DAILY_CAPACITY:
        raise ValueError(f"Daily serial capacity of {DAILY_CAPACITY} exhausted")
    return f"{prefix}-{when:%y%m%d}-{counter:05d}"


def signature(serial: str, secret: str) -> str:
    if not secret:
        raise ValueError("A secret is required")
    digest = hmac.new(secret.encode(), serial.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:SIGNATURE_LENGTH]


def build_payload(serial: str, secret: str, prefix: str = DEFAULT_PREFIX) -> str:
    match = _serial_pattern(prefix).fullmatch(serial)
    if not match:
        raise ValueError("Invalid readable serial")
    day, sequence = match.groups()
    return f"{prefix}:{day}-{sequence}:{signature(serial, secret)}"


def verify_payload(payload: str, secret: str, prefix: str = DEFAULT_PREFIX) -> bool:
    match = _payload_pattern(prefix).fullmatch(payload)
    if not match:
        return False
    day, sequence, given = match.groups()
    expected = signature(f"{prefix}-{day}-{sequence}", secret)
    return hmac.compare_digest(given.encode(), expected.encode())
