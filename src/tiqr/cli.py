import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Generator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from tiqr.auth import AuthenticationError, Session
from tiqr.biostar import (
    ACCESS_GROUP_NAME,
    BioStarClient,
    BioStarError,
    BioStarXEventSource,
    BioStarXProvisioner,
    BioStarXRegistrar,
)
from tiqr.models import Role, Ticket, TicketState, UsageType, User
from tiqr.ports import EventSource, Registrar
from tiqr.repository import SQLiteRepository
from tiqr.service import TicketService
from tiqr.settings import (
    LOCAL_ENV_FILE,
    Settings,
    database_path,
    discard_access_group_id,
    discard_secret,
    provision_secret,
    session_path,
)

# Failures a user can act on; anything else is a bug and keeps its traceback.
_EXPECTED_ERRORS = (ValueError, PermissionError, LookupError, RuntimeError, sqlite3.Error, OSError)
_TICKET_FIELDS = (
    "id",
    "readable_serial",
    "visitor_name",
    "visitor_type",
    "valid_from",
    "valid_until",
    "usage_type",
    "state",
    "created_by",
    "assigned_operator",
    "print_count",
    "use_count",
)
_DB_SUFFIXES = ("-journal", "-wal", "-shm")
_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="QR ticket administration. Bootstrap commands trust the local OS account.",
)
user_app = typer.Typer(no_args_is_help=True, help="Local, trusted-account user bootstrap.")
ticket_app = typer.Typer(
    no_args_is_help=True, help="Create, inspect, assign, save and print tickets."
)
app.add_typer(user_app, name="user")
app.add_typer(ticket_app, name="ticket")

Actor = Annotated[str, typer.Option("--as", "-a")]


@dataclass(frozen=True, slots=True)
class _Runtime:
    settings: Settings
    service: TicketService

    def authenticate(self, username: str) -> User:
        cached = _read_session()
        if cached is not None and cached.username == username:
            with suppress(AuthenticationError):
                return self.service.resume_session(cached)
        user = self.service.authenticate(username, _password())
        # Caching is optional; if the file can't be written, the next command asks again.
        with suppress(OSError):
            _write_session(self.service.start_session(user))
        return user

    def ticket_data(self, ticket: Ticket) -> dict[str, object]:
        return _ticket_data(ticket, self.settings.default_tz)


def _describe(exc: Exception) -> str:
    """The message, plus the BioStar code and HTTP status when present."""
    if not isinstance(exc, BioStarError):
        return str(exc)
    details: list[str] = []
    if exc.code is not None:
        details.append(f"BioStar code {exc.code}")
    if exc.http_status is not None:
        details.append(f"HTTP {exc.http_status}")
    return f"{exc} ({', '.join(details)})" if details else str(exc)


@contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except _EXPECTED_ERRORS as exc:
        typer.echo(f"Error: {_describe(exc)}", err=True)
        raise typer.Exit(1) from None


@contextmanager
def _session() -> Generator[_Runtime]:
    """Open settings, database and adapters for one command, then close them."""
    with _errors(), ExitStack() as stack:
        settings = Settings.from_env()
        repository = stack.enter_context(SQLiteRepository(settings.database_path))
        repository.initialize()
        registrar: Registrar | None = None
        event_source: EventSource | None = None
        if settings.biostar is not None:
            client = BioStarClient(settings.biostar)
            stack.callback(client.close)
            registrar = BioStarXRegistrar(client, repository)
            event_source = BioStarXEventSource(client, repository)
        service = TicketService(
            repository,
            settings.secret_key,
            registrar=registrar,
            event_source=event_source,
            prefix=settings.prefix,
        )
        yield _Runtime(settings, service)


def parse_input_datetime(text: str, timezone: str) -> datetime:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {timezone}") from exc
    text = text.strip()
    if not _ISO_DATETIME.match(text):
        raise ValueError("Use an ISO datetime including a time, such as 2030-01-01T12:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {text}") from exc
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    # A wall-clock time maps to one instant, two (DST fall-back) or none (spring-forward).
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if candidate.astimezone(zone).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if len(candidates) != 1:
        kind = "Ambiguous" if candidates else "Nonexistent"
        raise ValueError(f"{kind} local datetime in {timezone}; supply an explicit UTC offset")
    return candidates.pop()


def _password(*, confirm: bool = False) -> str:
    password: str = typer.prompt(
        "Password", hide_input=True, confirmation_prompt=confirm, default="", show_default=False
    )
    if not password.strip():
        raise ValueError("Password must not be empty")
    return password


