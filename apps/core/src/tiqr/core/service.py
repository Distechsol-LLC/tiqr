import hmac
from collections import Counter
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
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
from tiqr.core.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.core.models import (
    AccessEvent,
    Outcome,
    RawEvent,
    Role,
    Ticket,
    TicketState,
    UsageType,
    User,
    WebSession,
    utc,
)
from tiqr.core.ports import Clock, EventSource, PdfRenderer, Registrar, Repository
from tiqr.core.qr import DEFAULT_PREFIX, build_payload, make_serial, validate_prefix
from tiqr.core.settings import validate_secret

_ADMINS = frozenset({Role.ADMIN})
_STAFF = frozenset({Role.ADMIN, Role.MANAGER})
_MANAGERS = frozenset({Role.MANAGER})
_TRANSITIONS = frozenset(
    {
        (TicketState.ISSUED, TicketState.PASSED),
        (TicketState.ISSUED, TicketState.EXPIRED),
        (TicketState.PASSED, TicketState.EXPIRED),
    }
)


def _can_view(actor: User, ticket: Ticket) -> bool:
    return actor.role != Role.OPERATOR or ticket.assigned_operator == actor.id


class PermissionDeniedError(PermissionError):
    pass


class StateError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


class Stats(TypedDict):
    total: int
    issued: int
    passed: int
    expired: int
    uses: int
    prints: int


