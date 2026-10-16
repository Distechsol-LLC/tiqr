import hmac
from collections import Counter
from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TypedDict
from uuid import UUID, uuid4

from tiqr.auth import (
    INVALID_CREDENTIALS,
    SESSION_LIFETIME,
    AuthenticationError,
    Session,
    new_user,
    session_token,
    verify_password,
)
from tiqr.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.models import (
    AccessEvent,
    Outcome,
    RawEvent,
    Role,
    Ticket,
    TicketState,
    UsageType,
    User,
    utc,
)
from tiqr.ports import Clock, EventSource, PdfRenderer, Registrar, Repository
from tiqr.qr import DEFAULT_PREFIX, build_payload, make_serial, validate_prefix
from tiqr.settings import validate_secret

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

    def authenticate(self, username: str, password: str) -> User:
        user = self.repository.user_by_name(username)
        if user is None:
            raise AuthenticationError(INVALID_CREDENTIALS)
        verify_password(user, password)
        return user

    def start_session(self, user: User) -> Session:
        expires_at = self._now() + SESSION_LIFETIME
        token = session_token(self.secret_key, user.id, expires_at)
        return Session(user.username, expires_at, token)

    def resume_session(self, session: Session) -> User:
        user = self.repository.user_by_name(session.username)
        if user is None or self._now() >= session.expires_at:
            raise AuthenticationError(INVALID_CREDENTIALS)
        expected = session_token(self.secret_key, user.id, session.expires_at)
        if not hmac.compare_digest(session.token.encode(), expected.encode()):
            raise AuthenticationError(INVALID_CREDENTIALS)
        return user

    def _actor(self, actor: User) -> User:
        stored = self.repository.user_by_id(actor.id)
        if stored is None:
            raise PermissionDeniedError("Unknown actor")
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
            from tiqr.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

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
        actor = self._actor(actor)
        self._require(actor, _STAFF)
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
        actor = self._actor(actor)
        self._require(actor, _STAFF)
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
