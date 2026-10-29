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
    ApiKey,
    AuditEntry,
    Currency,
    LicenseRecord,
    Outcome,
    Registration,
    Role,
    StoredResponse,
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
# SQLite cannot change a CHECK, so the tables that hold currencies are rebuilt to accept tenge.
# `tickets` has children, so its foreign keys are off while the steps run (see `initialize`).
_TENGE = """
CREATE TABLE ticket_types_rebuilt (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    price INTEGER NOT NULL CHECK(price >= 0),
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency IN ('USD','RUB','AZN','KZT'))
);
INSERT INTO ticket_types_rebuilt (id, name, price, currency)
    SELECT id, name, price, currency FROM ticket_types;
DROP TABLE ticket_types;
ALTER TABLE ticket_types_rebuilt RENAME TO ticket_types;
CREATE TABLE tickets_rebuilt (
    id TEXT PRIMARY KEY, external_id TEXT UNIQUE, qr_payload TEXT NOT NULL UNIQUE,
    readable_serial TEXT NOT NULL UNIQUE, visitor_name TEXT NOT NULL, visitor_type TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_until TEXT NOT NULL,
    usage_type TEXT NOT NULL CHECK(usage_type IN ('one_time','multi_use')),
    state TEXT NOT NULL CHECK(state IN ('issued','passed','expired')),
    created_by TEXT NOT NULL REFERENCES users(id),
    assigned_operator TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL, passed_at TEXT,
    print_count INTEGER NOT NULL CHECK(print_count >= 0),
    use_count INTEGER NOT NULL CHECK(use_count >= 0),
    ticket_type TEXT, base_price INTEGER CHECK(base_price >= 0),
    discount_percent INTEGER NOT NULL DEFAULT 0
        CHECK(discount_percent BETWEEN 0 AND 100),
    currency TEXT CHECK(currency IN ('USD','RUB','AZN','KZT'))
);
INSERT INTO tickets_rebuilt (
    id, external_id, qr_payload, readable_serial, visitor_name, visitor_type, valid_from,
    valid_until, usage_type, state, created_by, assigned_operator, created_at, passed_at,
    print_count, use_count, ticket_type, base_price, discount_percent, currency
) SELECT
    id, external_id, qr_payload, readable_serial, visitor_name, visitor_type, valid_from,
    valid_until, usage_type, state, created_by, assigned_operator, created_at, passed_at,
    print_count, use_count, ticket_type, base_price, discount_percent, currency
FROM tickets;
DROP TABLE tickets;
ALTER TABLE tickets_rebuilt RENAME TO tickets;
"""
# Keys are never deleted: a new activation deactivates the old row, so the table is a history.
_LICENSES = """
CREATE TABLE licenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, license_key TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK(is_active IN (0,1)), activated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, licensed_to TEXT NOT NULL
)
"""

_TICKETS_V7 = """
    id TEXT PRIMARY KEY, external_id TEXT UNIQUE, qr_payload TEXT NOT NULL UNIQUE,
    readable_serial TEXT NOT NULL UNIQUE, visitor_name TEXT NOT NULL, visitor_type TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_until TEXT NOT NULL,
    usage_type TEXT NOT NULL CHECK(usage_type IN ('one_time','multi_use')),
    state TEXT NOT NULL CHECK(state IN ({states})),
    created_by TEXT NOT NULL REFERENCES users(id),
    assigned_operator TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL, passed_at TEXT,
    print_count INTEGER NOT NULL CHECK(print_count >= 0),
    use_count INTEGER NOT NULL CHECK(use_count >= 0),
    ticket_type TEXT, base_price INTEGER CHECK(base_price >= 0),
    discount_percent INTEGER NOT NULL DEFAULT 0
        CHECK(discount_percent BETWEEN 0 AND 100),
    currency TEXT CHECK(currency IN ('USD','RUB','AZN','KZT'))
"""
_COLUMNS_V7 = """id, external_id, qr_payload, readable_serial, visitor_name, visitor_type,
    valid_from, valid_until, usage_type, state, created_by, assigned_operator, created_at,
    passed_at, print_count, use_count, ticket_type, base_price, discount_percent, currency"""
_STATES_V7 = "'issued','passed','expired'"
_STATES_V8 = "'issued','passed','expired','revoked'"

