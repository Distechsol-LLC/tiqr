import sqlite3
import threading
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

from tiqr.core.models import (
    AccessEvent,
    Currency,
    Outcome,
    Registration,
    Role,
    SyncCursor,
    Ticket,
    TicketState,
    TicketType,
    UsageType,
    User,
    VisitorType,
    WebSession,
    utc,
)
from tiqr.core.ports import Repository

type _Value = str | int | None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin','manager','operator'))
);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, external_id TEXT UNIQUE, qr_payload TEXT NOT NULL UNIQUE,
    readable_serial TEXT NOT NULL UNIQUE, visitor_name TEXT NOT NULL, visitor_type TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_until TEXT NOT NULL,
    usage_type TEXT NOT NULL CHECK(usage_type IN ('one_time','multi_use')),
    state TEXT NOT NULL CHECK(state IN ('issued','passed','expired')),
    created_by TEXT NOT NULL REFERENCES users(id),
    assigned_operator TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL, passed_at TEXT,
    print_count INTEGER NOT NULL CHECK(print_count >= 0),
    use_count INTEGER NOT NULL CHECK(use_count >= 0)
);
CREATE TABLE IF NOT EXISTS access_events (
    event_id TEXT PRIMARY KEY, ticket_id TEXT REFERENCES tickets(id), occurred_at TEXT NOT NULL,
    granted INTEGER NOT NULL CHECK(granted IN (0,1)),
    outcome TEXT NOT NULL, processed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_cursor (id INTEGER PRIMARY KEY CHECK(id=1), token TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sequences (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS registrations (
    external_id TEXT PRIMARY KEY, card_id TEXT NOT NULL,
    user_removed INTEGER NOT NULL, card_removed INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cleaned_tickets (ticket_id TEXT PRIMARY KEY REFERENCES tickets(id));
"""
# Timestamps are fixed-width, so SQL compares them as text in time order.
_WEB_SESSIONS = """
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS web_sessions_user ON web_sessions(user_id);
"""
_USER_ACTIVE = """
ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1));
"""
# Names are unique whatever their case, so "Guest" and "guest" cannot both exist. A ticket keeps
# the name, price and discount it was made with, so nothing here references it.
_CATALOG = """
CREATE TABLE IF NOT EXISTS ticket_types (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    price INTEGER NOT NULL CHECK(price >= 0)
);
CREATE TABLE IF NOT EXISTS visitor_types (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    discount_percent INTEGER NOT NULL CHECK(discount_percent BETWEEN 0 AND 100)
);
ALTER TABLE tickets ADD COLUMN ticket_type TEXT;
ALTER TABLE tickets ADD COLUMN base_price INTEGER CHECK(base_price >= 0);
ALTER TABLE tickets ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0
    CHECK(discount_percent BETWEEN 0 AND 100);
"""
# Prices made before currencies existed were all in US dollars, so they are backfilled as such.
_CURRENCY = """
ALTER TABLE ticket_types ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'
    CHECK(currency IN ('USD','RUB','AZN'));
ALTER TABLE tickets ADD COLUMN currency TEXT CHECK(currency IN ('USD','RUB','AZN'));
UPDATE tickets SET currency='USD' WHERE base_price IS NOT NULL;
"""


def _statements(script: str) -> tuple[str, ...]:
    # No statement here contains a semicolon of its own, so splitting on them is exact.
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


# Step N upgrades schema version N to N + 1. Steps are append-only, and each runs once, in one
# transaction with its version bump.
_MIGRATIONS = tuple(
    _statements(script) for script in (_SCHEMA, _WEB_SESSIONS, _USER_ACTIVE, _CATALOG, _CURRENCY)
)
SCHEMA_VERSION = len(_MIGRATIONS)

_TICKET_COLUMNS = tuple(field.name for field in fields(Ticket))
_UPSERT_TICKET = (
    f"INSERT INTO tickets ({','.join(_TICKET_COLUMNS)}) "  # noqa: S608 - column names come from the dataclass, not input
    f"VALUES ({','.join(f':{column}' for column in _TICKET_COLUMNS)}) "
    "ON CONFLICT(id) DO UPDATE SET "
    + ",".join(f"{column}=excluded.{column}" for column in _TICKET_COLUMNS if column != "id")
)


def _to_sql(value: object) -> _Value:
    match value:
        case datetime():
            return value.isoformat()
        case UUID():
            return str(value)
        case str() | int() | None:
            return value
        case _:
            raise TypeError(f"Cannot store {type(value).__name__} in SQLite")


def _optional_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _user(row: sqlite3.Row) -> User:
    return User(
        UUID(row["id"]),
        row["username"],
        row["password_hash"],
        Role(row["role"]),
        active=bool(row["active"]),
    )


def _ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(
        id=UUID(row["id"]),
        external_id=row["external_id"],
        qr_payload=row["qr_payload"],
        readable_serial=row["readable_serial"],
        visitor_name=row["visitor_name"],
        visitor_type=row["visitor_type"],
        valid_from=datetime.fromisoformat(row["valid_from"]),
        valid_until=datetime.fromisoformat(row["valid_until"]),
        usage_type=UsageType(row["usage_type"]),
        state=TicketState(row["state"]),
        created_by=UUID(row["created_by"]),
        assigned_operator=UUID(row["assigned_operator"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        passed_at=_optional_datetime(row["passed_at"]),
        print_count=row["print_count"],
        use_count=row["use_count"],
        ticket_type=row["ticket_type"],
        base_price=row["base_price"],
        discount_percent=row["discount_percent"],
        currency=Currency(row["currency"]) if row["currency"] else None,
    )


def _ticket_type(row: sqlite3.Row) -> TicketType:
    return TicketType(UUID(row["id"]), row["name"], row["price"], Currency(row["currency"]))


def _visitor_type(row: sqlite3.Row) -> VisitorType:
    return VisitorType(UUID(row["id"]), row["name"], row["discount_percent"])


def _event(row: sqlite3.Row) -> AccessEvent:
    return AccessEvent(
        event_id=row["event_id"],
        ticket_id=UUID(row["ticket_id"]) if row["ticket_id"] else None,
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        granted=bool(row["granted"]),
        outcome=Outcome(row["outcome"]),
        processed_at=datetime.fromisoformat(row["processed_at"]),
    )


def _instant(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _web_session(row: sqlite3.Row) -> WebSession:
    return WebSession(
        token_hash=row["token_hash"],
        user_id=UUID(row["user_id"]),
        csrf_token=row["csrf_token"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
    )


def _registration(row: sqlite3.Row) -> Registration:
    return Registration(
        external_id=row["external_id"],
        card_id=row["card_id"],
        user_removed=bool(row["user_removed"]),
        card_removed=bool(row["card_removed"]),
    )


class SQLiteRepository(Repository):
    def __init__(self, path: Path | str = Path("tiqr.db")) -> None:
        location = str(path)
        if location != ":memory:":
            Path(location).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(location, timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def initialize(self, *, upgrade: bool = False) -> None:
        """Create a new database, or check an existing one is current.

        An older schema is upgraded only when `upgrade` is set, which `tiqr setup` does, so the
        database can be backed up first. A newer one is always refused.
        """
        with self._lock:
            tables = {
                name
                for (name,) in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if {"guests", "print_jobs"} & tables:
                raise ValueError("Reference application database detected; use a new TIQR_DB")
            (version,) = self._connection.execute("PRAGMA user_version").fetchone()
            if not 0 <= version <= SCHEMA_VERSION:
                raise ValueError(f"Unsupported database version: {version}")
            if 0 < version < SCHEMA_VERSION and not upgrade:
                raise ValueError(
                    f"Database schema version {version} is out of date; back the database up,"
                    " then run `tiqr setup` to upgrade it"
                )
            # A current database skips every step, sparing each command a write and fsync.
            for target in range(version + 1, SCHEMA_VERSION + 1):
                self._migrate(_MIGRATIONS[target - 1], target)

    def _migrate(self, statements: tuple[str, ...], version: int) -> None:
        # The version is set in the same transaction, so a failed step leaves the old schema.
        with self.transaction():
            # Another process may have run this step while this one waited for the write lock.
            (current,) = self._connection.execute("PRAGMA user_version").fetchone()
            if current >= version:
                return
            for statement in statements:
                self._connection.execute(statement)
            self._connection.execute(f"PRAGMA user_version = {version}")

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def transaction(self) -> Generator[None]:
        """Run the block in one IMMEDIATE transaction; nested calls join the outer one."""
        with self._lock:
            if self._connection.in_transaction:
                yield
                return
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def ping(self) -> bool:
        """Whether the database answers a read; a read needs no write lock, so it never waits."""
        try:
            with self._lock:
                self._connection.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return False
        return True

    def _execute(self, sql: str, parameters: Sequence[_Value] | dict[str, _Value] = ()) -> None:
        with self.transaction():
            self._connection.execute(sql, parameters)

    def _fetch_one[T](
        self, decode: Callable[[sqlite3.Row], T], sql: str, parameters: Sequence[_Value] = ()
    ) -> T | None:
        with self._lock:
            row: sqlite3.Row | None = self._connection.execute(sql, parameters).fetchone()
        return None if row is None else decode(row)

    def _fetch_all[T](self, decode: Callable[[sqlite3.Row], T], sql: str) -> list[T]:
        with self._lock:
            rows: list[sqlite3.Row] = self._connection.execute(sql).fetchall()
        return [decode(row) for row in rows]

    def add_user(self, user: User) -> None:
        self._execute(
            "INSERT INTO users (id, username, password_hash, role, active) VALUES (?,?,?,?,?)",
            (str(user.id), user.username, user.password_hash, user.role.value, int(user.active)),
        )

    def save_user(self, user: User) -> None:
        """Store a changed role, password or active state; usernames never change."""
        self._execute(
            "UPDATE users SET password_hash=?, role=?, active=? WHERE id=?",
            (user.password_hash, user.role.value, int(user.active), str(user.id)),
        )

    def user_by_name(self, username: str) -> User | None:
        return self._fetch_one(_user, "SELECT * FROM users WHERE username=?", (username,))

    def user_by_id(self, user_id: UUID) -> User | None:
        return self._fetch_one(_user, "SELECT * FROM users WHERE id=?", (str(user_id),))

    def list_users(self) -> list[User]:
        return self._fetch_all(_user, "SELECT * FROM users ORDER BY username")

    def delete_user(self, user_id: UUID) -> None:
        """Delete an account; its web sessions go with it."""
        self._execute("DELETE FROM users WHERE id=?", (str(user_id),))

    def add_ticket_type(self, ticket_type: TicketType) -> None:
        self._execute(
            "INSERT INTO ticket_types (id, name, price, currency) VALUES (?,?,?,?)",
            (str(ticket_type.id), ticket_type.name, ticket_type.price, ticket_type.currency),
        )

    def save_ticket_type(self, ticket_type: TicketType) -> None:
        self._execute(
            "UPDATE ticket_types SET name=?, price=?, currency=? WHERE id=?",
            (ticket_type.name, ticket_type.price, ticket_type.currency, str(ticket_type.id)),
        )

    def get_ticket_type(self, type_id: UUID) -> TicketType | None:
        return self._fetch_one(
            _ticket_type, "SELECT * FROM ticket_types WHERE id=?", (str(type_id),)
        )

    def ticket_type_by_name(self, name: str) -> TicketType | None:
        return self._fetch_one(_ticket_type, "SELECT * FROM ticket_types WHERE name=?", (name,))

    def list_ticket_types(self) -> list[TicketType]:
        return self._fetch_all(_ticket_type, "SELECT * FROM ticket_types ORDER BY name, id")

    def delete_ticket_type(self, type_id: UUID) -> None:
        self._execute("DELETE FROM ticket_types WHERE id=?", (str(type_id),))

    def add_visitor_type(self, visitor_type: VisitorType) -> None:
        self._execute(
            "INSERT INTO visitor_types (id, name, discount_percent) VALUES (?,?,?)",
            (str(visitor_type.id), visitor_type.name, visitor_type.discount_percent),
        )

    def save_visitor_type(self, visitor_type: VisitorType) -> None:
        self._execute(
            "UPDATE visitor_types SET name=?, discount_percent=? WHERE id=?",
            (visitor_type.name, visitor_type.discount_percent, str(visitor_type.id)),
        )

    def get_visitor_type(self, type_id: UUID) -> VisitorType | None:
        return self._fetch_one(
            _visitor_type, "SELECT * FROM visitor_types WHERE id=?", (str(type_id),)
        )

    def visitor_type_by_name(self, name: str) -> VisitorType | None:
        return self._fetch_one(_visitor_type, "SELECT * FROM visitor_types WHERE name=?", (name,))

    def list_visitor_types(self) -> list[VisitorType]:
        return self._fetch_all(_visitor_type, "SELECT * FROM visitor_types ORDER BY name, id")

    def delete_visitor_type(self, type_id: UUID) -> None:
        self._execute("DELETE FROM visitor_types WHERE id=?", (str(type_id),))

    def save_ticket(self, ticket: Ticket) -> None:
        self._execute(
            _UPSERT_TICKET, {column: _to_sql(getattr(ticket, column)) for column in _TICKET_COLUMNS}
        )

    def get_ticket(self, ticket_id: UUID) -> Ticket | None:
        return self._fetch_one(_ticket, "SELECT * FROM tickets WHERE id=?", (str(ticket_id),))

    def ticket_by_external_id(self, external_id: str) -> Ticket | None:
        return self._fetch_one(_ticket, "SELECT * FROM tickets WHERE external_id=?", (external_id,))

    def list_tickets(self) -> list[Ticket]:
        return self._fetch_all(_ticket, "SELECT * FROM tickets ORDER BY created_at, id")

    def get_event(self, event_id: str) -> AccessEvent | None:
        return self._fetch_one(_event, "SELECT * FROM access_events WHERE event_id=?", (event_id,))

    def add_event(self, event: AccessEvent) -> None:
        self._execute(
            "INSERT INTO access_events VALUES (?,?,?,?,?,?)",
            (
                event.event_id,
                _to_sql(event.ticket_id),
                event.occurred_at.isoformat(),
                int(event.granted),
                event.outcome.value,
                event.processed_at.isoformat(),
            ),
        )

    def list_events(self) -> list[AccessEvent]:
        return self._fetch_all(_event, "SELECT * FROM access_events ORDER BY occurred_at, event_id")

    def get_cursor(self) -> SyncCursor | None:
        return self._fetch_one(
            lambda row: SyncCursor(row["token"]), "SELECT token FROM sync_cursor WHERE id=1"
        )

    def save_cursor(self, cursor: SyncCursor) -> None:
        self._execute(
            "INSERT INTO sync_cursor VALUES (1,?) "
            "ON CONFLICT(id) DO UPDATE SET token=excluded.token",
            (cursor.token,),
        )

    def allocate(self, name: str, start: int = 1) -> int:
        with self.transaction():
            # Fully fetched so the statement finishes before the commit.
            [(value,)] = self._connection.execute(
                "INSERT INTO sequences VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=max(excluded.value, value + 1) "
                "RETURNING value",
                (name, start),
            ).fetchall()
        return int(value)

    def save_registration(self, registration: Registration) -> None:
        self._execute(
            "INSERT INTO registrations VALUES (?,?,?,?) ON CONFLICT(external_id) DO UPDATE SET "
            "card_id=excluded.card_id,user_removed=excluded.user_removed,"
            "card_removed=excluded.card_removed",
            (
                registration.external_id,
                registration.card_id,
                int(registration.user_removed),
                int(registration.card_removed),
            ),
        )

    def get_registration(self, external_id: str) -> Registration | None:
        return self._fetch_one(
            _registration, "SELECT * FROM registrations WHERE external_id=?", (external_id,)
        )

    def is_cleaned(self, ticket_id: UUID) -> bool:
        sql = "SELECT 1 FROM cleaned_tickets WHERE ticket_id=?"
        return self._fetch_one(lambda _: True, sql, (str(ticket_id),)) is not None

    def mark_cleaned(self, ticket_id: UUID) -> None:
        self._execute("INSERT OR IGNORE INTO cleaned_tickets VALUES (?)", (str(ticket_id),))

    def add_web_session(self, session: WebSession) -> None:
        self._execute(
            "INSERT INTO web_sessions VALUES (?,?,?,?,?,?)",
            (
                session.token_hash,
                str(session.user_id),
                session.csrf_token,
                _instant(session.created_at),
                _instant(session.last_seen_at),
                _instant(session.expires_at),
            ),
        )

    def get_web_session(self, token_hash: str) -> WebSession | None:
        return self._fetch_one(
            _web_session, "SELECT * FROM web_sessions WHERE token_hash=?", (token_hash,)
        )

    def touch_web_session(self, token_hash: str, seen_at: datetime) -> None:
        self._execute(
            "UPDATE web_sessions SET last_seen_at=? WHERE token_hash=?",
            (_instant(utc(seen_at)), token_hash),
        )

    def delete_web_session(self, token_hash: str) -> None:
        self._execute("DELETE FROM web_sessions WHERE token_hash=?", (token_hash,))

    def delete_user_web_sessions(self, user_id: UUID) -> None:
        self._execute("DELETE FROM web_sessions WHERE user_id=?", (str(user_id),))

    def purge_web_sessions(self, idle_since: datetime, now: datetime) -> None:
        """Delete sessions last seen at or before `idle_since`, or that ended by `now`."""
        self._execute(
            "DELETE FROM web_sessions WHERE last_seen_at<=? OR expires_at<=?",
            (_instant(utc(idle_since)), _instant(utc(now))),
        )