class TicketService:
    def __init__(
        self,
        repository: Repository,
        secret_key: str,
        registrar: Registrar | None = None,
        event_source: EventSource | None = None,
        *,
        clock: Clock | None = None,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        validate_secret(secret_key)
        validate_prefix(prefix)
        self.repository = repository
        self.secret_key = secret_key
        self.prefix = prefix
        self.registrar: Registrar = registrar or InMemoryRegistrar()
        self.event_source: EventSource = event_source or InMemoryEventSource()
        self._clock: Clock = clock or partial(datetime.now, UTC)

    def _now(self) -> datetime:
        return utc(self._clock())

    def add_user(self, username: str, password: str, role: Role) -> User:
        user = new_user(username, password, role)
        with self.repository.transaction():
            if self.repository.user_by_name(user.username):
                raise ValueError("Username already exists")
            self.repository.add_user(user)
        return user

    def list_users(self) -> list[User]:
        return self.repository.list_users()

    def create_user(self, actor: User, username: str, password: str, role: Role) -> User:
        """`add_user` for an authenticated caller rather than the trusted local OS account."""
        self._require(self._actor(actor), _ADMINS)
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
        somebody can always manage accounts.
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
        """`edit_user` for an authenticated admin. Admins may reset their own password, but
        not change their own role or deactivate themselves, which also keeps one admin active.
        """
        actor = self._actor(actor)
        self._require(actor, _ADMINS)
        if actor.id == user_id and (role not in (None, actor.role) or active is False):
            raise PermissionDeniedError(
                "Admins cannot change their own role or deactivate themselves"
            )
        return self.edit_user(user_id, role=role, active=active, password=password)

    @staticmethod
    def _is_active_admin(user: User) -> bool:
        return user.active and user.role == Role.ADMIN

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
            raise StateError("Only issued tickets can be printed")
        return ticket

    @staticmethod
    def _transition(ticket: Ticket, target: TicketState) -> Ticket:
        if (ticket.state, target) not in _TRANSITIONS:
            raise StateError(f"Illegal transition: {ticket.state} -> {target}")
        return replace(ticket, state=target)

    def _expire(self, ticket: Ticket) -> Ticket:
        if ticket.state != TicketState.EXPIRED and self._now() > ticket.valid_until:
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

    def create_ticket(
        self,
        actor: User,
        *,
        visitor_name: str,
        visitor_type: str,
        valid_from: datetime,
        valid_until: datetime,
        usage_type: UsageType,
    ) -> Ticket:
        actor = self._actor(actor)
        start, end, now = utc(valid_from), utc(valid_until), self._now()
        if not visitor_name.strip() or not visitor_type.strip():
            raise ValueError("Visitor name and type are required")
        if end < start or end < now:
            raise ValueError("Access window is reversed or already expired")
        if start.microsecond or end.microsecond:
            raise ValueError("Access windows require whole-second precision for BioStar alignment")
        serial = make_serial(
            self.repository.allocate(f"serial:{now:%Y%m%d}"), now.date(), self.prefix
        )
        ticket = Ticket(
            id=uuid4(),
            external_id=None,
            qr_payload=build_payload(serial, self.secret_key, self.prefix),
            readable_serial=serial,
            visitor_name=visitor_name.strip(),
            visitor_type=visitor_type.strip(),
            valid_from=start,
            valid_until=end,
            usage_type=UsageType(usage_type),
            state=TicketState.ISSUED,
            created_by=actor.id,
            assigned_operator=actor.id,
            created_at=now,
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

    def list_tickets(self, actor: User, state: TicketState | None = None) -> list[Ticket]:
        actor = self._actor(actor)
        state = TicketState(state) if state is not None else None
        return [
            ticket
            for ticket in self._expire_all()
            if _can_view(actor, ticket) and (state is None or ticket.state == state)
        ]

    def assign_ticket(self, actor: User, ticket_id: UUID, assignee_username: str) -> Ticket:
        actor = self._actor(actor)
        self._require(actor, _MANAGERS)
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

            renderer = render_pdf
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
        if ticket.state == TicketState.EXPIRED:
            return Outcome.IGNORED_EXPIRED
        if ticket.is_spent:
            return Outcome.IGNORED_SECOND_ONE_TIME_SCAN
        if not ticket.valid_from <= raw.occurred_at <= ticket.valid_until:
            return Outcome.IGNORED_OUTSIDE_WINDOW
        return Outcome.APPLIED

    def _record_use(self, ticket: Ticket, occurred_at: datetime) -> Ticket:
        if ticket.state == TicketState.ISSUED:
            if ticket.usage_type == UsageType.ONE_TIME and ticket.external_id is not None:
                self.registrar.deactivate(ticket.external_id)
            ticket = replace(self._transition(ticket, TicketState.PASSED), passed_at=occurred_at)
        ticket = replace(ticket, use_count=ticket.use_count + 1)
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
        )

    def sync(self, actor: User) -> int:
        self._require(self._actor(actor), _STAFF)
        return self.scheduled_sync()

    def scheduled_sync(self) -> int:
        """`sync` for a trusted in-process scheduler, which has no account to act as."""
        self._expire_all()
        events, cursor = self.event_source.fetch_events(self.repository.get_cursor())
        stored = 0
        with self.repository.transaction():
            for raw in sorted(events, key=lambda event: (event.occurred_at, event.event_id)):
                if self.repository.get_event(raw.event_id) is not None:
                    continue
                self.repository.add_event(self._apply_event(raw))
                stored += 1
            self.repository.save_cursor(cursor)
        return stored

    def cleanup(self, actor: User) -> int:
        self._require(self._actor(actor), _STAFF)
        return self.scheduled_cleanup()

    def scheduled_cleanup(self) -> int:
        """`cleanup` for a trusted in-process scheduler, which has no account to act as."""
        removed = 0
        # States only move forward, so a ticket eligible in this snapshot stays eligible.
        for ticket in self._expire_all():
            eligible = ticket.state == TicketState.EXPIRED or ticket.is_spent
            if eligible and ticket.external_id and not self.repository.is_cleaned(ticket.id):
                self.registrar.remove(ticket.external_id)
                self.repository.mark_cleaned(ticket.id)
                removed += 1
        return removed

    def stats(self, actor: User) -> Stats:
        actor = self._actor(actor)
        self._require(actor, _STAFF)
        tickets = self._expire_all()
        states = Counter(ticket.state for ticket in tickets)
        return Stats(
            total=len(tickets),
            issued=states[TicketState.ISSUED],
            passed=states[TicketState.PASSED],
            expired=states[TicketState.EXPIRED],
            uses=sum(ticket.use_count for ticket in tickets),
            prints=sum(ticket.print_count for ticket in tickets),
        )