def _read_session() -> Session | None:
    try:
        data = json.loads(session_path().read_text(encoding="utf-8"))
        expires_at = datetime.fromtimestamp(int(data["expires_at"]), UTC)
        return Session(str(data["username"]), expires_at, str(data["token"]))
    except OSError, ValueError, KeyError, TypeError, OverflowError:
        return None


def _write_session(session: Session) -> None:
    payload = {
        "username": session.username,
        "expires_at": int(session.expires_at.timestamp()),
        "token": session.token,
    }
    # Owner-only from creation, so the token is never briefly readable by others.
    descriptor = os.open(session_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(payload, file)


def _json(value: object) -> None:
    """Print as JSON; `default=str` covers UUIDs."""
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def _sumatra_pdf() -> Path | None:
    """Find SumatraPDF, which prints silently at 100%."""
    found = shutil.which("SumatraPDF")
    if found is not None:
        return Path(found)
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base and (candidate := Path(base, "SumatraPDF", "SumatraPDF.exe")).is_file():
            return candidate
    return None


def _send_to_printer(path: Path) -> None:
    """Queue a PDF on the default printer."""
    if sys.platform == "win32":
        sumatra = _sumatra_pdf()
        if sumatra is None:
            # Returns once the job is queued, so later printer failures go unreported.
            os.startfile(path, "print")  # noqa: S606 - the path is the PDF just rendered
            return
        result = subprocess.run(  # noqa: S603 - the executable and PDF are ours
            [sumatra, "-print-to-default", "-print-settings", "noscale", "-silent", str(path)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"SumatraPDF could not print {path.name} (exit {result.returncode})")
        return
    lp = shutil.which("lp")
    if lp is None:
        raise RuntimeError(
            "Printing needs the CUPS lp command; install CUPS or print the saved PDF"
        )
    # print-scaling=none keeps the page at 100%, which the QR code size depends on.
    result = subprocess.run(  # noqa: S603 - lp is resolved above and the PDF is ours
        [lp, "-o", "print-scaling=none", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"lp exited with status {result.returncode}"
        raise RuntimeError(f"Printing failed: {detail}")


def _user_data(user: User) -> dict[str, object]:
    return {"id": user.id, "username": user.username, "role": user.role}


def _ticket_data(ticket: Ticket, timezone: str) -> dict[str, object]:
    zone = ZoneInfo(timezone)
    data: dict[str, object] = {name: getattr(ticket, name) for name in _TICKET_FIELDS}
    for name in ("valid_from", "valid_until"):
        data[name] = getattr(ticket, name).astimezone(zone).isoformat()
    return data | {"timezone": timezone}


@app.command()
def setup() -> None:
    """Create the signing key, the database, and the BioStar access group when configured.

    Without TIQR_BIOSTAR_ACCESS_GROUP_ID, BioStar gets a TiQR AG group, a TiQR AL level and a door
    per reader in TIQR_BIOSTAR_DEVICE_IDS. Reruns fill gaps.
    """
    with _errors():
        if provision_secret():
            typer.echo(f"Wrote TIQR_SECRET_KEY to {LOCAL_ENV_FILE}")
        else:
            typer.echo(f"TIQR_SECRET_KEY already set in {LOCAL_ENV_FILE}; nothing to do")
        settings = Settings.from_env()
        with SQLiteRepository(settings.database_path) as repository:
            repository.initialize()
        typer.echo(f"Database initialized: {settings.database_path}")
        if settings.biostar is not None:
            with BioStarClient(settings.biostar) as client:
                group_id = BioStarXProvisioner(client).ensure_access()
            typer.echo(f"BioStar access group {ACCESS_GROUP_NAME} ready: id {group_id}")
        typer.echo("Next: tiqr user add <username> --role admin")


@app.command()
def reset(
    *,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Delete the signing key, the pinned BioStar access group ID, and the database.

    Users and tickets are lost and printed QR codes stop verifying. BioStar and PDFs are untouched.
    """
    with _errors():
        database = database_path()
        if not yes:
            typer.confirm(
                f"Delete TIQR_SECRET_KEY and TIQR_BIOSTAR_ACCESS_GROUP_ID from {LOCAL_ENV_FILE}"
                f" and the database {database}?",
                abort=True,
            )
        if discard_secret():
            typer.echo(f"Removed TIQR_SECRET_KEY from {LOCAL_ENV_FILE}")
        if discard_access_group_id():
            typer.echo(f"Cleared TIQR_BIOSTAR_ACCESS_GROUP_ID in {LOCAL_ENV_FILE}")
        removed = [
            file
            for file in (database, *(database.with_name(database.name + s) for s in _DB_SUFFIXES))
            if file.exists()
        ]
        for file in removed:
            file.unlink()
        if removed:
            typer.echo(f"Deleted database: {database}")
        typer.echo("Reset complete. Next: tiqr setup")


@user_app.command("add")
def user_add(
    username: Annotated[str, typer.Argument()], role: Annotated[Role, typer.Option("--role")]
) -> None:
    """Add a local user, prompting for a hidden, confirmed password."""
    with _session() as runtime:
        _json(_user_data(runtime.service.add_user(username, _password(confirm=True), role)))


@user_app.command("list")
def user_list() -> None:
    """List local usernames and roles; never print password hashes."""
    with _session() as runtime:
        _json([_user_data(user) for user in runtime.service.list_users()])


@ticket_app.command("create")
def ticket_create(
    name: Annotated[str, typer.Option("--name", "-n")],
    visitor_type: Annotated[str, typer.Option("--type", "-t")],
    valid_from: Annotated[str, typer.Option("--from", "-f")],
    valid_until: Annotated[str, typer.Option("--until", "-u")],
    usage: Annotated[UsageType, typer.Option("--usage")],
    actor: Actor,
    timezone: Annotated[str | None, typer.Option("--tz")] = None,
) -> None:
    """Issue a ticket using ISO datetimes (naive inputs use --tz or TIQR_DEFAULT_TZ)."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        zone = timezone or runtime.settings.default_tz
        ticket = runtime.service.create_ticket(
            user,
            visitor_name=name,
            visitor_type=visitor_type,
            valid_from=parse_input_datetime(valid_from, zone),
            valid_until=parse_input_datetime(valid_until, zone),
            usage_type=usage,
        )
        _json(runtime.ticket_data(ticket))


@ticket_app.command("list")
def ticket_list(
    actor: Actor, state: Annotated[TicketState | None, typer.Option("--state")] = None
) -> None:
    """List the tickets visible to the authenticated actor."""
    with _session() as runtime:
        tickets = runtime.service.list_tickets(runtime.authenticate(actor), state=state)
        tickets.sort(key=lambda ticket: (ticket.readable_serial, str(ticket.id)))
        _json([runtime.ticket_data(ticket) for ticket in tickets])


@ticket_app.command("save")
def ticket_save(ticket_id: Annotated[UUID, typer.Argument()], actor: Actor) -> None:
    """Render a PDF file only; no printer or print queue is used."""
    with _session() as runtime:
        path = runtime.service.print_ticket(
            runtime.authenticate(actor),
            ticket_id,
            output_dir=runtime.settings.output_dir,
            timezone=runtime.settings.default_tz,
        )
        typer.echo(str(path))


@ticket_app.command("print")
def ticket_print(ticket_id: Annotated[UUID, typer.Argument()], actor: Actor) -> None:
    """Save the PDF, then send it to the default printer; a failed print leaves the count alone."""
    from tiqr.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    def render_and_print(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
        path = render_pdf(ticket, output_dir, timezone)
        _send_to_printer(path)
        return path

    with _session() as runtime:
        path = runtime.service.print_ticket(
            runtime.authenticate(actor),
            ticket_id,
            output_dir=runtime.settings.output_dir,
            timezone=runtime.settings.default_tz,
            renderer=render_and_print,
        )
        typer.echo(f"Sent to the default printer: {path}")


@ticket_app.command("assign")
def ticket_assign(
    ticket_id: Annotated[UUID, typer.Argument()],
    operator: Annotated[str, typer.Argument()],
    actor: Actor,
) -> None:
    """Assign a ticket to an operator username."""
    with _session() as runtime:
        ticket = runtime.service.assign_ticket(runtime.authenticate(actor), ticket_id, operator)
        _json(runtime.ticket_data(ticket))


@app.command()
def sync(actor: Actor) -> None:
    """Synchronize access events."""
    with _session() as runtime:
        count = runtime.service.sync(runtime.authenticate(actor))
        typer.echo(f"Synced {count} events")


@app.command()
def cleanup(actor: Actor) -> None:
    """Remove expired remote registrations through the domain service."""
    with _session() as runtime:
        count = runtime.service.cleanup(runtime.authenticate(actor))
        typer.echo(f"Removed {count} tickets")


@app.command()
def stats(actor: Actor) -> None:
    """Show ticket, access and PDF rendering totals."""
    with _session() as runtime:
        _json(runtime.service.stats(runtime.authenticate(actor)))
