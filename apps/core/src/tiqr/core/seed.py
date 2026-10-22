"""Demo operators and tickets for trying TiQR locally, in every state the UI shows.

Local mode only: the seed writes through the in-memory adapters, so it never touches BioStar.
Run it with `TIQR_SEED_PASSWORD` set, against a database that has no tickets yet.
"""

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tiqr.core.fakes import InMemoryEventSource
from tiqr.core.models import RawEvent, Role, UsageType, User
from tiqr.core.ports import Clock, Repository
from tiqr.core.qr import DEFAULT_PREFIX
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService
from tiqr.core.settings import Settings

PASSWORD_VARIABLE = "TIQR_SEED_PASSWORD"  # noqa: S105 - the name of a variable, not a secret

OPERATORS = ("leyla", "elnur", "aynur")
# Kept in the database so the history stays visible, but unable to sign in or act.
DEACTIVATED_OPERATOR = "rufat"


@dataclass(frozen=True, slots=True)
class Scan:
    at: timedelta
    granted: bool


@dataclass(frozen=True, slots=True)
class Visit:
    visitor: str
    visitor_type: str
    usage: UsageType
    operator: str
    created: timedelta
    starts: timedelta
    ends: timedelta
    scans: tuple[Scan, ...] = ()


# Offsets are relative to the seed's clock. Expired visits are created in the past so that
# reading them later shows them expired, exactly as a ticket that ran out in real use would.
VISITS = (
    Visit(
        "Adam Tələbə",
        "Tələbə",
        UsageType.ONE_TIME,
        "leyla",
        created=timedelta(hours=-1),
        starts=timedelta(days=1),
        ends=timedelta(days=1, hours=8),
    ),
    Visit(
        "Günel Məmmədova",
        "Qonaq",
        UsageType.MULTI_USE,
        "elnur",
        created=timedelta(hours=-1),
        starts=timedelta(hours=-1),
        ends=timedelta(days=10),
        scans=(Scan(timedelta(minutes=-30), granted=False),),
    ),
    Visit(
        "Rəşad Əliyev",
        "Əməkdaş",
        UsageType.ONE_TIME,
        "aynur",
        created=timedelta(hours=-1),
        starts=timedelta(days=3),
        ends=timedelta(days=3, hours=8),
    ),
    Visit(
        "Ləman Cəfərova",
        "Tələbə",
        UsageType.MULTI_USE,
        DEACTIVATED_OPERATOR,
        created=timedelta(hours=-1),
        starts=timedelta(hours=-1),
        ends=timedelta(days=2),
    ),
    Visit(
        "Nigar Həsənova",
        "Tələbə",
        UsageType.ONE_TIME,
        "leyla",
        created=timedelta(hours=-2),
        starts=timedelta(hours=-2),
        ends=timedelta(days=1),
        scans=(Scan(timedelta(hours=-1), granted=True),),
    ),
    Visit(
        "Orxan Quliyev",
        "Qonaq",
        UsageType.MULTI_USE,
        "elnur",
        created=timedelta(hours=-3),
        starts=timedelta(hours=-3),
        ends=timedelta(days=5),
        scans=(Scan(timedelta(hours=-2), granted=True), Scan(timedelta(hours=-1), granted=True)),
    ),
    Visit(
        "Səbinə Rzayeva",
        "Qonaq",
        UsageType.ONE_TIME,
        "aynur",
        created=timedelta(days=-10),
        starts=timedelta(days=-10),
        ends=timedelta(days=-9),
    ),
    Visit(
        "Vüsal Nəsirov",
        "Əməkdaş",
        UsageType.MULTI_USE,
        "leyla",
        created=timedelta(days=-10),
        starts=timedelta(days=-10),
        ends=timedelta(days=-9, hours=12),
    ),
)


@dataclass(frozen=True, slots=True)
class SeedReport:
    operators: tuple[str, ...]
    tickets: int
    events: int


class SeedError(RuntimeError):
    pass


def _at(moment: datetime) -> Clock:
    return lambda: moment


def _now() -> datetime:
    return datetime.now(UTC)


def _manager(repository: Repository) -> User:
    for user in repository.list_users():
        if user.role == Role.MANAGER and user.active:
            return user
    raise SeedError("Seeding needs an active manager; run `tiqr user add <name> --role manager`")


def seed_demo(
    repository: Repository,
    secret_key: str,
    password: str,
    *,
    prefix: str = DEFAULT_PREFIX,
    clock: Clock | None = None,
) -> SeedReport:
    """Add the demo operators and visits to `repository`, refusing a database with tickets."""
    clock = clock or _now
    now = clock().replace(microsecond=0)
    if repository.list_tickets():
        raise SeedError("The database already has tickets; seed only an empty database")
    manager = _manager(repository)

    added: list[str] = []
    for name in (*OPERATORS, DEACTIVATED_OPERATOR):
        if repository.user_by_name(name) is None:
            TicketService(repository, secret_key, prefix=prefix).add_user(
                name, password, Role.OPERATOR
            )
            added.append(name)

    events: list[RawEvent] = []
    for number, visit in enumerate(VISITS, start=1):
        # Each visit is created at its own offset, so backdated visits are stamped in the past.
        service = TicketService(
            repository, secret_key, clock=_at(now + visit.created), prefix=prefix
        )
        ticket = service.create_ticket(
            manager,
            visitor_name=visit.visitor,
            visitor_type=visit.visitor_type,
            valid_from=now + visit.starts,
            valid_until=now + visit.ends,
            usage_type=visit.usage,
        )
        service.assign_ticket(manager, ticket.id, visit.operator)
        events.extend(
            RawEvent(
                event_id=f"seed-{number}-{index}",
                external_id=ticket.external_id,
                occurred_at=now + scan.at,
                granted=scan.granted,
            )
            for index, scan in enumerate(visit.scans, start=1)
        )

    # Scans are replayed through the real sync path, so passed tickets get their use counts.
    stored = TicketService(
        repository, secret_key, event_source=InMemoryEventSource(events), clock=clock, prefix=prefix
    ).scheduled_sync()
    # Deactivated last, after its ticket exists, so the account keeps its history.
    deactivated = repository.user_by_name(DEACTIVATED_OPERATOR)
    if deactivated is not None and deactivated.active:
        TicketService(repository, secret_key, prefix=prefix).edit_user(deactivated.id, active=False)
    return SeedReport(operators=tuple(added), tickets=len(VISITS), events=stored)


def main() -> None:
    """Seed the configured database from the command line; prints the outcome."""
    password = os.environ.get(PASSWORD_VARIABLE, "")
    if not password:
        sys.exit(f"Set {PASSWORD_VARIABLE} to the password for the demo operators")
    settings = Settings.from_env()
    if settings.biostar is not None:
        sys.exit("tiqr seed only runs in local mode; unset the TIQR_BIOSTAR_* settings first")
    with SQLiteRepository(settings.database_path) as repository:
        repository.initialize()
        try:
            report = seed_demo(repository, settings.secret_key, password, prefix=settings.prefix)
        except (SeedError, ValueError) as exc:
            sys.exit(f"Error: {exc}")
    sys.stdout.write(
        f"Added operators: {', '.join(report.operators) or 'none'}\n"
        f"Created {report.tickets} tickets with {report.events} access events\n"
    )


if __name__ == "__main__":
    main()
