"""Offline licensing: a vendor-signed key, checked against a public key built into this program.

A key is `base64(payload JSON).base64(signature)`: RSA-2048, PKCS#1 v1.5, SHA-256, over the raw
payload bytes. Nothing here signs; the private key stays with the vendor. Nothing is trusted
until the signature verifies, and the database only caches what the key says.
"""

import array
import base64
import binascii
import hashlib
import json
import platform
import re
import secrets
import socket
import struct
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_public_key

PRODUCT_ID = "tiqr"
SIGNATURE_BYTES = 256  # a 2048-bit modulus
TRIAL_DAYS = 30
# Rotating this means rebuilding and redelivering the program, and it voids every issued key.
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsR2RU6kCNQUVM3NdhRpG
0KR5I/YbCHiW7h/dkBUcNLA8qtZQn+JXz4zJlJwVbMk+6DPXf8k/J7USmjfuzy8T
/IFFqqQBSGpf8bnldP6DrqMSKERSffzQV5HkyEMI5An/vK3eHojjdJ7MK7rnLU1N
dHwzseLUwnoxybKDLsgqdN8pWDRbgRF4rX9u7E+O6+UC/aX2JY3xjTawQOwz0Dei
i2qy/e0HYeNBK1QE0B3ZgJzZxt2VuqSvEkG6CbHkjSx3nNAr0bpKGVZDEO8acZhZ
9eqOHC7qZo1MDiYIHKwvwQPLCAP2pZ2sXSNniLHwjnmk8FKynMVPKAUE6JgwGwZu
gQIDAQAB
-----END PUBLIC KEY-----
"""

_MACHINE_ID = re.compile(r"[0-9A-F]{32}")
_REQUEST_ID = re.compile(r"[0-9A-F]{16}")
_DAY_SECONDS = 86_400
_MAC_BYTES = 6


class LicenseType(StrEnum):
    TRIAL = "trial"
    STANDARD = "standard"


class LicenseState(StrEnum):
    NONE = "none"
    INVALID = "invalid"
    EXPIRED = "expired"
    ACTIVE = "active"


type RequestType = Literal["trial", "standard"]
REQUEST_TYPES: tuple[RequestType, ...] = ("trial", "standard")


class LicenseError(ValueError):
    """A key the program refuses. `code` is a slug the web client translates."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code


@dataclass(frozen=True, slots=True)
class LicensePayload:
    product: str
    type: LicenseType
    licensed_to: str
    issued_at: datetime
    expires_at: datetime
    machine_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class LicenseStatus:
    state: LicenseState
    machine_id: str
    type: LicenseType | None = None
    licensed_to: str | None = None
    expires_at: datetime | None = None
    days_remaining: int | None = None

    @property
    def is_valid(self) -> bool:
        return self.state == LicenseState.ACTIVE


@dataclass(frozen=True, slots=True)
class RequestCode:
    """A customer's request, as the vendor reads it. Untrusted until validated."""

    request_id: str
    machine_id: str
    request_type: RequestType
    contact: str | None


def _permanent_mac(name: str) -> str | None:
    """The burned-in address of a network card (ETHTOOL_GPERMADDR), or `None` if it won't say."""
    with suppress(ImportError, OSError, struct.error):
        import fcntl  # noqa: PLC0415 - Unix only; Windows never reaches here

        ethtool_get_permaddr, siocethtool, size = 0x20, 0x8946, 32
        buffer = array.array("B", struct.pack("II", ethtool_get_permaddr, size) + bytes(size))
        request = struct.pack("16sP", name.encode(), buffer.buffer_info()[0])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            fcntl.ioctl(probe.fileno(), siocethtool, request)
        length = struct.unpack_from("II", buffer)[1]
        if length == _MAC_BYTES:
            return ":".join(f"{byte:02x}" for byte in buffer[8 : 8 + length])
    return None


def _card_mac(interface: Path) -> str:
    """An interface's address. A physical card may show a temporary one, so use its real one.

    Network managers randomize a Wi-Fi card's address while scanning and put it back afterwards,
    so reading the live address made the fingerprint depend on when the program started.
    """
    live = (interface / "address").read_text().strip().lower()
    is_physical = (interface / "device").exists()
    assigned = (interface / "addr_assign_type").read_text().strip() if is_physical else "0"
    if assigned == "0":
        return live
    return _permanent_mac(interface.name) or ""  # no permanent address: skip it, don't guess


