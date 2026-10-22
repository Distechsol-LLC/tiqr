from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from tiqr.core.qr import PAYLOAD_LENGTH

# Far above any real ticket, and well inside SQLite's integers and JSON's safe ones.
MAX_PRICE = 10**9
MAX_DISCOUNT = 100


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return value.astimezone(UTC)


def discounted(price: int, percent: int) -> int:
    """`price` less `percent` per cent, in the same minor units, rounding half up."""
    return (price * (MAX_DISCOUNT - percent) + MAX_DISCOUNT // 2) // MAX_DISCOUNT


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"


class Currency(StrEnum):
    USD = "USD"
    RUB = "RUB"
    AZN = "AZN"
    KZT = "KZT"


class UsageType(StrEnum):
    ONE_TIME = "one_time"
    MULTI_USE = "multi_use"


class TicketState(StrEnum):
    ISSUED = "issued"
    PASSED = "passed"
    EXPIRED = "expired"


class Outcome(StrEnum):
    APPLIED = "applied"
    DENIED = "denied"
    IGNORED_UNKNOWN_TICKET = "ignored_unknown_ticket"
    IGNORED_OUTSIDE_WINDOW = "ignored_outside_window"
    IGNORED_SECOND_ONE_TIME_SCAN = "ignored_second_one_time_scan"
    IGNORED_EXPIRED = "ignored_expired"


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    username: str
    password_hash: str
    role: Role
    # A deactivated account keeps its history and tickets but can neither sign in nor act.
    active: bool = True


@dataclass(frozen=True, slots=True)
class TicketType:
    """A kind of ticket and what it costs, in minor units such as cents."""

    id: UUID
    name: str
    price: int
    currency: Currency

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A name is required")
        if not 0 <= self.price <= MAX_PRICE:
            raise ValueError(f"Price must be between 0 and {MAX_PRICE}")


@dataclass(frozen=True, slots=True)
class VisitorType:
    """A kind of visitor and the share of a ticket's price taken off for them."""

    id: UUID
    name: str
    discount_percent: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A name is required")
        if not 0 <= self.discount_percent <= MAX_DISCOUNT:
            raise ValueError("Discount must be between 0 and 100 per cent")


@dataclass(frozen=True, slots=True)
class Ticket:
    id: UUID
    external_id: str | None
    qr_payload: str
    readable_serial: str
    visitor_name: str
    visitor_type: str
    valid_from: datetime
    valid_until: datetime
    usage_type: UsageType
    state: TicketState
    created_by: UUID
    assigned_operator: UUID
    created_at: datetime
    passed_at: datetime | None = None
    print_count: int = 0
    use_count: int = 0
    # Copied from the catalog when the ticket is made, so editing or deleting a catalog entry
    # later never changes what an issued ticket cost.
    ticket_type: str | None = None
    base_price: int | None = None
    discount_percent: int = 0
    currency: Currency | None = None

    def __post_init__(self) -> None:
        for name in ("valid_from", "valid_until", "created_at", "passed_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, utc(value))
        if self.valid_until < self.valid_from:
            raise ValueError("Access window ends before it starts")
        if len(self.qr_payload) != PAYLOAD_LENGTH or not self.qr_payload.isascii():
            raise ValueError(f"QR payload must be exactly {PAYLOAD_LENGTH} ASCII characters")
        if self.print_count < 0 or self.use_count < 0:
            raise ValueError("Ticket counters must not be negative")
        if self.base_price is not None and not 0 <= self.base_price <= MAX_PRICE:
            raise ValueError(f"Price must be between 0 and {MAX_PRICE}")
        if not 0 <= self.discount_percent <= MAX_DISCOUNT:
            raise ValueError("Discount must be between 0 and 100 per cent")

    @property
    def price(self) -> int | None:
        """What the visitor pays: the base price less the visitor type's discount."""
        return (
            None if self.base_price is None else discounted(self.base_price, self.discount_percent)
        )

    @property
    def is_spent(self) -> bool:
        """A one-time ticket that has already let its visitor through."""
        return self.state == TicketState.PASSED and self.usage_type == UsageType.ONE_TIME


@dataclass(frozen=True, slots=True)
class RawEvent:
    event_id: str
    external_id: str | None
    occurred_at: datetime
    granted: bool

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("An event ID is required")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class AccessEvent:
    event_id: str
    ticket_id: UUID | None
    occurred_at: datetime
    granted: bool
    outcome: Outcome
    processed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        object.__setattr__(self, "processed_at", utc(self.processed_at))


@dataclass(frozen=True, slots=True)
class WebSession:
    """A browser login. Only the token's hash is stored; the browser holds the token itself."""

    token_hash: str
    user_id: UUID
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("created_at", "last_seen_at", "expires_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class SyncCursor:
    token: str


@dataclass(frozen=True, slots=True)
class Registration:
    external_id: str
    card_id: str
    user_removed: bool = False
    card_removed: bool = False


@dataclass(frozen=True, slots=True)
class LicenseRecord:
    """A stored key. The key is the authority; the other columns only cache what it says."""

    license_key: str
    activated_at: datetime
    expires_at: datetime
    licensed_to: str
    is_active: bool = True
    id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "activated_at", utc(self.activated_at))
        object.__setattr__(self, "expires_at", utc(self.expires_at))
