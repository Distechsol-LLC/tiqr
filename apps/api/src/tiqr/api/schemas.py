"""Request and response bodies. Responses carry what the CLI prints, never hashes or payloads."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from tiqr.core.license import LicenseState, LicenseStatus, LicenseType
from tiqr.core.localtime import zone
from tiqr.core.models import (
    MAX_DISCOUNT,
    MAX_GROUP_SIZE,
    MAX_PRICE,
    ActiveHours,
    ApiKey,
    Currency,
    LicenseRecord,
    Mode,
    Role,
    Ticket,
    TicketState,
    TicketType,
    UsageType,
    User,
    VisitorSubtype,
    VisitorType,
    WebSession,
)

# Generous bounds: they stop runaway bodies, while the core decides what is valid.
_Name = Annotated[str, StringConstraints(max_length=200)]
_Username = Annotated[str, StringConstraints(max_length=150)]
_Password = Annotated[str, StringConstraints(max_length=1024)]
_Price = Annotated[
    int, Field(ge=0, le=MAX_PRICE, description="In minor units, such as cents: 1250 is 12.50")
]
_Discount = Annotated[
    int, Field(ge=0, le=MAX_DISCOUNT, description="Per cent taken off a ticket's price")
]
_Code = Annotated[
    str | None,
    StringConstraints(max_length=128),
    Field(
        description=(
            "The BioStar pass code, used unchanged; leading and trailing spaces are trimmed. "
            "Either alphanumeric (letters, digits and hyphens, up to 32 characters) or numeric "
            "(exactly 12 or 16 digits, leading zeros kept). Unique per tenant: a revoked pass's "
            "code stays taken."
        )
    ),
]
_Session = Annotated[
    str | None,
    StringConstraints(max_length=200),
    Field(description="The session or event the ticket admits to"),
]
_LocalDatetime = Annotated[
    str,
    StringConstraints(max_length=64),
    Field(
        description="ISO datetime with a time; without an offset it is read in `timezone`",
        examples=["2030-06-01T09:00", "2030-06-01T09:00:00+04:00"],
    ),
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(_Request):
    username: _Username
    password: _Password


class UserIn(_Request):
    username: _Username
    password: _Password
    role: Role


class UserPatch(_Request):
    """Any of: a new role, an active state, a new password. Omitted fields stay as they are."""

    role: Role | None = None
    active: Annotated[bool | None, Field(description="false deactivates; true reactivates")] = None
    password: Annotated[
        _Password | None, Field(description="Resets the password; ends the user's sessions")
    ] = None


class TicketIn(_Request):
    visitor_name: Annotated[
        _Name,
        Field(
            description="The visitor, which a badge needs; a ticket names no one, so it is dropped"
        ),
    ] = ""
    visitor_type: Annotated[
        _Name, Field(description="A visitor type from GET /visitor-types; any other name is a 422")
    ]
    visitor_subtype: Annotated[
        _Name | None,
        Field(
            description=(
                "Tickets: required, one of the visitor type's `subtypes`; the ticket carries its "
                "name as `visitor_type`, and its discount. Badges take none; sending one is a 422"
            )
        ),
    ] = None
    valid_from: _LocalDatetime
    valid_until: _LocalDatetime
    usage_type: Annotated[
        UsageType,
        Field(description="Tickets: one_time or group. Badges: multi_use; anything else is a 422"),
    ]
    group_size: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_GROUP_SIZE,
            description="People a group ticket admits, from 2; 1 for every other ticket",
        ),
    ] = 1
    ticket_type: Annotated[
        _Name | None,
        Field(description="Name of a ticket type; prices the ticket, less the visitor discount"),
    ] = None
    timezone: Annotated[
        str | None,
        StringConstraints(max_length=64),
        Field(description="IANA zone for offset-less times; default the server's TIQR_DEFAULT_TZ"),
    ] = None
    external_code: _Code = None
    event_session: _Session = None


_Timezone = Annotated[
    str | None,
    StringConstraints(max_length=64),
    Field(description="IANA zone for offset-less times; default the server's TIQR_DEFAULT_TZ"),
]
_Reason = Annotated[
    str | None, StringConstraints(max_length=500), Field(description="Why; stored in the audit log")
]


class TicketPatch(_Request):
    """Move the validity window; either end may be left out. The end must be after the start."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"valid_until": "2030-06-01T18:00"}]}
    )

    valid_from: _LocalDatetime | None = None
    valid_until: _LocalDatetime | None = None
    timezone: _Timezone = None


