import json
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

import typer

from tiqr.core.auth import AuthenticationError, Session
from tiqr.core.biostar import ACCESS_GROUP_NAME, BioStarClient, BioStarError, BioStarXProvisioner
from tiqr.core.localtime import parse_input_datetime
from tiqr.core.models import Role, Ticket, TicketState, UsageType, User
from tiqr.core.printer import send_to_printer
from tiqr.core.repository import SQLiteRepository
from tiqr.core.runtime import open_service
from tiqr.core.service import TicketService
from tiqr.core.settings import (
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

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="QR ticket administration. Bootstrap commands trust the local OS account.",
)
user_app = typer.Typer(no_args_is_help=True, help="Local, trusted-account user management.")
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
    with _errors():
        settings = Settings.from_env()
        with open_service(settings) as service:
            yield _Runtime(settings, service)


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


def _user_data(user: User) -> dict[str, object]:
    return {"id": user.id, "username": user.username, "role": user.role, "active": user.active}


def _ticket_data(ticket: Ticket, timezone: str) -> dict[str, object]:
    zone = ZoneInfo(timezone)
    data: dict[str, object] = {name: getattr(ticket, name) for name in _TICKET_FIELDS}
    for name in ("valid_from", "valid_until"):
        data[name] = getattr(ticket, name).astimezone(zone).isoformat()
    return data | {"timezone": timezone}


@app.command()
def setup() -> None:
    """Create the signing key and the database, or upgrade the database, and the BioStar group.

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
            repository.initialize(upgrade=True)
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
    """List local usernames, roles and active states; never print password hashes."""
    with _session() as runtime:
        _json([_user_data(user) for user in runtime.service.list_users()])


@user_app.command("role")
def user_role(
    username: Annotated[str, typer.Argument()], role: Annotated[Role, typer.Argument()]
) -> None:
    """Change a user's role; it applies from their next command or request."""
    with _session() as runtime:
        user = runtime.service.find_user(username)
        _json(_user_data(runtime.service.edit_user(user.id, role=role)))


@user_app.command("deactivate")
def user_deactivate(username: Annotated[str, typer.Argument()]) -> None:
    """Stop a user signing in and end their sessions; their tickets and history stay."""
    with _session() as runtime:
        user = runtime.service.find_user(username)
        _json(_user_data(runtime.service.edit_user(user.id, active=False)))


@user_app.command("activate")
def user_activate(username: Annotated[str, typer.Argument()]) -> None:
    """Let a deactivated user sign in again."""
    with _session() as runtime:
        user = runtime.service.find_user(username)
        _json(_user_data(runtime.service.edit_user(user.id, active=True)))


@user_app.command("delete")
def user_delete(username: Annotated[str, typer.Argument()]) -> None:
    """Delete a deactivated user; users with tickets stay, deactivated, to keep the history."""
    with _session() as runtime:
        user = runtime.service.find_user(username)
        runtime.service.remove_user(user.id)
        _json({"deleted": user.username})


@user_app.command("password")
def user_password(username: Annotated[str, typer.Argument()]) -> None:
    """Reset a user's password, prompting for a hidden, confirmed one; ends their sessions."""
    with _session() as runtime:
        user = runtime.service.find_user(username)
        password = _password(confirm=True)
        _json(_user_data(runtime.service.edit_user(user.id, password=password)))


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
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    def render_and_print(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
        path = render_pdf(ticket, output_dir, timezone)
        send_to_printer(path)
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
def stats(
    actor: Actor,
    since: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="First local day, inclusive.")
    ] = None,
    until: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Last local day, inclusive.")
    ] = None,
) -> None:
    """Show ticket, access and PDF rendering totals, for tickets created in a date range."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        _json(
            runtime.service.stats(
                user,
                since=since.date() if since else None,
                until=until.date() if until else None,
                timezone=runtime.settings.default_tz,
            )
        )


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address; default TIQR_HOST.")] = None,
    port: Annotated[int | None, typer.Option(help="Port; default TIQR_PORT.")] = None,
    tls_cert: Annotated[Path | None, typer.Option(help="PEM certificate; TIQR_TLS_CERT.")] = None,
    tls_key: Annotated[Path | None, typer.Option(help="PEM private key; TIQR_TLS_KEY.")] = None,
    *,
    dev: Annotated[
        bool, typer.Option("--dev", help="Loopback only, with the API docs; never production.")
    ] = False,
) -> None:
    """Run the web API and UI, with scheduled sync and cleanup; HTTPS once TLS is configured."""
    # FastAPI and Uvicorn are slow to import and only this command needs them.
    from tiqr.api.config import ServerConfig  # noqa: PLC0415
    from tiqr.api.server import run  # noqa: PLC0415

    with _errors():
        config = ServerConfig.from_env(
            host=host, port=port, tls_cert=tls_cert, tls_key=tls_key, dev=dev
        )
        # Fails here, with a short message, rather than in the server's startup log.
        with _session():
            pass
    run(config)
