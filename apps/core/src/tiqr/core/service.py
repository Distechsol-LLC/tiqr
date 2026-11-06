import hashlib
import hmac
import logging
import re
import secrets
import threading
from collections import Counter
from collections.abc import Callable, Collection, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from pathlib import Path
from typing import TypedDict
from uuid import UUID, uuid4

from tiqr.core.auth import (
    DEACTIVATED,
    INVALID_CREDENTIALS,
    SESSION_LIFETIME,
    SIGNED_OUT,
    WEB_SESSION_IDLE,
    WEB_SESSION_LIFETIME,
    WEB_SESSION_TOUCH,
    AuthenticationError,
    Session,
    hash_password,
    new_user,
    new_web_token,
    reject_unknown_user,
    session_token,
    verify_password,
    web_token_hash,
)
from tiqr.core.biostar import BioStarClient, BioStarXEventSource, BioStarXRegistrar
from tiqr.core.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.core.license import (
    PUBLIC_KEY,
    LicenseError,
    LicensePayload,
    LicenseState,
    LicenseStatus,
    LicenseType,
    build_request_code,
    check_machine,
    days_between,
    machine_id,
    verify_license_key,
)
from tiqr.core.localtime import day_start, zone
from tiqr.core.models import (
    DEFAULT_TENANT,
    MAX_GROUP_SIZE,
    MIN_GROUP_SIZE,
    AccessEvent,
    ActiveHours,
    ApiKey,
    AuditEntry,
    Currency,
    LicenseRecord,
    Mode,
    Outcome,
    RawEvent,
    Role,
    StoredResponse,
    Ticket,
    TicketState,
    TicketType,
    UsageType,
    User,
    VisitorType,
    WebSession,
    utc,
)
from tiqr.core.ports import Clock, EventSource, PdfRenderer, Registrar, Repository
from tiqr.core.qr import DEFAULT_PREFIX, build_payload, make_serial, validate_prefix
from tiqr.core.repository import SQLiteRepository
from tiqr.core.settings import BioStarSettings, validate_secret

_ADMINS = frozenset({Role.ADMIN})
_STAFF = frozenset({Role.ADMIN, Role.MANAGER})
_TRANSITIONS = frozenset(
    {
        (TicketState.ISSUED, TicketState.PASSED),
        (TicketState.ISSUED, TicketState.EXPIRED),
        (TicketState.PASSED, TicketState.EXPIRED),
        (TicketState.ISSUED, TicketState.REVOKED),
        (TicketState.PASSED, TicketState.REVOKED),
    }
)
# Revoked and expired are final: neither grants access, and neither can be revived.
_FINAL = frozenset({TicketState.EXPIRED, TicketState.REVOKED})
_MAX_REASON = 500
_MAX_CODE = 128
_MAX_PASSAGES = 500
KEY_PREFIX = "tqk_"
SCOPE_READ = "tickets:read"
SCOPE_WRITE = "tickets:write"
SCOPE_REVOKE = "tickets:revoke"
SCOPE_PASSES = "passes:read"
SCOPES = frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_REVOKE, SCOPE_PASSES})
# Who an action is credited to when it is not the account itself, such as an API key.
_ATTRIBUTION: ContextVar[str | None] = ContextVar("tiqr_attribution", default=None)


class _Unset:
    """Marks an argument left out, since None is a valid value for it."""


_UNSET = _Unset()
audit_logger = logging.getLogger("tiqr.audit")


def _clean_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("A name is required")
    return name


def _can_view(actor: User, ticket: Ticket) -> bool:
    return actor.role != Role.OPERATOR or ticket.assigned_operator == actor.id


def _matches(ticket: Ticket, needle: str) -> bool:
    fields = (
        ticket.readable_serial,
        ticket.visitor_name,
        ticket.visitor_type,
        ticket.ticket_type,
        ticket.external_code,
    )
    return any(needle in (field or "").casefold() for field in fields)


def _counts(tickets: list[Ticket]) -> Counts:
    # A group ticket counts once per person it admits, so ten people read as ten tickets.
    states: Counter[TicketState] = Counter()
    for ticket in tickets:
        states[ticket.state] += ticket.group_size
    return Counts(
        total=sum(ticket.group_size for ticket in tickets),
        issued=states[TicketState.ISSUED],
        passed=states[TicketState.PASSED],
        expired=states[TicketState.EXPIRED],
        prints=sum(ticket.print_count for ticket in tickets),
        passes=sum(ticket.use_count for ticket in tickets),
    )


def _by_ticket_type(tickets: list[Ticket]) -> dict[str, Counts]:
    groups: dict[str, list[Ticket]] = {}
    for ticket in tickets:
        # Tickets made without a ticket type are grouped under an empty name
        groups.setdefault(ticket.ticket_type or "", []).append(ticket)
    return {name: _counts(group) for name, group in sorted(groups.items())}


class PermissionDeniedError(PermissionError):
    pass


class StateError(ValueError):
    code = "conflict"


class ExternalCodeTakenError(StateError):
    code = "external_code_taken"


class InvalidStateError(StateError):
    code = "invalid_state"


class OutsideActiveHoursError(StateError):
    code = "outside_active_hours"


class ModeError(ValueError):
    """Something the install's mode does not offer, such as a price on a badge."""


class CredentialFormatError(ValueError):
    """An external code the venue's readers cannot read, refused before anything is written."""


class NotFoundError(LookupError):
    pass


class IdempotencyConflictError(StateError):
    """An Idempotency-Key was reused with a different payload."""

    code = "idempotency_mismatch"


def _clean_reason(reason: str | None) -> str | None:
    reason = (reason or "").strip()
    if len(reason) > _MAX_REASON:
        raise ValueError(f"A reason is at most {_MAX_REASON} characters")
    return reason or None


# The readers take either an alphanumeric code (letters, digits, hyphen, up to 32 characters) or
# a fixed-length numeric one, leading zeros included. Anything else is refused before any write.
_ALPHANUMERIC_CODE = re.compile(r"[A-Za-z0-9-]{1,32}")
_NUMERIC_CODE = re.compile(r"[0-9]{12}|[0-9]{16}")
_DIGITS = re.compile(r"[0-9]+")


def _clean_code(code: str | None) -> str | None:
    code = (code or "").strip()
    if len(code) > _MAX_CODE:
        raise ValueError(f"An external code is at most {_MAX_CODE} characters")
    # Digits-only codes are numeric, so they must have the fixed numeric length.
    numeric = bool(code) and _DIGITS.fullmatch(code) is not None
    readable = _NUMERIC_CODE.fullmatch(code) if numeric else _ALPHANUMERIC_CODE.fullmatch(code)
    if code and not readable:
        raise CredentialFormatError(
            "External code must be 12 or 16 digits, or up to 32 letters, digits or hyphens"
        )
    return code or None


def key_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Counts(TypedDict):
    total: int
    issued: int
    passed: int
    expired: int
    prints: int
    passes: int


class VisitorStats(Counts):
    ticket_types: dict[str, Counts]


class Stats(Counts):
    visitor_types: dict[str, VisitorStats]
    ticket_types: dict[str, Counts]