class RevokeIn(_Request):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"reason": "Lost card"}]}
    )

    reason: _Reason = None


class TransferIn(_Request):
    """Move a ticket to another session or event; the window may move with it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"event_session": "Matinee", "valid_until": "2030-06-01T16:00"}]
        },
    )

    event_session: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    valid_from: _LocalDatetime | None = None
    valid_until: _LocalDatetime | None = None
    timezone: _Timezone = None


class ReissueIn(_Request):
    """Reissue a ticket in any state; give a new window, or keep the old one."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"valid_until": "2030-06-01T18:00", "group_size": 3}]},
    )

    valid_from: _LocalDatetime | None = None
    valid_until: _LocalDatetime | None = None
    timezone: _Timezone = None
    group_size: Annotated[
        int | None,
        Field(
            ge=1,
            le=MAX_GROUP_SIZE,
            description=(
                "Group tickets only: the people it now admits, from 2; a group never becomes "
                "one-time, nor a one-time ticket a group, and it is refused once the current "
                "window has ended. Left out, it stays as it is"
            ),
        ),
    ] = None


class BatchItemIn(TicketIn):
    idempotency_key: Annotated[
        str | None,
        StringConstraints(max_length=255),
        Field(description="Per-item key; else the Idempotency-Key header plus `:index`"),
    ] = None


class BatchIn(_Request):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "atomic": True,
                    "items": [
                        {
                            "visitor_type": "Contractor",
                            "valid_from": "2030-06-01T09:00",
                            "valid_until": "2030-06-01T17:00",
                            "usage_type": "one_time",
                            "external_code": "BAR-0001",
                            "idempotency_key": "import-42-0",
                        }
                    ],
                }
            ]
        },
    )

    items: Annotated[list[BatchItemIn], Field(min_length=1, description="Tickets to create")]
    atomic: Annotated[
        bool,
        Field(
            description="true: all or nothing, undoing the created ones if any fails; "
            "false: every item stands or fails on its own"
        ),
    ] = False


class ServiceKeyIn(_Request):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "box-office",
                    "scopes": ["tickets:read", "tickets:write"],
                    "acts_as": "manager",
                }
            ]
        },
    )

    name: _Name
    scopes: Annotated[
        list[Literal["tickets:read", "tickets:write", "tickets:revoke", "passes:read"]],
        Field(min_length=1, description="What the key may do; reads, writes, revokes, or passages"),
    ]
    acts_as: Annotated[
        _Username | None, Field(description="Account the key acts as; default the caller's own")
    ] = None
    expires_at: Annotated[datetime | None, Field(description="Timezone-aware; default never")] = (
        None
    )


class ServiceKeyRotateIn(_Request):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"grace_minutes": 60}]}
    )

    grace_minutes: Annotated[
        int, Field(ge=0, le=10080, description="How long the old key keeps working")
    ] = 60


class TicketTypeIn(_Request):
    name: _Name
    price_minor: _Price
    currency: Annotated[Currency, Field(description="The currency the price is in")]


class TicketTypePatch(_Request):
    """Any of: a new name, a new price, a new currency. Omitted fields stay as they are."""

    name: _Name | None = None
    price_minor: _Price | None = None
    currency: Currency | None = None


_TypeDiscount = Annotated[
    int, Field(ge=0, le=MAX_DISCOUNT, description="Always 0: tickets take a subtype's discount")
]


class VisitorTypeIn(_Request):
    name: _Name
    discount_percent: _TypeDiscount = 0


class VisitorTypePatch(_Request):
    """A new name. Omitted fields stay as they are."""

    name: _Name | None = None
    discount_percent: _TypeDiscount | None = None


class VisitorSubtypeIn(_Request):
    name: Annotated[_Name, Field(description="Unique across every visitor type's subtypes")]
    discount_percent: _Discount = 0


class VisitorSubtypePatch(_Request):
    """Any of: a new name, a new discount. Omitted fields stay as they are."""

    name: _Name | None = None
    discount_percent: _Discount | None = None


class AssignIn(_Request):
    assignee: Annotated[_Username, Field(description="Username of any existing account")]


class UserOut(BaseModel):
    id: UUID
    username: str
    role: Role
    active: bool

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(id=user.id, username=user.username, role=user.role, active=user.active)