# Revoked tickets, the caller's own code (unique per tenant) and an event session. SQLite cannot
# change a CHECK, so `tickets` is rebuilt, as in _TENGE.
_REVOCATION = f"""
CREATE TABLE tickets_rebuilt ({_TICKETS_V7.format(states=_STATES_V8)},
    external_code TEXT, tenant_id TEXT NOT NULL DEFAULT 'default', event_session TEXT
);
INSERT INTO tickets_rebuilt ({_COLUMNS_V7}) SELECT {_COLUMNS_V7} FROM tickets;
DROP TABLE tickets;
ALTER TABLE tickets_rebuilt RENAME TO tickets;
CREATE UNIQUE INDEX tickets_external_code ON tickets(tenant_id, external_code)
    WHERE external_code IS NOT NULL
"""  # noqa: S608 - built from the constants above, not input
# Undoing it: a revoked ticket reads as expired, since it grants no access either way, and the
# external codes, tenants and sessions go with their columns.
_REVOCATION_DOWN = f"""
DROP INDEX tickets_external_code;
CREATE TABLE tickets_rebuilt ({_TICKETS_V7.format(states=_STATES_V7)});
INSERT INTO tickets_rebuilt ({_COLUMNS_V7}) SELECT {
    _COLUMNS_V7.replace("state,", "CASE state WHEN 'revoked' THEN 'expired' ELSE state END,")
} FROM tickets;
DROP TABLE tickets;
ALTER TABLE tickets_rebuilt RENAME TO tickets
"""  # noqa: S608 - built from the constants above, not input
# Passages gain their point and direction, and a sequence that orders the feed. A sequence is
# assigned at insert, so an event that arrives late still lands after the cursor it missed.
# A pass also gets a second card, carrying the caller's own code, so readers accept either.
_PASSAGES = """
ALTER TABLE access_events ADD COLUMN point_id TEXT;
ALTER TABLE access_events ADD COLUMN point_name TEXT;
ALTER TABLE access_events ADD COLUMN direction TEXT;
ALTER TABLE access_events ADD COLUMN sequence INTEGER;
UPDATE access_events SET sequence = rowid;
CREATE UNIQUE INDEX access_events_sequence ON access_events(sequence);
ALTER TABLE registrations ADD COLUMN external_card_id TEXT;
"""
_PASSAGES_DOWN = """
DROP INDEX access_events_sequence;
ALTER TABLE access_events DROP COLUMN point_id;
ALTER TABLE access_events DROP COLUMN point_name;
ALTER TABLE access_events DROP COLUMN direction;
ALTER TABLE access_events DROP COLUMN sequence;
ALTER TABLE registrations DROP COLUMN external_card_id
"""
# The audit log is append-only. Idempotency records expire; API keys keep only a hash.
_SERVICE_TABLES = """
CREATE TABLE audit_log (
    id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    ticket_id TEXT, reason TEXT, detail TEXT
);
CREATE INDEX audit_log_ticket ON audit_log(ticket_id, occurred_at);
CREATE TABLE idempotency_keys (
    tenant_id TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
    status INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, PRIMARY KEY (tenant_id, key)
);
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, scopes TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT, replaced_by TEXT
)
"""
_SERVICE_TABLES_DOWN = """
DROP TABLE api_keys;
DROP TABLE idempotency_keys;
DROP TABLE audit_log
"""


def _statements(script: str) -> tuple[str, ...]:
    # No statement here contains a semicolon of its own, so splitting on them is exact.
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


# Step N upgrades schema version N to N + 1. Steps are append-only, and each runs once, in one
# transaction with its version bump.
_MIGRATIONS = tuple(
    _statements(script)
    for script in (
        _SCHEMA,
        _WEB_SESSIONS,
        _USER_ACTIVE,
        _CATALOG,
        _CURRENCY,
        _TENGE,
        _LICENSES,
        _REVOCATION,
        _SERVICE_TABLES,
        _PASSAGES,
    )
)
# Reversal N undoes step N, taking version N to N - 1. Steps 1 to 7 predate reversals and are not
# reversible; every later step must add one.
_REVERSALS = {
    8: _statements(_REVOCATION_DOWN),
    9: _statements(_SERVICE_TABLES_DOWN),
    10: _statements(_PASSAGES_DOWN),
}
OLDEST_REVERSIBLE = min(_REVERSALS) - 1
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


def _license(row: sqlite3.Row) -> LicenseRecord:
    return LicenseRecord(
        row["license_key"],
        datetime.fromisoformat(row["activated_at"]),
        datetime.fromisoformat(row["expires_at"]),
        row["licensed_to"],
        is_active=bool(row["is_active"]),
        id=row["id"],
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
        external_code=row["external_code"],
        tenant_id=row["tenant_id"],
        event_session=row["event_session"],
    )


