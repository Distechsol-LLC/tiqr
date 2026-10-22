"""Request and response bodies. Responses carry what the CLI prints, never hashes or payloads."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tiqr.core.localtime import zone
from tiqr.core.models import (
    MAX_DISCOUNT,
    MAX_PRICE,
    Role,
    Ticket,
    TicketState,
    TicketType,
    UsageType,
    User,
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
    visitor_name: _Name
    visitor_type: _Name
    valid_from: _LocalDatetime
    valid_until: _LocalDatetime
    usage_type: UsageType
    ticket_type: Annotated[
        _Name | None,
        Field(description="Name of a ticket type; prices the ticket, less the visitor discount"),
    ] = None
    timezone: Annotated[
        str | None,
        StringConstraints(max_length=64),
        Field(description="IANA zone for offset-less times; default the server's TIQR_DEFAULT_TZ"),
    ] = None


class TicketTypeIn(_Request):
    name: _Name
    price_minor: _Price


class TicketTypePatch(_Request):
    """Any of: a new name, a new price. Omitted fields stay as they are."""

    name: _Name | None = None
    price_minor: _Price | None = None


class VisitorTypeIn(_Request):
    name: _Name
    discount_percent: _Discount = 0


class VisitorTypePatch(_Request):
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

    @classmethod
    def of(cls, ticket_type: TicketType) -> TicketTypeOut:
        return cls(id=ticket_type.id, name=ticket_type.name, price_minor=ticket_type.price)


class VisitorTypeOut(BaseModel):
    id: UUID
    name: str
    discount_percent: Annotated[int, Field(description="Per cent taken off a ticket's price")]

    @classmethod
    def of(cls, visitor_type: VisitorType) -> VisitorTypeOut:
        return cls(
            id=visitor_type.id,
            name=visitor_type.name,
            discount_percent=visitor_type.discount_percent,
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
    price_minor: Annotated[int | None, Field(description="The base price less the discount")]
    timezone: Annotated[str, Field(description="The zone every datetime here is shown in")]

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
            timezone=timezone,
        )


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
    total: int
    issued: int
    passed: int
    expired: int
    uses: int
    prints: int


class StatsOut(CountsOut):
    visitor_types: Annotated[
        dict[str, CountsOut], Field(description="The same counts for each visitor type")
    ]


class ConfigOut(BaseModel):
    timezone: Annotated[str, Field(description="TIQR_DEFAULT_TZ, for input and display")]
    server_printing: Annotated[bool, Field(description="Whether /print reaches a printer")]


class HealthOut(BaseModel):
    status: str
    version: str


# Every code the handlers, the security layer and the error handlers send.
ErrorCode = Literal[
    "unauthenticated",
    "forbidden",
    "csrf",
    "cross_origin",
    "not_found",
    "conflict",
    "server_printing_off",
    "invalid",
    "rate_limited",
    "printer",
    "biostar",
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
