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
    Outcome,
    Registration,
    Role,
    SyncCursor,
    Ticket,
    TicketState,
    UsageType,
    User,
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
PRAGMA user_version = 1;
"""

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
    return User(UUID(row["id"]), row["username"], row["password_hash"], Role(row["role"]))


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
    )


def _event(row: sqlite3.Row) -> AccessEvent:
    return AccessEvent(
        event_id=row["event_id"],
        ticket_id=UUID(row["ticket_id"]) if row["ticket_id"] else None,
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        granted=bool(row["granted"]),
        outcome=Outcome(row["outcome"]),
        processed_at=datetime.fromisoformat(row["processed_at"]),
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

    def initialize(self) -> None:
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
            if version not in (0, 1):
                raise ValueError(f"Unsupported database version: {version}")
            # user_version is set last, so version 1 means a complete schema; skipping the script
            # spares every command a write and fsync.
            if version == 0:
                self._connection.executescript(_SCHEMA)

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
            "INSERT INTO users VALUES (?,?,?,?)",
            (str(user.id), user.username, user.password_hash, user.role.value),
        )

    def user_by_name(self, username: str) -> User | None:
        return self._fetch_one(_user, "SELECT * FROM users WHERE username=?", (username,))

    def user_by_id(self, user_id: UUID) -> User | None:
        return self._fetch_one(_user, "SELECT * FROM users WHERE id=?", (str(user_id),))

    def list_users(self) -> list[User]:
        return self._fetch_all(_user, "SELECT * FROM users ORDER BY username")

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