def _audit(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        id=UUID(row["id"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        actor=row["actor"],
        action=row["action"],
        ticket_id=UUID(row["ticket_id"]) if row["ticket_id"] else None,
        reason=row["reason"],
        detail=row["detail"],
    )


def _stored_response(row: sqlite3.Row) -> StoredResponse:
    return StoredResponse(
        key=row["key"],
        tenant_id=row["tenant_id"],
        fingerprint=row["fingerprint"],
        status=row["status"],
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
    )


def _api_key(row: sqlite3.Row) -> ApiKey:
    return ApiKey(
        id=UUID(row["id"]),
        name=row["name"],
        key_hash=row["key_hash"],
        user_id=UUID(row["user_id"]),
        scopes=tuple(row["scopes"].split()),
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=_optional_datetime(row["expires_at"]),
        revoked_at=_optional_datetime(row["revoked_at"]),
        replaced_by=UUID(row["replaced_by"]) if row["replaced_by"] else None,
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
        point_id=row["point_id"],
        point_name=row["point_name"],
        direction=row["direction"],
        sequence=row["sequence"],
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
        external_card_id=row["external_card_id"],
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
                raise ValueError("Reference application database detected; use a new database file")
            (version,) = self._connection.execute("PRAGMA user_version").fetchone()
            if not 0 <= version <= SCHEMA_VERSION:
                raise ValueError(f"Unsupported database version: {version}")
            if 0 < version < SCHEMA_VERSION and not upgrade:
                raise ValueError(
                    f"Database schema version {version} is out of date; back the database up,"
                    " then run `tiqr setup` to upgrade it"
                )
            # A current database skips every step, sparing each command a write and fsync.
            # Dropping a table with children needs foreign keys off; a no-op inside a transaction.
            self._connection.execute("PRAGMA foreign_keys = OFF")
            try:
                for target in range(version + 1, SCHEMA_VERSION + 1):
                    self._migrate(_MIGRATIONS[target - 1], target)
            finally:
                self._connection.execute("PRAGMA foreign_keys = ON")

    def downgrade(self, target: int) -> None:
        """Undo schema steps down to version `target`, newest first; back the database up first."""
        with self._lock:
            (version,) = self._connection.execute("PRAGMA user_version").fetchone()
            if not OLDEST_REVERSIBLE <= target <= version:
                raise ValueError(
                    f"Cannot downgrade from {version} to {target}; "
                    f"only versions {OLDEST_REVERSIBLE} and up are reachable"
                )
            self._connection.execute("PRAGMA foreign_keys = OFF")
            try:
                for current in range(version, target, -1):
                    self._revert(_REVERSALS[current], current)
            finally:
                self._connection.execute("PRAGMA foreign_keys = ON")

    def _revert(self, statements: tuple[str, ...], version: int) -> None:
        with self.transaction():
            for statement in statements:
                self._connection.execute(statement)
            if self._connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(f"Downgrading from schema version {version} would orphan rows")
            self._connection.execute(f"PRAGMA user_version = {version - 1}")

    def _migrate(self, statements: tuple[str, ...], version: int) -> None:
        # The version is set in the same transaction, so a failed step leaves the old schema.
        with self.transaction():
            # Another process may have run this step while this one waited for the write lock.
            (current,) = self._connection.execute("PRAGMA user_version").fetchone()
            if current >= version:
                return
            for statement in statements:
                self._connection.execute(statement)
            # Checked before the commit, so a step that orphans rows rolls back instead.
            if self._connection.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(f"Upgrading to schema version {version} would orphan rows")
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

    def _fetch_all[T](
        self, decode: Callable[[sqlite3.Row], T], sql: str, parameters: Sequence[_Value] = ()
    ) -> list[T]:
        with self._lock:
            rows: list[sqlite3.Row] = self._connection.execute(sql, parameters).fetchall()
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

    def ticket_by_external_code(self, tenant_id: str, external_code: str) -> Ticket | None:
        return self._fetch_one(
            _ticket,
            "SELECT * FROM tickets WHERE tenant_id=? AND external_code=?",
            (tenant_id, external_code),
        )

    def add_audit(self, entry: AuditEntry) -> None:
        self._execute(
            "INSERT INTO audit_log (id, occurred_at, actor, action, ticket_id, reason, detail)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                str(entry.id),
                _instant(entry.occurred_at),
                entry.actor,
                entry.action,
                str(entry.ticket_id) if entry.ticket_id else None,
                entry.reason,
                entry.detail,
            ),
        )

    def list_audit(self, ticket_id: UUID | None = None) -> list[AuditEntry]:
        where, parameters = (
            ("", ()) if ticket_id is None else (" WHERE ticket_id=?", (str(ticket_id),))
        )
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM audit_log{where} ORDER BY occurred_at, rowid",  # noqa: S608 - fixed text
                parameters,
            ).fetchall()
        return [_audit(row) for row in rows]

    def get_stored_response(self, tenant_id: str, key: str, now: datetime) -> StoredResponse | None:
        """The saved answer for `key`, unless it has expired."""
        return self._fetch_one(
            _stored_response,
            "SELECT * FROM idempotency_keys WHERE tenant_id=? AND key=? AND expires_at>?",
            (tenant_id, key, _instant(now)),
        )

    def save_stored_response(self, response: StoredResponse) -> None:
        with self.transaction():
            # An expired record under the same key is replaced.
            self._connection.execute(
                "DELETE FROM idempotency_keys WHERE tenant_id=? AND key=?",
                (response.tenant_id, response.key),
            )
            self._connection.execute(
                "INSERT INTO idempotency_keys (tenant_id, key, fingerprint, status, body,"
                " created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (
                    response.tenant_id,
                    response.key,
                    response.fingerprint,
                    response.status,
                    response.body,
                    _instant(response.created_at),
                    _instant(response.expires_at),
                ),
            )

    def purge_stored_responses(self, now: datetime) -> int:
        with self.transaction():
            cursor = self._connection.execute(
                "DELETE FROM idempotency_keys WHERE expires_at<=?", (_instant(now),)
            )
            return cursor.rowcount

    def save_api_key(self, key: ApiKey) -> None:
        self._execute(
            "INSERT INTO api_keys (id, name, key_hash, user_id, scopes, created_at, expires_at,"
            " revoked_at, replaced_by) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET"
            " name=excluded.name, scopes=excluded.scopes, expires_at=excluded.expires_at,"
            " revoked_at=excluded.revoked_at, replaced_by=excluded.replaced_by",
            (
                str(key.id),
                key.name,
                key.key_hash,
                str(key.user_id),
                " ".join(key.scopes),
                _instant(key.created_at),
                _instant(key.expires_at) if key.expires_at else None,
                _instant(key.revoked_at) if key.revoked_at else None,
                str(key.replaced_by) if key.replaced_by else None,
            ),
        )

    def get_api_key(self, key_id: UUID) -> ApiKey | None:
        return self._fetch_one(_api_key, "SELECT * FROM api_keys WHERE id=?", (str(key_id),))

    def api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        return self._fetch_one(_api_key, "SELECT * FROM api_keys WHERE key_hash=?", (key_hash,))

    def list_api_keys(self) -> list[ApiKey]:
        return self._fetch_all(_api_key, "SELECT * FROM api_keys ORDER BY created_at, id")

    def list_tickets(self) -> list[Ticket]:
        return self._fetch_all(_ticket, "SELECT * FROM tickets ORDER BY created_at, id")

    def get_event(self, event_id: str) -> AccessEvent | None:
        return self._fetch_one(_event, "SELECT * FROM access_events WHERE event_id=?", (event_id,))

    def add_event(self, event: AccessEvent) -> None:
        self._execute(
            "INSERT INTO access_events (event_id, ticket_id, occurred_at, granted, outcome, "
            "processed_at, point_id, point_name, direction, sequence) "
            "VALUES (?,?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(sequence), 0) + 1 FROM access_events))",
            (
                event.event_id,
                _to_sql(event.ticket_id),
                event.occurred_at.isoformat(),
                int(event.granted),
                event.outcome.value,
                event.processed_at.isoformat(),
                event.point_id,
                event.point_name,
                event.direction,
            ),
        )

    def list_events(self) -> list[AccessEvent]:
        return self._fetch_all(_event, "SELECT * FROM access_events ORDER BY occurred_at, event_id")

    def list_passages(self, after: int, limit: int) -> list[AccessEvent]:
        return self._fetch_all(
            _event,
            "SELECT * FROM access_events WHERE sequence>? ORDER BY sequence LIMIT ?",
            (after, limit),
        )

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
            "INSERT INTO registrations (external_id, card_id, user_removed, card_removed, "
            "external_card_id) VALUES (?,?,?,?,?) ON CONFLICT(external_id) DO UPDATE SET "
            "card_id=excluded.card_id,user_removed=excluded.user_removed,"
            "card_removed=excluded.card_removed,external_card_id=excluded.external_card_id",
            (
                registration.external_id,
                registration.card_id,
                int(registration.user_removed),
                int(registration.card_removed),
                registration.external_card_id,
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

    def activate_license(self, record: LicenseRecord) -> None:
        """Deactivate every key and store this one as the active key, in one transaction."""
        with self.transaction():
            self._connection.execute("UPDATE licenses SET is_active=0")
            self._connection.execute(
                "INSERT INTO licenses (license_key, is_active, activated_at, expires_at,"
                " licensed_to) VALUES (?,1,?,?,?)",
                (
                    record.license_key,
                    _instant(record.activated_at),
                    _instant(record.expires_at),
                    record.licensed_to,
                ),
            )

    def deactivate_licenses(self) -> None:
        self._execute("UPDATE licenses SET is_active=0")

    def active_license(self) -> LicenseRecord | None:
        return self._fetch_one(
            _license, "SELECT * FROM licenses WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        )

    def list_licenses(self) -> list[LicenseRecord]:
        return self._fetch_all(_license, "SELECT * FROM licenses ORDER BY id DESC")