class TicketService:
    def __init__(  # noqa: PLR0913 - collaborators and options, all keyword-only past four
        self,
        repository: Repository,
        secret_key: str,
        registrar: Registrar | None = None,
        event_source: EventSource | None = None,
        *,
        clock: Clock | None = None,
        prefix: str = DEFAULT_PREFIX,
        license_public_key: str = PUBLIC_KEY,
        tenant: str = DEFAULT_TENANT,
        timezone: str = "UTC",
        mode: Mode = Mode.TICKET,
    ) -> None:
        validate_secret(secret_key)
        validate_prefix(prefix)
        zone(timezone)
        self.repository = repository
        self.secret_key = secret_key
        self.prefix = prefix
        self._license_public_key = license_public_key
        self.registrar: Registrar = registrar or InMemoryRegistrar()
        self.event_source: EventSource = event_source or InMemoryEventSource()
        self._clock: Clock = clock or partial(datetime.now, UTC)
        self.tenant = tenant
        # The zone the active hours are read in: the server's own, as its clock shows it
        self.timezone = timezone
        # Held across a keyed request's lookup, work and save, so a retry cannot run it twice.
        self.idempotency_lock = threading.RLock()
        # Told each passage a sync has committed; set by the server when a webhook is configured.
        self.on_passage: Callable[[AccessEvent], None] | None = None
        # The swappable BioStar connection, set by `open_service`; None where none is managed.
        self.biostar_link: BioStarLink | None = None
        # Badges or tickets; `mode_switch` moves the service between their databases.
        self.mode = Mode(mode)
        self.mode_switch: ModeSwitch | None = None

    def _now(self) -> datetime:
        return utc(self._clock())

    @staticmethod
    @contextmanager
    def attributed(label: str | None) -> Generator[None]:
        """Credit the audit entries made inside the block to `label`, such as an API key."""
        token = _ATTRIBUTION.set(label)
        try:
            yield
        finally:
            _ATTRIBUTION.reset(token)

    def _record(
        self,
        actor: User,
        action: str,
        ticket: Ticket | None = None,
        *,
        reason: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Write one audit entry, in the caller's transaction when there is one."""
        via = _ATTRIBUTION.get()
        name = f"{via} (as {actor.username})" if via else actor.username
        entry = AuditEntry(
            uuid4(), self._now(), name, action, ticket.id if ticket else None, reason, detail
        )
        self.repository.add_audit(entry)
        audit_logger.info(
            "actor=%s at=%s action=%s ticket=%s reason=%s detail=%s",
            entry.actor,
            entry.occurred_at.isoformat(),
            action,
            entry.ticket_id,
            reason,
            detail,
        )

    def audit_trail(self, actor: User, ticket_id: UUID | None = None) -> list[AuditEntry]:
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        return self.repository.list_audit(ticket_id)

    def ping(self) -> bool:
        """Whether the store answers; the health check asks without an account."""
        return self.repository.ping()

    def add_user(self, username: str, password: str, role: Role) -> User:
        user = new_user(username, password, role)
        with self.repository.transaction():
            if self.repository.user_by_name(user.username):
                raise ValueError("Username already exists")
            if user.role == Role.ADMIN and self._admin_exists():
                raise StateError("Only one admin account can exist")
            self.repository.add_user(user)
        return user

    def list_users(self) -> list[User]:
        return self.repository.list_users()

    def create_user(self, actor: User, username: str, password: str, role: Role) -> User:
        """`add_user` for an authenticated caller rather than the trusted local OS account.

        Admins create any role; managers create operators only.
        """
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        if actor.role == Role.MANAGER and Role(role) != Role.OPERATOR:
            raise PermissionDeniedError("Managers can only create operators")
        return self.add_user(username, password, role)

    def list_accounts(self, actor: User) -> list[User]:
        """`list_users` for an authenticated caller; managers need it to pick assignees."""
        self._require(self._actor(actor), _STAFF)
        return self.list_users()

    def find_user(self, username: str) -> User:
        user = self.repository.user_by_name(username.strip())
        if user is None:
            raise NotFoundError("User not found")
        return user

    def edit_user(
        self,
        user_id: UUID,
        *,
        role: Role | None = None,
        active: bool | None = None,
        password: str | None = None,
    ) -> User:
        """Change a role, (de)activate, or reset a password, as the trusted local OS account.

        Deactivating or resetting a password ends the user's sessions; a new role applies from
        their next request. The last active admin can be neither demoted nor deactivated, so
        somebody can always manage accounts. Only one admin account can exist, so promoting
        someone demotes the current admin to manager.
        """
        if role is None and active is None and password is None:
            raise ValueError("Nothing to change")
        # Hashed before the transaction, so the write lock isn't held for Argon2.
        password_hash = None if password is None else hash_password(password)
        with self.repository.transaction():
            user = self.repository.user_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")
            updated = replace(
                user,
                role=user.role if role is None else Role(role),
                active=user.active if active is None else active,
                password_hash=password_hash or user.password_hash,
            )
            if updated.role == Role.ADMIN and user.role != Role.ADMIN:
                admins = [
                    other for other in self.repository.list_users() if other.role == Role.ADMIN
                ]
                if admins and not updated.active:
                    raise StateError("A deactivated account cannot replace the admin")
                # Only one admin exists, so the one being replaced becomes a manager.
                for admin in admins:
                    self.repository.save_user(replace(admin, role=Role.MANAGER))
            if self._is_active_admin(user) and not self._is_active_admin(updated):
                admins = [
                    other for other in self.repository.list_users() if self._is_active_admin(other)
                ]
                if len(admins) <= 1:
                    raise StateError("The last active admin cannot be deactivated or demoted")
            self.repository.save_user(updated)
            if not updated.active or password_hash is not None:
                self.repository.delete_user_web_sessions(user.id)
        return updated

    def manage_user(
        self,
        actor: User,
        user_id: UUID,
        *,
        role: Role | None = None,
        active: bool | None = None,
        password: str | None = None,
    ) -> User:
        """`edit_user` for an authenticated admin or manager. Admins may reset their own password,
        but not change their own role or deactivate themselves, which also keeps one admin active.
        Managers may only deactivate and reactivate operators.
        """
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        if actor.role == Role.MANAGER:
            target = self.repository.user_by_id(user_id)
            if target is None:
                raise NotFoundError("User not found")
            if target.role != Role.OPERATOR or role is not None or password is not None:
                raise PermissionDeniedError("Managers can only deactivate or reactivate operators")
        if actor.id == user_id and (role not in (None, actor.role) or active is False):
            raise PermissionDeniedError(
                "Admins cannot change their own role or deactivate themselves"
            )
        return self.edit_user(user_id, role=role, active=active, password=password)

    def remove_user(self, user_id: UUID) -> None:
        """Delete a deactivated account, as the trusted local OS account.

        Only deactivated accounts go, so a deletion is always a second, deliberate step; accounts
        that created or hold tickets stay, deactivated, to keep the history whole.
        """
        with self.repository.transaction():
            user = self.repository.user_by_id(user_id)
            if user is None:
                raise NotFoundError("User not found")
            if user.active:
                raise StateError("Deactivate the user before deleting them")
            tickets = self.repository.list_tickets()
            if any(user.id in (ticket.created_by, ticket.assigned_operator) for ticket in tickets):
                raise StateError("Users with tickets cannot be deleted; they stay deactivated")
            self.repository.delete_user(user.id)

    def delete_user(self, actor: User, user_id: UUID) -> None:
        """`remove_user` for an authenticated admin."""
        self._require(self._actor(actor), _ADMINS)
        self.remove_user(user_id)

    @staticmethod
    def _is_active_admin(user: User) -> bool:
        return user.active and user.role == Role.ADMIN

    def _verified(self, license_key: str, this_machine: str) -> LicensePayload | None:
        """The payload when the key verifies for this machine; a copied key is no key."""
        payload = verify_license_key(license_key, self._license_public_key)
        return payload if payload and payload.machine_id == this_machine else None

    def _stored_license(self) -> LicensePayload | None:
        """The stored key's payload while it verifies, expired or not."""
        record = self.repository.active_license()
        return None if record is None else self._verified(record.license_key, machine_id())

    def license_status(self) -> LicenseStatus:
        """Verified on every read: the database row is a cache with no say over expiry."""
        this_machine = machine_id()
        record = self.repository.active_license()
        if record is None:
            return LicenseStatus(LicenseState.NONE, this_machine)
        payload = self._verified(record.license_key, this_machine)
        if payload is None:
            return LicenseStatus(LicenseState.INVALID, this_machine)
        now = self._now()
        if payload.expires_at <= now:
            return LicenseStatus(
                LicenseState.EXPIRED,
                this_machine,
                licensed_to=payload.licensed_to,
                expires_at=payload.expires_at,
                days_remaining=0,
            )
        return LicenseStatus(
            LicenseState.ACTIVE,
            this_machine,
            type=payload.type,
            licensed_to=payload.licensed_to,
            expires_at=payload.expires_at,
            days_remaining=days_between(now, payload.expires_at),
        )

    def require_license(self) -> None:
        """Refuse unless a license is live; the API and the CLI both gate on this."""
        status = self.license_status()
        if not status.is_valid:
            raise LicenseError(
                403, "license_required", f"A valid license is required ({status.state})"
            )

    def license_request_code(self, actor: User) -> str:
        """A code for the vendor, for any signed-in role: a viewer at the wall can pass it on.

        Always standard: only the vendor decides whether a machine gets a trial.
        """
        self._actor(actor)
        return build_request_code("standard")

    def activate_license(self, actor: User, license_key: str) -> LicenseStatus:
        """Store a vendor key for an admin, after every check; a bad key leaves the old one live."""
        self._require(self._actor(actor), _ADMINS)
        payload = verify_license_key(license_key, self._license_public_key)
        if payload is None:
            raise LicenseError(
                400, "license_bad_signature", "The key is not valid for this product"
            )
        check_machine(payload)
        now = self._now()
        if payload.expires_at <= now:
            raise LicenseError(400, "license_already_expired", "The key has already expired")
        with self.repository.transaction():
            active = self.repository.active_license()
            if active is not None and active.license_key == license_key.strip():
                raise LicenseError(409, "license_already_active", "This key is already active")
            # A trial must never replace a paid license, even one that has expired.
            current = self._stored_license()
            if (
                payload.type == LicenseType.TRIAL
                and current is not None
                and current.type != LicenseType.TRIAL
            ):
                raise LicenseError(
                    409, "license_trial_over_paid", "A trial cannot replace a paid license"
                )
            self.repository.activate_license(
                LicenseRecord(license_key.strip(), now, payload.expires_at, payload.licensed_to)
            )
        return self.license_status()

    def deactivate_license(self, actor: User) -> None:
        """Retire the active key without resetting anything; for swapping licenses by hand."""
        self._require(self._actor(actor), _ADMINS)
        with self.repository.transaction():
            record = self.repository.active_license()
            if record is not None:
                self.repository.deactivate_licenses()

    def require_admin(self, actor: User) -> None:
        self._require(self._actor(actor), _ADMINS)

    def record_mode_switch(self, actor: User, source: str, target: str) -> None:
        """Audit a mode switch in the database switched to, which serves from now on."""
        self._record(self._actor(actor), "mode.switch", detail=f"{self.mode}: {source} -> {target}")

    def recent_events(self, actor: User, limit: int) -> list[AccessEvent]:
        """The newest scans the door readers reported, by time (admin)."""
        self.require_admin(actor)
        events = self.repository.list_events()
        events.sort(key=lambda event: (event.occurred_at, event.sequence), reverse=True)
        return events[:limit]

    def license_history(self, actor: User) -> list[LicenseRecord]:
        self._require(self._actor(actor), _ADMINS)
        return self.repository.list_licenses()

    def _admin_exists(self) -> bool:
        return any(user.role == Role.ADMIN for user in self.repository.list_users())

    def authenticate(self, username: str, password: str) -> User:
        user = self.repository.user_by_name(username)
        if user is None:
            reject_unknown_user(password)
        verify_password(user, password)
        # Checked after the password, so only the account's holder learns it is deactivated.
        if not user.active:
            raise AuthenticationError(DEACTIVATED)
        return user

    def start_session(self, user: User) -> Session:
        expires_at = self._now() + SESSION_LIFETIME
        token = session_token(self.secret_key, user, expires_at)
        return Session(user.username, expires_at, token)

    def resume_session(self, session: Session) -> User:
        user = self.repository.user_by_name(session.username)
        if user is None or not user.active or self._now() >= session.expires_at:
            raise AuthenticationError(INVALID_CREDENTIALS)
        expected = session_token(self.secret_key, user, session.expires_at)
        if not hmac.compare_digest(session.token.encode(), expected.encode()):
            raise AuthenticationError(INVALID_CREDENTIALS)
        return user

    def open_web_session(self, user: User) -> tuple[str, WebSession]:
        """Start a browser session for an authenticated user; return its token and record."""
        user = self._actor(user)
        now = self._now()
        token = new_web_token()
        session = WebSession(
            token_hash=web_token_hash(token),
            user_id=user.id,
            csrf_token=new_web_token(),
            created_at=now,
            last_seen_at=now,
            expires_at=now + WEB_SESSION_LIFETIME,
        )
        with self.repository.transaction():
            # Logins are rare enough to sweep ended sessions on, so no scheduler is needed.
            self.repository.purge_web_sessions(now - WEB_SESSION_IDLE, now)
            self.repository.add_web_session(session)
        return token, session

    def resume_web_session(self, token: str) -> tuple[User, WebSession]:
        """The user and session behind a browser token, while it is neither idle nor ended."""
        # No transaction: each write is one statement, and a logout racing this request at worst
        # lets that one request finish. Most requests then take no write lock at all.
        now = self._now()
        token_hash = web_token_hash(token)
        session = self.repository.get_web_session(token_hash)
        user = None if session is None else self.repository.user_by_id(session.user_id)
        if session is None or user is None or not user.active:
            raise AuthenticationError(SIGNED_OUT)
        if now >= session.expires_at or now >= session.last_seen_at + WEB_SESSION_IDLE:
            self.repository.delete_web_session(token_hash)
            raise AuthenticationError(SIGNED_OUT)
        if now - session.last_seen_at >= WEB_SESSION_TOUCH:
            session = replace(session, last_seen_at=now)
            self.repository.touch_web_session(token_hash, now)
        return user, session

    def close_web_session(self, token: str) -> None:
        self.repository.delete_web_session(web_token_hash(token))

    def _actor(self, actor: User) -> User:
        stored = self.repository.user_by_id(actor.id)
        if stored is None:
            raise PermissionDeniedError("Unknown actor")
        if not stored.active:
            raise PermissionDeniedError(DEACTIVATED)
        return stored

    @staticmethod
    def _require(actor: User, roles: Collection[Role]) -> None:
        if actor.role not in roles:
            raise PermissionDeniedError("This role cannot perform this action")

    @staticmethod
    def _require_view(actor: User, ticket: Ticket) -> None:
        if not _can_view(actor, ticket):
            raise PermissionDeniedError("Ticket is not assigned to this operator")

    @classmethod
    def _require_printable(cls, actor: User, ticket: Ticket) -> Ticket:
        cls._require_view(actor, ticket)
        if ticket.state != TicketState.ISSUED:
            raise InvalidStateError("Only issued tickets can be printed")
        return ticket

    @staticmethod
    def _transition(ticket: Ticket, target: TicketState) -> Ticket:
        if (ticket.state, target) not in _TRANSITIONS:
            raise InvalidStateError(f"Illegal transition: {ticket.state} -> {target}")
        return replace(ticket, state=target)

    def _expire(self, ticket: Ticket) -> Ticket:
        if ticket.state not in _FINAL and self._now() > ticket.valid_until:
            ticket = self._transition(ticket, TicketState.EXPIRED)
            self.repository.save_ticket(ticket)
        return ticket

    def _read_ticket(self, ticket_id: UUID) -> Ticket:
        with self.repository.transaction():
            ticket = self.repository.get_ticket(ticket_id)
            if ticket is None:
                raise NotFoundError("Ticket not found")
            return self._expire(ticket)

    def _expire_all(self) -> list[Ticket]:
        with self.repository.transaction():
            return [self._expire(ticket) for ticket in self.repository.list_tickets()]

    def active_hours(self, actor: User) -> ActiveHours | None:
        """When tickets may be created, or None for any time. Every signed-in role may read them."""
        self._actor(actor)
        return self.repository.active_hours()

    def set_active_hours(
        self, actor: User, start: time | None, end: time | None
    ) -> ActiveHours | None:
        """Limit ticket creation to the local times from `start` to `end`, in the server's zone.
        Both None lifts the limit. Admins and managers.
        """
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        if (start is None) != (end is None):
            raise ValueError("Give both a start and an end, or neither")
        hours = ActiveHours(start, end) if start is not None and end is not None else None
        with self.repository.transaction():
            self.repository.save_active_hours(hours)
            self._record(
                actor,
                "active_hours.set",
                detail="any time" if hours is None else f"{start:%H:%M} to {end:%H:%M}",
            )
        return hours

    def list_ticket_types(self, actor: User) -> list[TicketType]:
        """Every ticket type; operators read them too, to see what a ticket costs."""
        self._actor(actor)
        return self.repository.list_ticket_types()

    def create_ticket_type(
        self, actor: User, name: str, price: int, currency: Currency
    ) -> TicketType:
        """Add a ticket type costing `price` minor units of `currency`. Admins and managers."""
        self._require(self._actor(actor), _STAFF)
        self._require_priced()
        ticket_type = TicketType(uuid4(), _clean_name(name), price, currency)
        with self.repository.transaction():
            if self.repository.ticket_type_by_name(ticket_type.name):
                raise ValueError("A ticket type with this name already exists")
            self.repository.add_ticket_type(ticket_type)
        return ticket_type

    def edit_ticket_type(
        self,
        actor: User,
        type_id: UUID,
        *,
        name: str | None = None,
        price: int | None = None,
        currency: Currency | None = None,
    ) -> TicketType:
        """Rename a ticket type, or change its price or currency. Issued tickets keep theirs."""
        self._require(self._actor(actor), _STAFF)
        self._require_priced()
        if name is None and price is None and currency is None:
            raise ValueError("Nothing to change")
        with self.repository.transaction():
            current = self.repository.get_ticket_type(type_id)
            if current is None:
                raise NotFoundError("Ticket type not found")
            updated = TicketType(
                current.id,
                current.name if name is None else _clean_name(name),
                current.price if price is None else price,
                current.currency if currency is None else currency,
            )
            clash = self.repository.ticket_type_by_name(updated.name)
            if clash is not None and clash.id != current.id:
                raise ValueError("A ticket type with this name already exists")
            self.repository.save_ticket_type(updated)
        return updated

    def delete_ticket_type(self, actor: User, type_id: UUID) -> None:
        """Remove a ticket type. Tickets already issued keep their name and price."""
        self._require(self._actor(actor), _STAFF)
        with self.repository.transaction():
            if self.repository.get_ticket_type(type_id) is None:
                raise NotFoundError("Ticket type not found")
            self.repository.delete_ticket_type(type_id)

    def list_visitor_types(self, actor: User) -> list[VisitorType]:
        """Every visitor type; operators read them too, to pick one when issuing a ticket."""
        self._actor(actor)
        return self.repository.list_visitor_types()

    def create_visitor_type(self, actor: User, name: str, discount_percent: int = 0) -> VisitorType:
        """Add a visitor type whose tickets cost `discount_percent` per cent less."""
        self._require(self._actor(actor), _STAFF)
        if discount_percent:
            self._require_priced()
        visitor_type = VisitorType(uuid4(), _clean_name(name), discount_percent)
        with self.repository.transaction():
            if self.repository.visitor_type_by_name(visitor_type.name):
                raise ValueError("A visitor type with this name already exists")
            self.repository.add_visitor_type(visitor_type)
        return visitor_type

    def edit_visitor_type(
        self,
        actor: User,
        type_id: UUID,
        *,
        name: str | None = None,
        discount_percent: int | None = None,
    ) -> VisitorType:
        """Rename a visitor type or change its discount. Tickets already issued keep theirs."""
        self._require(self._actor(actor), _STAFF)
        if discount_percent:
            self._require_priced()
        if name is None and discount_percent is None:
            raise ValueError("Nothing to change")
        with self.repository.transaction():
            current = self.repository.get_visitor_type(type_id)
            if current is None:
                raise NotFoundError("Visitor type not found")
            updated = VisitorType(
                current.id,
                current.name if name is None else _clean_name(name),
                current.discount_percent if discount_percent is None else discount_percent,
            )
            clash = self.repository.visitor_type_by_name(updated.name)
            if clash is not None and clash.id != current.id:
                raise ValueError("A visitor type with this name already exists")
            self.repository.save_visitor_type(updated)
        return updated

    def delete_visitor_type(self, actor: User, type_id: UUID) -> None:
        """Remove a visitor type. Tickets already issued keep their name and discount."""
        self._require(self._actor(actor), _STAFF)
        with self.repository.transaction():
            if self.repository.get_visitor_type(type_id) is None:
                raise NotFoundError("Visitor type not found")
            self.repository.delete_visitor_type(type_id)

    def _require_priced(self) -> None:
        if self.mode == Mode.BADGE:
            raise ModeError("Badges have no ticket types, prices or discounts")

    def _priced_ticket_type(self, ticket_type: str | None) -> TicketType | None:
        if ticket_type is None:
            return None
        self._require_priced()
        priced = self.repository.ticket_type_by_name(ticket_type.strip())
        if priced is None:
            raise ValueError("Unknown ticket type")
        return priced

    def _admission(
        self, visitor_name: str, usage_type: UsageType, group_size: int
    ) -> tuple[str, UsageType, int]:
        """The name, usage and group size the mode allows, or `ModeError`.

        A badge names its visitor and is always multi-use. A ticket names no one, so a name sent
        is dropped, and admits once, or once per person of a group.
        """
        usage = UsageType(usage_type)
        if self.mode == Mode.BADGE:
            if not visitor_name.strip():
                raise ValueError("Visitor name and type are required")
            if usage != UsageType.MULTI_USE or group_size != 1:
                raise ModeError("Badges are always multi-use, for one person")
            return visitor_name.strip(), usage, 1
        if usage == UsageType.MULTI_USE:
            raise ModeError("Tickets are one-time or for a group")
        if usage == UsageType.GROUP and not MIN_GROUP_SIZE <= group_size <= MAX_GROUP_SIZE:
            raise ValueError(f"A group is from {MIN_GROUP_SIZE} to {MAX_GROUP_SIZE} people")
        if usage == UsageType.ONE_TIME and group_size != 1:
            raise ModeError("Only a group ticket admits more than one person")
        return "", usage, group_size

    def create_ticket(  # noqa: PLR0913 - a ticket's definition is its own arguments
        self,
        actor: User,
        *,
        visitor_name: str = "",
        visitor_type: str,
        valid_from: datetime,
        valid_until: datetime,
        usage_type: UsageType,
        ticket_type: str | None = None,
        external_code: str | None = None,
        event_session: str | None = None,
        group_size: int = 1,
    ) -> Ticket:
        """Issue a ticket, or a badge in badge mode. Naming a catalog `ticket_type` prices it, and
        the `visitor_type` must be one from the catalog; its discount comes off that price, which
        a group pays once per person. See `_admission` for what each mode allows.
        """
        actor = self._actor(actor)
        start, end, now = utc(valid_from), utc(valid_until), self._now()
        if not visitor_type.strip():
            raise ValueError("Visitor name and type are required")
        visitor_name, usage, group_size = self._admission(visitor_name, usage_type, group_size)
        if end < start or end < now:
            raise ValueError("Access window is reversed or already expired")
        if start.microsecond or end.microsecond:
            raise ValueError("Access windows require whole-second precision for BioStar alignment")
        hours = self.repository.active_hours()
        if hours is not None and not hours.allows(now.astimezone(zone(self.timezone)).time()):
            raise OutsideActiveHoursError(
                f"Tickets can only be created from {hours.start:%H:%M} to {hours.end:%H:%M}"
                f" ({self.timezone})"
            )
        code = _clean_code(external_code)
        if code and self.repository.ticket_by_external_code(self.tenant, code):
            raise ExternalCodeTakenError("A ticket with this external code already exists")
        priced = self._priced_ticket_type(ticket_type)
        known = self.repository.visitor_type_by_name(visitor_type.strip())
        if known is None:
            raise ValueError("Unknown visitor type")
        serial = make_serial(
            self.repository.allocate(f"serial:{now:%Y%m%d}"), now.date(), self.prefix
        )
        ticket = Ticket(
            id=uuid4(),
            external_id=None,
            qr_payload=build_payload(serial, self.secret_key, self.prefix),
            readable_serial=serial,
            visitor_name=visitor_name,
            visitor_type=known.name,
            valid_from=start,
            valid_until=end,
            usage_type=usage,
            state=TicketState.ISSUED,
            created_by=actor.id,
            assigned_operator=actor.id,
            created_at=now,
            ticket_type=priced.name if priced else None,
            base_price=priced.price if priced else None,
            # Badges carry no price, so no discount either, whatever the catalog held.
            discount_percent=0 if self.mode == Mode.BADGE else known.discount_percent,
            currency=priced.currency if priced else None,
            external_code=code,
            tenant_id=self.tenant,
            event_session=(event_session or "").strip() or None,
            group_size=group_size,
        )
        external_id = self.registrar.register(ticket)
        if not external_id:
            raise ValueError("Registrar returned an empty external ID")
        try:
            self.registrar.set_window(external_id, start, end)
            ticket = replace(ticket, external_id=external_id)
            with self.repository.transaction():
                ticket = self._expire(ticket)
                self.repository.save_ticket(ticket)
                self._record(actor, "ticket.create", ticket, detail=f"serial={serial}")
        except Exception as exc:
            try:
                self.registrar.remove(external_id)
            except Exception as rollback_error:  # noqa: BLE001 - the original error is re-raised
                exc.add_note(f"Registration rollback also failed: {rollback_error}")
            raise
        return ticket

    def get_ticket(self, actor: User, ticket_id: UUID) -> Ticket:
        actor = self._actor(actor)
        ticket = self._read_ticket(ticket_id)
        self._require_view(actor, ticket)
        return ticket

    def list_tickets(
        self,
        actor: User,
        state: TicketState | None = None,
        search: str | None = None,
        external_code: str | None = None,
    ) -> list[Ticket]:
        actor = self._actor(actor)
        state = TicketState(state) if state is not None else None
        needle = (search or "").strip().casefold()
        code = (external_code or "").strip()
        return [
            ticket
            for ticket in self._expire_all()
            if _can_view(actor, ticket)
            and (state is None or ticket.state == state)
            and (not needle or _matches(ticket, needle))
            and (not code or ticket.external_code == code)
        ]

    def assign_ticket(self, actor: User, ticket_id: UUID, assignee_username: str) -> Ticket:
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        # Read first on its own so a discovered expiry commits even if assignment fails.
        self._read_ticket(ticket_id)
        with self.repository.transaction():
            ticket = self._read_ticket(ticket_id)
            assignee = self.repository.user_by_name(assignee_username)
            if assignee is None:
                raise NotFoundError("Assignee not found")
            if not assignee.active:
                raise StateError("Assignee account is deactivated")
            ticket = replace(ticket, assigned_operator=assignee.id)
            self.repository.save_ticket(ticket)
            return ticket

    def _staff_ticket(self, actor: User, ticket_id: UUID) -> tuple[User, Ticket]:
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        # Read first on its own so a discovered expiry commits even if the change is refused.
        return actor, self._read_ticket(ticket_id)

    def _holder_ticket(self, actor: User, ticket_id: UUID) -> tuple[User, Ticket]:
        """Staff for any ticket; an operator only for a ticket assigned to them."""
        actor = self._actor(actor)
        if actor.role == Role.OPERATOR:
            ticket = self._read_ticket(ticket_id)
            self._require_view(actor, ticket)
            return actor, ticket
        self._require(actor, _STAFF)
        return actor, self._read_ticket(ticket_id)

    def _failed(
        self, actor: User, action: str, ticket_id: UUID, exc: Exception, reason: str | None
    ) -> None:
        """Audit a refused or failed change, outside the rolled-back transaction."""
        ticket = self.repository.get_ticket(ticket_id)
        self._record(actor, f"{action}.failed", ticket, reason=reason, detail=str(exc)[:500])

    def revoke_ticket(self, actor: User, ticket_id: UUID, reason: str | None = None) -> Ticket:
        """Cancel a ticket and remove its access in BioStar. Staff, or its assigned operator.

        Revoking a revoked ticket returns it as it is. An expired ticket cannot be revoked. If
        BioStar refuses, the ticket stays as it was and the error is raised, so a retry is safe.
        """
        actor, _ = self._holder_ticket(actor, ticket_id)
        reason = _clean_reason(reason)
        try:
            with self.repository.transaction():
                ticket = self._read_ticket(ticket_id)
                if ticket.state == TicketState.REVOKED:
                    return ticket
                ticket = self._transition(ticket, TicketState.REVOKED)
                if ticket.external_id:
                    self.registrar.deactivate(ticket.external_id)
                self.repository.save_ticket(ticket)
                self._record(actor, "ticket.revoke", ticket, reason=reason)
                return ticket
        except Exception as exc:
            self._failed(actor, "ticket.revoke", ticket_id, exc, reason)
            raise

    def _amend(
        self,
        actor: User,
        ticket_id: UUID,
        action: str,
        *,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        event_session: str | _Unset | None = _UNSET,
        holder: bool = False,
    ) -> Ticket:
        resolve = self._holder_ticket if holder else self._staff_ticket
        actor, _ = resolve(actor, ticket_id)
        try:
            return self._amend_stored(
                actor, ticket_id, action, valid_from, valid_until, event_session
            )
        except Exception as exc:
            self._failed(actor, action, ticket_id, exc, None)
            raise

    def _amend_stored(
        self,
        actor: User,
        ticket_id: UUID,
        action: str,
        valid_from: datetime | None,
        valid_until: datetime | None,
        event_session: str | _Unset | None,
    ) -> Ticket:
        with self.repository.transaction():
            ticket = self._read_ticket(ticket_id)
            # Passed and still admitting: multi-use, or a group with people still to come.
            usable = ticket.state == TicketState.ISSUED or (
                ticket.state == TicketState.PASSED and not ticket.is_spent
            )
            if not usable:
                raise InvalidStateError(f"A {ticket.state} ticket cannot be changed")
            start = ticket.valid_from if valid_from is None else utc(valid_from)
            end = ticket.valid_until if valid_until is None else utc(valid_until)
            if end <= start:
                raise ValueError("The end of the validity window must be after its start")
            if start.microsecond or end.microsecond:
                raise ValueError(
                    "Access windows require whole-second precision for BioStar alignment"
                )
            if end < self._now():
                raise ValueError("Access window is reversed or already expired")
            session = (
                ticket.event_session
                if isinstance(event_session, _Unset)
                else ((event_session or "").strip() or None)
            )
            updated = replace(ticket, valid_from=start, valid_until=end, event_session=session)
            if updated == ticket:
                return ticket
            window_changed = (start, end) != (ticket.valid_from, ticket.valid_until)
            if window_changed and ticket.external_id:
                self.registrar.set_window(ticket.external_id, start, end)
            try:
                self.repository.save_ticket(updated)
                self._record(
                    actor,
                    action,
                    updated,
                    detail=(
                        f"valid_from {ticket.valid_from.isoformat()} -> {start.isoformat()}; "
                        f"valid_until {ticket.valid_until.isoformat()} -> {end.isoformat()}; "
                        f"event_session {ticket.event_session!r} -> {session!r}"
                    ),
                )
            except Exception as exc:
                if window_changed and ticket.external_id:
                    # Put BioStar back, so it never grants a window the database does not hold.
                    try:
                        self.registrar.set_window(
                            ticket.external_id, ticket.valid_from, ticket.valid_until
                        )
                    except Exception as rollback_error:  # noqa: BLE001 - the original is re-raised
                        exc.add_note(f"BioStar window rollback also failed: {rollback_error}")
                raise
            return updated

    def update_validity(
        self,
        actor: User,
        ticket_id: UUID,
        *,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> Ticket:
        """Move a ticket's validity window, in BioStar too. Staff, or its assigned operator.

        Allowed while the ticket is issued, or passed and multi-use. Either end may be left as
        it is; the end must be after the start.
        """
        if valid_from is None and valid_until is None:
            raise ValueError("Nothing to change")
        return self._amend(
            actor,
            ticket_id,
            "ticket.update_validity",
            valid_from=valid_from,
            valid_until=valid_until,
            holder=True,
        )

    def transfer_ticket(
        self,
        actor: User,
        ticket_id: UUID,
        event_session: str,
        *,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> Ticket:
        """Move a ticket to another session or event, keeping its state, id and audit history.

        The window may move with it; BioStar follows through `update_validity`'s steps.
        """
        if not (event_session or "").strip():
            raise ValueError("A target session is required")
        return self._amend(
            actor,
            ticket_id,
            "ticket.transfer",
            valid_from=valid_from,
            valid_until=valid_until,
            event_session=event_session,
        )

    def reissue_ticket(
        self,
        actor: User,
        ticket_id: UUID,
        *,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        group_size: int | None = None,
    ) -> Ticket:
        """Reissue a ticket in any state, as the same ticket; this is also how it is edited.

        The ticket keeps its id, serial and QR code and returns to issued. The new window must
        end in the future; BioStar is told of it and the account is enabled again. If BioStar
        refuses, the ticket stays as it was. Staff, or the operator it is assigned to.

        A ticket (not a badge) may change how many people it admits until its current window
        ends: one makes it one-time, more a group. Its price follows, per person as issued.
        """
        actor, old = self._holder_ticket(actor, ticket_id)
        try:
            return self._reissue_stored(actor, old.id, valid_from, valid_until, group_size)
        except Exception as exc:
            self._failed(actor, "ticket.reissue", ticket_id, exc, None)
            raise

    def _reissue_stored(
        self,
        actor: User,
        ticket_id: UUID,
        valid_from: datetime | None,
        valid_until: datetime | None,
        group_size: int | None,
    ) -> Ticket:
        with self.repository.transaction():
            ticket = self._read_ticket(ticket_id)
            usage, size = self._regroup(ticket, group_size)
            start = ticket.valid_from if valid_from is None else utc(valid_from)
            end = ticket.valid_until if valid_until is None else utc(valid_until)
            if end <= start:
                raise ValueError("The end of the validity window must be after its start")
            if start.microsecond or end.microsecond:
                raise ValueError(
                    "Access windows require whole-second precision for BioStar alignment"
                )
            if end < self._now():
                raise ValueError("Access window is reversed or already expired")
            updated = replace(
                ticket,
                state=TicketState.ISSUED,
                valid_from=start,
                valid_until=end,
                usage_type=usage,
                group_size=size,
            )
            detail = (
                f"state {ticket.state} -> {updated.state}; "
                f"valid_from {ticket.valid_from.isoformat()} -> {start.isoformat()}; "
                f"valid_until {ticket.valid_until.isoformat()} -> {end.isoformat()}"
            )
            if size != ticket.group_size:
                detail += f"; group_size {ticket.group_size} -> {size}"
                if ticket.price is not None:
                    detail += f"; price {ticket.price} -> {updated.price}"
            if ticket.external_id:
                self.registrar.set_window(ticket.external_id, start, end)
                self.registrar.activate(ticket.external_id)
            try:
                self.repository.save_ticket(updated)
                self._record(actor, "ticket.reissue", updated, detail=detail)
            except Exception as exc:
                if ticket.external_id:
                    try:
                        self.registrar.deactivate(ticket.external_id)
                        self.registrar.set_window(
                            ticket.external_id, ticket.valid_from, ticket.valid_until
                        )
                    except Exception as rollback_error:  # noqa: BLE001 - the original is re-raised
                        exc.add_note(f"BioStar reissue rollback also failed: {rollback_error}")
                raise
            return updated

    def _regroup(self, ticket: Ticket, group_size: int | None) -> tuple[UsageType, int]:
        """The usage and size a reissue leaves `ticket` with, or why its size cannot change."""
        if group_size is None or group_size == ticket.group_size:
            return ticket.usage_type, ticket.group_size
        if self.mode == Mode.BADGE:
            raise ModeError("Badges are always multi-use, for one person")
        if ticket.valid_until < self._now():
            raise StateError("The ticket's window has ended, so its visitors can no longer change")
        if not 1 <= group_size <= MAX_GROUP_SIZE:
            raise ValueError(f"A ticket admits from 1 to {MAX_GROUP_SIZE} people")
        return (UsageType.ONE_TIME if group_size == 1 else UsageType.GROUP), group_size

    def idempotency_lookup(self, key: str, fingerprint: str) -> StoredResponse | None:
        """The saved answer for `key` if one is live; a different payload under it is a conflict."""
        stored = self.repository.get_stored_response(self.tenant, key, self._now())
        if stored is None:
            return None
        if not hmac.compare_digest(stored.fingerprint, fingerprint):
            raise IdempotencyConflictError("This Idempotency-Key was used with a different request")
        return stored

    def idempotency_store(
        self, key: str, fingerprint: str, status: int, body: str, ttl: timedelta
    ) -> None:
        now = self._now()
        self.repository.purge_stored_responses(now)
        self.repository.save_stored_response(
            StoredResponse(key, self.tenant, fingerprint, status, body, now, now + ttl)
        )

    def _key_admin(self, actor: User) -> User:
        actor = self._actor(actor)
        self._require(actor, _ADMINS)
        return actor

    def create_api_key(
        self,
        actor: User,
        name: str,
        scopes: Collection[str],
        *,
        acts_as: str | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[ApiKey, str]:
        """Issue a service key (admin). The secret is returned once and only its hash is kept.

        The key acts as the account `acts_as` (default: the admin), with that role's limits and
        only the listed scopes.
        """
        actor = self._key_admin(actor)
        unknown = set(scopes) - SCOPES
        if unknown or not scopes:
            raise ValueError(f"Scopes must be one or more of: {', '.join(sorted(SCOPES))}")
        owner = actor if acts_as is None else self.find_user(acts_as)
        if not owner.active:
            raise StateError("The account is deactivated")
        now = self._now()
        if expires_at is not None and utc(expires_at) <= now:
            raise ValueError("The key would already be expired")
        secret = KEY_PREFIX + secrets.token_urlsafe(32)
        key = ApiKey(
            uuid4(),
            _clean_name(name),
            key_hash(secret),
            owner.id,
            tuple(sorted(set(scopes))),
            now,
            utc(expires_at) if expires_at else None,
        )
        with self.repository.transaction():
            self.repository.save_api_key(key)
            self._record(
                actor, "api_key.create", detail=f"key={key.id} scopes={' '.join(key.scopes)}"
            )
        return key, secret

    def list_api_keys(self, actor: User) -> list[ApiKey]:
        self._key_admin(actor)
        return self.repository.list_api_keys()

    def _stored_key(self, key_id: UUID) -> ApiKey:
        key = self.repository.get_api_key(key_id)
        if key is None:
            raise NotFoundError("API key not found")
        return key

    def revoke_api_key(self, actor: User, key_id: UUID) -> ApiKey:
        """End a key now; revoking a revoked key changes nothing."""
        actor = self._key_admin(actor)
        with self.repository.transaction():
            key = self._stored_key(key_id)
            if key.revoked_at is not None:
                return key
            key = replace(key, revoked_at=self._now())
            self.repository.save_api_key(key)
            self._record(actor, "api_key.revoke", detail=f"key={key.id}")
            return key

    def rotate_api_key(
        self, actor: User, key_id: UUID, grace: timedelta = timedelta(0)
    ) -> tuple[ApiKey, str]:
        """Issue a successor with the same name, account and scopes. The old key keeps working
        for `grace` (none by default), so clients can switch over, and is then expired.
        """
        actor = self._key_admin(actor)
        if grace < timedelta(0):
            raise ValueError("The grace period must not be negative")
        with self.repository.transaction():
            old = self._stored_key(key_id)
            now = self._now()
            if old.revoked_at is not None or (old.expires_at and old.expires_at <= now):
                raise StateError("Only a live key can be rotated")
            if old.replaced_by is not None:
                raise StateError("This key was already rotated")
            secret = KEY_PREFIX + secrets.token_urlsafe(32)
            new = ApiKey(
                uuid4(), old.name, key_hash(secret), old.user_id, old.scopes, now, old.expires_at
            )
            end = now + grace
            expires = end if old.expires_at is None else min(end, old.expires_at)
            self.repository.save_api_key(new)
            self.repository.save_api_key(replace(old, expires_at=expires, replaced_by=new.id))
            self._record(actor, "api_key.rotate", detail=f"key={old.id} -> {new.id}")
            return new, secret

    def authenticate_api_key(self, secret: str) -> tuple[User, ApiKey]:
        """The account and key behind a presented secret, or `AuthenticationError`."""
        key = self.repository.api_key_by_hash(key_hash(secret)) if secret else None
        now = self._now()
        if key is None or key.revoked_at is not None or (key.expires_at and key.expires_at <= now):
            raise AuthenticationError(INVALID_CREDENTIALS)
        user = self.repository.user_by_id(key.user_id)
        if user is None or not user.active:
            raise AuthenticationError(INVALID_CREDENTIALS)
        return user, key

    def print_ticket(
        self,
        actor: User,
        ticket_id: UUID,
        output_dir: Path,
        timezone: str = "UTC",
        renderer: PdfRenderer | None = None,
    ) -> Path:
        actor = self._actor(actor)
        # Checked first on its own so a refusal still commits a discovered expiry.
        self._require_printable(actor, self._read_ticket(ticket_id))
        if renderer is None:
            from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

            renderer = partial(render_pdf, mode=self.mode)
        with self.repository.transaction():
            ticket = self._require_printable(actor, self._read_ticket(ticket_id))
            path = renderer(ticket, output_dir, timezone)
            self.repository.save_ticket(replace(ticket, print_count=ticket.print_count + 1))
            return path

    @staticmethod
    def _outcome(raw: RawEvent, ticket: Ticket | None) -> Outcome:
        if not raw.granted:
            return Outcome.DENIED
        if ticket is None:
            return Outcome.IGNORED_UNKNOWN_TICKET
        if ticket.state in _FINAL:
            return Outcome.IGNORED_EXPIRED
        if ticket.is_spent:
            return Outcome.IGNORED_SECOND_ONE_TIME_SCAN
        if not ticket.valid_from <= raw.occurred_at <= ticket.valid_until:
            return Outcome.IGNORED_OUTSIDE_WINDOW
        return Outcome.APPLIED

    def _record_use(self, ticket: Ticket, occurred_at: datetime) -> Ticket:
        if ticket.state == TicketState.ISSUED:
            ticket = replace(self._transition(ticket, TicketState.PASSED), passed_at=occurred_at)
        ticket = replace(ticket, use_count=ticket.use_count + 1)
        # The pass that spends a one-time or group ticket also shuts it in BioStar, before saving.
        if ticket.is_spent and ticket.external_id is not None:
            self.registrar.deactivate(ticket.external_id)
        self.repository.save_ticket(ticket)
        return ticket

    def _apply_event(self, raw: RawEvent) -> AccessEvent:
        ticket = self.repository.ticket_by_external_id(raw.external_id) if raw.external_id else None
        if ticket is not None:
            ticket = self._expire(ticket)
        outcome = self._outcome(raw, ticket)
        if outcome == Outcome.APPLIED and ticket is not None:
            ticket = self._record_use(ticket, raw.occurred_at)
        return AccessEvent(
            event_id=raw.event_id,
            ticket_id=ticket.id if ticket else None,
            occurred_at=raw.occurred_at,
            granted=raw.granted,
            outcome=outcome,
            processed_at=self._now(),
            point_id=raw.point_id,
            point_name=raw.point_name,
            direction=raw.direction,
        )

    def sync(self, actor: User) -> int:
        self._require(self._actor(actor), _STAFF)
        return self.scheduled_sync()

    def scheduled_sync(self) -> int:
        """`sync` for a trusted in-process scheduler, which has no account to act as."""
        self._expire_all()
        events, cursor = self.event_source.fetch_events(self.repository.get_cursor())
        stored: list[AccessEvent] = []
        with self.repository.transaction():
            for raw in sorted(events, key=lambda event: (event.occurred_at, event.event_id)):
                if self.repository.get_event(raw.event_id) is not None:
                    continue
                event = self._apply_event(raw)
                self.repository.add_event(event)
                stored.append(event)
            self.repository.save_cursor(cursor)
        # Announced only once committed, so a rolled-back run tells no one about its passages.
        for event in stored:
            if self.on_passage is not None:
                self.on_passage(event)
        return len(stored)

    def passages(
        self, actor: User, after: int, limit: int, *, scoped_key: bool = False
    ) -> list[AccessEvent]:
        """Passages in arrival order after `after`, which is the sequence of the last one read.

        Staff, or a service key holding `passes:read`, whatever account it acts as.
        """
        actor = self._actor(actor)
        if not scoped_key:
            self._require(actor, _STAFF)
        if after < 0:
            raise ValueError("The cursor must not be negative")
        if not 1 <= limit <= _MAX_PASSAGES:
            raise ValueError(f"A page holds from 1 to {_MAX_PASSAGES} passages")
        return self.repository.list_passages(after, limit)

    def passage_ticket(self, ticket_id: UUID) -> Ticket | None:
        """The ticket a passage belongs to. Feed readers are already gated by `passages`."""
        return self.repository.get_ticket(ticket_id)

    def cleanup(self, actor: User) -> int:
        self._require(self._actor(actor), _STAFF)
        return self.scheduled_cleanup()

    def scheduled_cleanup(self) -> int:
        """`cleanup` for a trusted in-process scheduler, which has no account to act as."""
        removed = 0
        # States only move forward, so a ticket eligible in this snapshot stays eligible.
        for ticket in self._expire_all():
            eligible = ticket.state in _FINAL or ticket.is_spent
            if eligible and ticket.external_id and not self.repository.is_cleaned(ticket.id):
                self.registrar.remove(ticket.external_id)
                self.repository.mark_cleaned(ticket.id)
                removed += 1
        return removed

    def stats(
        self,
        actor: User,
        since: date | None = None,
        until: date | None = None,
        timezone: str = "UTC",
    ) -> Stats:
        """Figures for the tickets created from `since` through `until`, local days in `timezone`.

        Either end may be left open; with neither, every ticket counts.
        """
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        if since is not None and until is not None and until < since:
            raise ValueError("The end date must not be before the start date")
        tickets = self._expire_all()
        if since is not None:
            start = day_start(since, timezone)
            tickets = [ticket for ticket in tickets if ticket.created_at >= start]
        if until is not None:
            end = day_start(until + timedelta(days=1), timezone)
            tickets = [ticket for ticket in tickets if ticket.created_at < end]
        by_visitor: dict[str, list[Ticket]] = {}
        for ticket in tickets:
            by_visitor.setdefault(ticket.visitor_type, []).append(ticket)
        return Stats(
            **_counts(tickets),
            visitor_types={
                name: VisitorStats(**_counts(group), ticket_types=_by_ticket_type(group))
                for name, group in sorted(by_visitor.items())
            },
            ticket_types=_by_ticket_type(tickets),
        )


class ModeSwitch:
    """The service's database for each mode; switching moves the service onto the other one.

    Each database opened stays open until `close`, so a request still running on the one left
    behind finishes there. A switch first copies the shared accounts, sessions, keys, license,
    hours and counters into the target (see `SQLiteRepository.mirror_shared`), so whoever is
    signed in stays signed in.
    """

    def __init__(
        self, paths: Mapping[Mode, Path], save: Callable[[Mode], object] | None = None
    ) -> None:
        self.paths = {Mode(mode): Path(path) for mode, path in paths.items()}
        self.save = save
        self.service: TicketService | None = None
        self._repositories: dict[Mode, SQLiteRepository] = {}
        self._lock = threading.Lock()

    def open(self, mode: Mode) -> SQLiteRepository:
        """The mode's database, created and migrated when new; refused when out of date."""
        mode = Mode(mode)
        repository = self._repositories.get(mode)
        if repository is None:
            repository = SQLiteRepository(self.paths[mode])
            try:
                repository.initialize()
            except Exception:
                repository.close()
                raise
            self._repositories[mode] = repository
        return repository

    def switch(self, actor: User, mode: Mode) -> Mode:
        """Make `mode` the service's, for an admin; saving it so the next start keeps it."""
        service = self.service
        if service is None:
            raise RuntimeError("The switch is not bound to a service")
        service.require_admin(actor)
        mode = Mode(mode)
        with self._lock:
            if mode == service.mode:
                return mode
            source = service.repository
            if not isinstance(source, SQLiteRepository):
                raise TypeError("Only a SQLite database can be switched")
            target = self.open(mode)
            target.mirror_shared(source)
            if self.save is not None:
                self.save(mode)
            service.repository = target
            # The BioStar adapters keep registrations and the sync cursor in the same database.
            for adapter in (service.registrar, service.event_source):
                if isinstance(adapter, BioStarXRegistrar | BioStarXEventSource):
                    adapter.repository = target
            service.mode = mode
            service.record_mode_switch(actor, source.path, target.path)
        return mode

    def close(self) -> None:
        for repository in self._repositories.values():
            repository.close()
        self._repositories.clear()


class BioStarLink:
    """The service's BioStar connection, which can be replaced while the service runs."""

    def __init__(
        self, settings: BioStarSettings | None = None, client: BioStarClient | None = None
    ) -> None:
        self.settings = settings
        self.client = client
        self.service: TicketService | None = None

    def connect(self, settings: BioStarSettings | None) -> None:
        """Point the service at `settings`, or at the in-memory fakes when None."""
        if self.service is None:
            raise RuntimeError("The link is not bound to a service")
        previous = self.client
        if settings is None:
            self.client = None
            self.service.registrar = InMemoryRegistrar()
            self.service.event_source = InMemoryEventSource()
        else:
            self.client = BioStarClient(settings)
            self.service.registrar = BioStarXRegistrar(self.client, self.service.repository)
            self.service.event_source = BioStarXEventSource(self.client, self.service.repository)
        self.settings = settings
        if previous is not None:
            previous.close()

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