class TicketTypeOut(BaseModel):
    id: UUID
    name: str
    price_minor: Annotated[int, Field(description="In minor units, such as cents")]
    currency: Annotated[Currency, Field(description="The currency the price is in")]

    @classmethod
    def of(cls, ticket_type: TicketType) -> TicketTypeOut:
        return cls(
            id=ticket_type.id,
            name=ticket_type.name,
            price_minor=ticket_type.price,
            currency=ticket_type.currency,
        )


class VisitorSubtypeOut(BaseModel):
    id: UUID
    visitor_type_id: UUID
    name: str
    discount_percent: Annotated[int, Field(description="Per cent taken off a ticket's price")]

    @classmethod
    def of(cls, subtype: VisitorSubtype) -> VisitorSubtypeOut:
        return cls(
            id=subtype.id,
            visitor_type_id=subtype.visitor_type_id,
            name=subtype.name,
            discount_percent=subtype.discount_percent,
        )


class VisitorTypeOut(BaseModel):
    id: UUID
    name: str
    discount_percent: Annotated[int, Field(description="Always 0: tickets take a subtype's")]
    subtypes: Annotated[
        list[VisitorSubtypeOut],
        Field(description="By name; a ticket needs one. Always empty for badges"),
    ] = []

    @classmethod
    def of(
        cls, visitor_type: VisitorType, subtypes: list[VisitorSubtype] | None = None
    ) -> VisitorTypeOut:
        return cls(
            id=visitor_type.id,
            name=visitor_type.name,
            discount_percent=visitor_type.discount_percent,
            subtypes=[
                VisitorSubtypeOut.of(subtype)
                for subtype in subtypes or ()
                if subtype.visitor_type_id == visitor_type.id
            ],
        )


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: Annotated[str, Field(description="Send as X-CSRF-Token on every write request")]
    expires_at: Annotated[datetime, Field(description="When the session ends, however active")]
    idle_timeout: Annotated[int, Field(description="Seconds without a request that end it")]

    @classmethod
    def of(cls, user: User, session: WebSession, idle_timeout: int) -> SessionOut:
        return cls(
            user=UserOut.of(user),
            csrf_token=session.csrf_token,
            expires_at=session.expires_at,
            idle_timeout=idle_timeout,
        )


class TicketOut(BaseModel):
    id: UUID
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
    passed_at: datetime | None
    print_count: int
    use_count: int
    ticket_type: Annotated[str | None, Field(description="Null for a ticket made without one")]
    base_price_minor: Annotated[int | None, Field(description="The ticket type's price then")]
    discount_percent: Annotated[int, Field(description="The visitor type's discount then")]
    price_minor: Annotated[
        int | None, Field(description="The base price less the discount, times the group size")
    ]
    currency: Annotated[
        Currency | None, Field(description="The currency the price was in then; null without one")
    ]
    timezone: Annotated[str, Field(description="The zone every datetime here is shown in")]
    external_code: Annotated[str | None, Field(description="Your own code; null without one")] = (
        None
    )
    event_session: Annotated[str | None, Field(description="Null without one")] = None
    group_size: Annotated[
        int, Field(description="People the ticket admits; above 1 only for a group ticket")
    ] = 1

    @classmethod
    def of(cls, ticket: Ticket, timezone: str) -> TicketOut:
        local = zone(timezone)
        return cls(
            id=ticket.id,
            readable_serial=ticket.readable_serial,
            visitor_name=ticket.visitor_name,
            visitor_type=ticket.visitor_type,
            valid_from=ticket.valid_from.astimezone(local),
            valid_until=ticket.valid_until.astimezone(local),
            usage_type=ticket.usage_type,
            state=ticket.state,
            created_by=ticket.created_by,
            assigned_operator=ticket.assigned_operator,
            created_at=ticket.created_at.astimezone(local),
            passed_at=ticket.passed_at.astimezone(local) if ticket.passed_at else None,
            print_count=ticket.print_count,
            use_count=ticket.use_count,
            ticket_type=ticket.ticket_type,
            base_price_minor=ticket.base_price,
            discount_percent=ticket.discount_percent,
            price_minor=ticket.price,
            currency=ticket.currency,
            timezone=timezone,
            external_code=ticket.external_code,
            event_session=ticket.event_session,
            group_size=ticket.group_size,
        )