def _macs() -> list[str]:
    """Every hardware address, sorted: enumeration order is not guaranteed between boots."""
    found: set[str] = set()
    with suppress(OSError):  # no /sys/class/net off Linux, or in a stripped-down container
        for interface in Path("/sys/class/net").iterdir():
            with suppress(OSError):
                found.add(_card_mac(interface))
    if not found:
        node = uuid.getnode()
        # getnode() invents a random number when it finds no address; the multicast bit says so
        if not node >> 40 & 1:
            found.add(":".join(f"{node >> shift & 0xFF:02x}" for shift in range(40, -8, -8)))
    return sorted(found - {"", "00:00:00:00:00:00"})


def machine_id() -> str:
    """A stable fingerprint of this install: 32 uppercase hex.

    Owner-controlled inputs, so it identifies a machine without protecting against its owner.
    """
    parts = [socket.gethostname(), platform.system().lower(), platform.machine(), *_macs()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32].upper()


def build_request_code(request_type: RequestType, contact: str | None = None) -> str:
    request = {
        "product": PRODUCT_ID,
        "requestId": secrets.token_hex(8).upper(),
        "machineId": machine_id(),
        "requestType": request_type,
        **({"contact": contact} if contact else {}),
    }
    return base64.b64encode(json.dumps(request).encode()).decode()


def parse_request_code(code: str) -> RequestCode:
    """Validate a request code strictly; the vendor tooling reads customer input with this."""
    try:
        raw: Any = json.loads(base64.b64decode(code.strip(), validate=True))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The request code is not valid") from exc
    if not isinstance(raw, dict):
        raise ValueError("The request code is not valid")  # noqa: TRY004 - one error for callers
    fields = cast("dict[str, Any]", raw)
    contact = fields.get("contact")
    request_type = fields.get("requestType")
    if fields.get("product") != PRODUCT_ID:
        raise ValueError("The request is for another product")
    if not _full_match(_MACHINE_ID, fields.get("machineId")):
        raise ValueError("The machine ID is malformed")
    if not _full_match(_REQUEST_ID, fields.get("requestId")):
        raise ValueError("The request ID is malformed")
    if request_type not in REQUEST_TYPES:
        raise ValueError("The request type is not allowed")
    if contact is not None and not isinstance(contact, str):
        raise ValueError("The contact is malformed")
    return RequestCode(fields["requestId"], fields["machineId"], request_type, contact or None)


def _full_match(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _moment(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("A timestamp is required")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("A timestamp needs a UTC offset")
    return moment.astimezone(UTC)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("A string is required")
    return value


def _parse(raw: object) -> LicensePayload:
    if not isinstance(raw, dict):
        raise TypeError("The payload is not an object")
    fields = cast("dict[str, Any]", raw)
    return LicensePayload(
        product=_text(fields["product"]),
        type=LicenseType(fields["type"]),
        licensed_to=_text(fields["licensedTo"]),
        issued_at=_moment(fields["issuedAt"]),
        expires_at=_moment(fields["expiresAt"]),
        machine_id=_text(fields["machineId"]),
        request_id=_text(fields["requestId"]),
    )


def verify_license_key(license_key: str, public_key: str = PUBLIC_KEY) -> LicensePayload | None:
    """The payload when the signature and product check out; `None` for anything else.

    The JSON is parsed only after the signature verifies, and the signature covers the raw bytes.
    """
    try:
        parts = license_key.strip().split(".")
        if len(parts) != 2 or not all(parts):  # noqa: PLR2004 - payload and signature
            return None
        payload_bytes = base64.b64decode(parts[0], validate=True)
        signature = base64.b64decode(parts[1], validate=True)
        if len(signature) != SIGNATURE_BYTES:
            return None
        key = load_pem_public_key(public_key.encode())
        if not isinstance(key, rsa.RSAPublicKey):
            return None
        key.verify(signature, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
        payload = _parse(json.loads(payload_bytes))
    except InvalidSignature, binascii.Error, ValueError, TypeError, KeyError:
        return None
    return payload if payload.product == PRODUCT_ID else None


def days_between(now: datetime, expires_at: datetime) -> int:
    """Whole days left, rounded up, so the last day still reads as one."""
    seconds = (expires_at - now).total_seconds()
    return max(0, -int(-seconds // _DAY_SECONDS))


def check_machine(payload: LicensePayload) -> None:
    """Refuse a key issued for another machine; a missing ID is a refusal, never a wildcard."""
    current = machine_id()
    if not payload.machine_id or payload.machine_id != current:
        raise LicenseError(
            400,
            "license_wrong_machine",
            f"The key is for machine {payload.machine_id[:8]}, this is {current[:8]}",
        )
