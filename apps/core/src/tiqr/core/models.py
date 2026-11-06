from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from uuid import UUID

from tiqr.core.qr import PAYLOAD_LENGTH

# Far above any real ticket, and well inside SQLite's integers and JSON's safe ones.
MAX_PRICE = 10**11
MAX_DISCOUNT = 100
# The most people one group ticket admits; a group is at least two, or it is a one-time ticket.
MAX_GROUP_SIZE = 100
MIN_GROUP_SIZE = 2
DEFAULT_TENANT = "default"


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return value.astimezone(UTC)


def discounted(price: int, percent: int) -> int:
    """`price` less `percent` per cent, in the same minor units, rounding half up."""
    return (price * (MAX_DISCOUNT - percent) + MAX_DISCOUNT // 2) // MAX_DISCOUNT


def _check_group(usage_type: UsageType, group_size: int) -> None:
    if usage_type == UsageType.GROUP:
        if not MIN_GROUP_SIZE <= group_size <= MAX_GROUP_SIZE:
            raise ValueError(f"A group is from {MIN_GROUP_SIZE} to {MAX_GROUP_SIZE} people")
    elif group_size != 1:
        raise ValueError("Only a group ticket admits more than one person")


class Role(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"


class Currency(StrEnum):
    USD = "USD"
    RUB = "RUB"
    AZN = "AZN"
    KZT = "KZT"


class Mode(StrEnum):
    """What the install issues; each mode keeps its own database.

    Tickets carry no visitor name and admit once, or once per person of a group. Badges carry a
    visitor's name, have no ticket types or prices, and admit as often as their window allows.
    """

    TICKET = "ticket"
    BADGE = "badge"


class UsageType(StrEnum):
    ONE_TIME = "one_time"
    MULTI_USE = "multi_use"
    # One QR code for `group_size` people: it admits that many passages, then stops.
    GROUP = "group"


class TicketState(StrEnum):
    ISSUED = "issued"
    PASSED = "passed"
    EXPIRED = "expired"
    REVOKED = "revoked"


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
class VisitorSubtype:
    """A kind of visitor within a visitor type, and the share of a ticket's price taken off.

    Tickets mode only: a ticket is issued for a subtype, and carries its name and discount in
    place of the type's. Names are unique across every type, so a name alone finds one.
    """

    id: UUID
    visitor_type_id: UUID
    name: str
    discount_percent: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A name is required")
        if not 0 <= self.discount_percent <= MAX_DISCOUNT:
            raise ValueError("Discount must be between 0 and 100 per cent")


@dataclass(frozen=True, slots=True)
class VisitorType:
    """A kind of visitor. Badges use it as it is; tickets use one of its subtypes, which carry
    the discount, so a ticket mode type keeps none of its own."""

    id: UUID
    name: str
    discount_percent: int = 0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A name is required")
        if not 0 <= self.discount_percent <= MAX_DISCOUNT:
            raise ValueError("Discount must be between 0 and 100 per cent")


@dataclass(frozen=True, slots=True)
class ActiveHours:
    """The local times of day tickets may be created: from `start` up to `end`. An `end` before
    the `start` runs past midnight, so 22:00 to 06:00 covers the night."""

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise ValueError("Active hours must start and end at different times")

    def allows(self, moment: time) -> bool:
        """Whether the wall-clock time `moment` falls inside the hours; `end` itself does not."""
        if self.start < self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


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
    # The caller's own ticket code or barcode value; unique per tenant when set.
    external_code: str | None = None
    tenant_id: str = DEFAULT_TENANT
    # The session or event the ticket admits to; free text, moved by a session transfer.
    event_session: str | None = None
    # How many people the ticket admits: above one only for a group ticket.
    group_size: int = 1

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
        _check_group(self.usage_type, self.group_size)

    @property
    def price(self) -> int | None:
        """What the visitor pays: the base price less the visitor type's discount, per person."""
        if self.base_price is None:
            return None
        return discounted(self.base_price, self.discount_percent) * self.group_size

    @property
    def is_spent(self) -> bool:
        """A one-time ticket that has let its visitor through, or a group ticket its whole group."""
        if self.state != TicketState.PASSED:
            return False
        if self.usage_type == UsageType.GROUP:
            return self.use_count >= self.group_size
        return self.usage_type == UsageType.ONE_TIME


@dataclass(frozen=True, slots=True)
class RawEvent:
    event_id: str
    external_id: str | None
    occurred_at: datetime
    granted: bool
    point_id: str | None = None
    point_name: str | None = None
    direction: str | None = None

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
    point_id: str | None = None
    point_name: str | None = None
    direction: str | None = None
    sequence: int = 0

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
    external_card_id: str | None = None


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


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One state-changing action: who did what to which ticket, when, and why."""

    id: UUID
    occurred_at: datetime
    actor: str
    action: str
    ticket_id: UUID | None = None
    reason: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))


@dataclass(frozen=True, slots=True)
class StoredResponse:
    """A saved answer to an Idempotency-Key, replayed for the same key and payload."""

    key: str
    tenant_id: str
    fingerprint: str
    status: int
    body: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ApiKey:
    """A service credential: only its hash is stored; it acts as `user_id` within `scopes`."""

    id: UUID
    name: str
    key_hash: str
    user_id: UUID
    scopes: tuple[str, ...]
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by: UUID | None = None