class BatchItemOut(BaseModel):
    index: int
    status: Annotated[
        Literal["created", "replayed", "error", "rolled_back", "skipped"],
        Field(description="replayed: the item's key had already created its ticket"),
    ]
    ticket_id: UUID | None = None
    ticket: TicketOut | None = None
    code: Annotated[str | None, Field(description="The error's code, as in a refusal")] = None
    error: str | None = None


class BatchOut(BaseModel):
    atomic: bool
    committed: Annotated[
        bool, Field(description="false only when an all-or-nothing batch was undone")
    ]
    created: int
    failed: int
    results: list[BatchItemOut]


class ServiceKeyOut(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    acts_as: UUID
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    replaced_by: UUID | None

    @classmethod
    def of(cls, key: ApiKey) -> ServiceKeyOut:
        return cls(
            id=key.id,
            name=key.name,
            scopes=list(key.scopes),
            acts_as=key.user_id,
            created_at=key.created_at,
            expires_at=key.expires_at,
            revoked_at=key.revoked_at,
            replaced_by=key.replaced_by,
        )


class ServiceKeyCreated(ServiceKeyOut):
    secret: Annotated[str, Field(description="Shown once; send as `Authorization: Bearer`")]


class AuditOut(BaseModel):
    id: UUID
    occurred_at: datetime
    actor: str
    action: str
    ticket_id: UUID | None
    reason: str | None
    detail: str | None


class PassageOut(BaseModel):
    """One passage. A multi-use pass gives one record per passage."""

    event_id: str
    ticket_id: UUID | None
    external_code: str | None
    event_time: datetime
    point_id: str | None
    point_name: str | None
    direction: Annotated[str | None, Field(description="entry or exit, when BioStar says")]
    granted: bool
    outcome: Annotated[
        str,
        Field(
            description="applied, denied, ignored_unknown_ticket, ignored_outside_window, "
            "ignored_second_one_time_scan or ignored_expired; new values may appear later"
        ),
    ]


class PassagePage(BaseModel):
    items: list[PassageOut]
    next_cursor: Annotated[
        int,
        Field(description="Pass this as `after` to read on; repeating it returns the same items"),
    ]


class _Page(BaseModel):
    total: Annotated[int, Field(description="Every match, across all pages")]
    page: Annotated[int, Field(description="The page shown, from 1")]
    size: Annotated[int, Field(description="Most items on a page")]


class UserPage(_Page):
    items: list[UserOut]


class TicketPage(_Page):
    items: list[TicketOut]


class TicketTypePage(_Page):
    items: list[TicketTypeOut]


class VisitorTypePage(_Page):
    items: list[VisitorTypeOut]


class CountOut(BaseModel):
    count: int


class CountsOut(BaseModel):
    """Ticket counts weigh a group ticket by its size, so a group of ten counts as ten."""

    total: int
    issued: int
    passed: int
    expired: int
    prints: Annotated[int, Field(description="Badges made, summed over the tickets")]
    passes: Annotated[int, Field(description="Passages made, summed over the tickets")]


class VisitorStatsOut(CountsOut):
    ticket_types: Annotated[
        dict[str, CountsOut],
        Field(description="The same counts for each ticket type of this visitor type"),
    ]


class StatsOut(CountsOut):
    visitor_types: Annotated[
        dict[str, VisitorStatsOut],
        Field(description="The same counts for each visitor type, split by ticket type"),
    ]
    ticket_types: Annotated[
        dict[str, CountsOut],
        Field(description="The same counts for each ticket type; empty name for none"),
    ]


class ConfigOut(BaseModel):
    timezone: Annotated[str, Field(description="TIQR_DEFAULT_TZ, for input and display")]
    server_printing: Annotated[bool, Field(description="Whether /print reaches a printer")]


# A time of day on the 24-hour clock, such as 09:00
_Clock = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class ActiveHoursIn(_Request):
    """Both times, or neither to lift the limit. The times are in the server's timezone."""

    start: Annotated[
        _Clock | None, Field(description="HH:MM, when tickets may start being made")
    ] = None
    end: Annotated[
        _Clock | None,
        Field(description="HH:MM, when they stop; before the start, the hours run past midnight"),
    ] = None

    @model_validator(mode="after")
    def _both_or_neither(self) -> ActiveHoursIn:
        if (self.start is None) != (self.end is None):
            raise ValueError("Give both a start and an end, or neither")
        return self


class ActiveHoursOut(BaseModel):
    start: Annotated[str | None, Field(description="HH:MM, or null when any time is allowed")]
    end: Annotated[str | None, Field(description="HH:MM, or null when any time is allowed")]
    timezone: Annotated[str, Field(description="The zone the times are in")]

    @classmethod
    def of(cls, hours: ActiveHours | None, timezone: str) -> ActiveHoursOut:
        if hours is None:
            return cls(start=None, end=None, timezone=timezone)
        return cls(
            start=hours.start.isoformat(timespec="minutes"),
            end=hours.end.isoformat(timespec="minutes"),
            timezone=timezone,
        )


class BrandingOut(BaseModel):
    app_name: Annotated[str, Field(description="app_name, for titles and the header")]
    theme: Annotated[str, Field(description="theme: default, light, dark or a Skeleton theme name")]
    languages: Annotated[
        list[str],
        Field(
            description="languages, such as en-US: what the switcher offers, "
            "first is the fallback default"
        ),
    ]
    currencies: Annotated[
        list[Currency], Field(description="The currencies of the languages' regions")
    ]
    has_logo: Annotated[bool, Field(description="Whether /api/logo serves logo_path")]
    mode: Annotated[Mode, Field(description="Whether the install issues tickets or badges")] = (
        Mode.TICKET
    )


class ModeIn(_Request):
    mode: Annotated[Mode, Field(description="ticket or badge; each keeps its own database")]


class ModeOut(BaseModel):
    mode: Mode
    pinned: Annotated[
        bool, Field(description="Whether TIQR_MODE is set in the environment, so it cannot switch")
    ]


class LicenseStatusOut(BaseModel):
    """Verified against the signed key on every read; only `none` and `invalid` hide the rest."""

    state: LicenseState
    is_valid: Annotated[bool, Field(description="True only for a live trial or paid license")]
    machine_id: Annotated[str, Field(description="This install's fingerprint, in every state")]
    type: LicenseType | None = None
    licensed_to: str | None = None
    expires_at: datetime | None = None
    days_remaining: int | None = None

    @classmethod
    def of(cls, status: LicenseStatus) -> LicenseStatusOut:
        return cls(
            state=status.state,
            is_valid=status.is_valid,
            machine_id=status.machine_id,
            type=status.type,
            licensed_to=status.licensed_to,
            expires_at=status.expires_at,
            days_remaining=status.days_remaining,
        )


class RequestCodeOut(BaseModel):
    code: Annotated[str, Field(description="Send this to the vendor to get a key")]


class ActivateIn(BaseModel):
    license_key: Annotated[str, StringConstraints(max_length=4096)]


class LicenseRecordOut(BaseModel):
    id: int
    is_active: bool
    activated_at: datetime
    expires_at: datetime
    licensed_to: str
    key_hint: Annotated[str, Field(description="Both ends of the key; it is a working credential")]

    @classmethod
    def of(cls, record: LicenseRecord) -> LicenseRecordOut:
        key = record.license_key
        return cls(
            id=record.id or 0,
            is_active=record.is_active,
            activated_at=record.activated_at,
            expires_at=record.expires_at,
            licensed_to=record.licensed_to,
            key_hint=f"{key[:8]}…{key[-6:]}",
        )


class HealthOut(BaseModel):
    status: str
    version: str


# Every code the handlers, the security layer and the error handlers send.
ErrorCode = Literal[
    "unauthenticated",
    "forbidden",
    "scope",
    "csrf",
    "cross_origin",
    "not_found",
    "conflict",
    "external_code_taken",
    "outside_active_hours",
    "idempotency_mismatch",
    "invalid_state",
    "credential_format",
    "server_printing_off",
    "mode_pinned",
    "invalid",
    "batch_too_large",
    "rate_limited",
    "printer",
    "biostar",
    "license_required",
    "license_bad_signature",
    "license_wrong_machine",
    "license_already_expired",
    "license_trial_over_paid",
    "license_already_active",
    "internal",
]


class ErrorOut(BaseModel):
    """A refusal: a message to show, and a stable code to branch on."""

    detail: str
    code: ErrorCode


class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str
    input: Any = None
    ctx: dict[str, Any] | None = None


class FieldErrorsOut(BaseModel):
    """A malformed request, as FastAPI reports it: one entry per bad field."""

    detail: list[FieldError]
