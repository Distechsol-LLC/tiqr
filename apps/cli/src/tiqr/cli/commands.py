import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import typer

from tiqr.cli.installer import (
    is_administrator,
    is_installed,
    lan_address,
    open_firewall,
    register_service,
    uninstall_service,
    wait_until_healthy,
)
from tiqr.core.auth import AuthenticationError, Session
from tiqr.core.biostar import ACCESS_GROUP_NAME, BioStarClient, BioStarError, BioStarXProvisioner
from tiqr.core.license import build_request_code
from tiqr.core.localtime import parse_input_datetime
from tiqr.core.models import ApiKey, Role, Ticket, TicketState, UsageType, User
from tiqr.core.printer import send_to_printer
from tiqr.core.repository import SQLiteRepository
from tiqr.core.runtime import open_service
from tiqr.core.service import SCOPES, IdempotencyConflictError, TicketService
from tiqr.core.settings import (
    BRANDING_FILE,
    LOCAL_ENV_FILE,
    Settings,
    branding_path,
    database_path,
    discard_access_group_id,
    discard_secret,
    load_branding,
    provision_secret,
    session_path,
    write_local_settings,
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
    "external_code",
    "event_session",
)
_DB_SUFFIXES = ("-journal", "-wal", "-shm")
# Set by the install scripts once the user has agreed to a reinstall, so it is not asked twice.
REINSTALL_CONFIRMED_ENV = "TIQR_REINSTALL_CONFIRMED"

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
key_app = typer.Typer(no_args_is_help=True, help="Service API keys for the web API (admin).")
license_app = typer.Typer(no_args_is_help=True, help="Request and activate this install's license.")
app.add_typer(user_app, name="user")
app.add_typer(license_app, name="license")
app.add_typer(ticket_app, name="ticket")
app.add_typer(key_app, name="key")


@app.callback()
def _copyright() -> None:
    # Copyright Notice
    typer.echo("© 2026 Distechsol LLC", err=True)


Actor = Annotated[str, typer.Option("--as", "-a")]


@dataclass(frozen=True, slots=True)
class _Runtime:
    settings: Settings
    service: TicketService

    def authenticate(self, username: str, *, licensed: bool = True) -> User:
        user = self._sign_in(username)
        if licensed:
            # After the password, so only a signed-in account learns the license state.
            self.service.require_license()
        return user

    def _sign_in(self, username: str) -> User:
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


@app.command()
def selftest() -> None:
    """Render a sample badge in a temporary folder, to prove the program's assets are intact.

    Touches no ticket, account or setting, and needs neither setup nor a license.
    """
    # ReportLab is slow to import and only this command and printing need it.
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415

    with _errors(), tempfile.TemporaryDirectory() as folder:
        start = datetime(2030, 1, 1, 8, tzinfo=UTC)
        owner = uuid4()
        sample = Ticket(
            id=uuid4(),
            external_id=None,
            qr_payload="TQR:300101-00001:ABCDEFGHIJKLMNO",
            readable_serial="TQR-300101-00001",
            visitor_name="Sample Visitor",
            visitor_type="Visitor",
            valid_from=start,
            valid_until=start + timedelta(hours=2),
            usage_type=UsageType.MULTI_USE,
            state=TicketState.ISSUED,
            created_by=owner,
            assigned_operator=owner,
            created_at=start,
        )
        pdf = render_pdf(sample, Path(folder), "UTC")
        if not pdf.read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("The sample badge is not a PDF")
    typer.echo("Self-test passed: the badge renders")


def _reinstall_decision(*, service: bool) -> bool:
    """Whether an existing service is replaced; a terminal user who declines stops the install."""
    if not service or not is_installed(Path(sys.executable)):
        return False
    if os.environ.get(REINSTALL_CONFIRMED_ENV):
        return True
    if _interactive() and not typer.confirm(
        "TiQR is already installed. Reinstall it?", default=False
    ):
        typer.echo("Install cancelled; nothing was changed.")
        raise typer.Exit(1)
    return True


def _register(*, reinstall: bool, source: Path) -> None:
    if reinstall:
        uninstall_service(Path(sys.executable))
        typer.echo("Removed the existing TiQR service; registering it again")
    typer.echo(register_service(Path(sys.executable), branding_path().parent, source))


@app.command()
def install(
    *,
    source: Annotated[
        Path | None,
        typer.Option(
            help="Folder holding tiqr_brand.jsonc and WinSW; default: beside the executable."
        ),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(help="Address operators' PCs use; asked for, or this machine's LAN address."),
    ] = None,
    port: Annotated[int | None, typer.Option(help="TCP port; asked for, or 7102.")] = None,
    service: Annotated[
        bool, typer.Option("--service/--no-service", help="Register and start the service.")
    ] = True,
    firewall: Annotated[
        bool, typer.Option("--firewall/--no-firewall", help="Open the port in the host firewall.")
    ] = True,
) -> None:
    """Install TiQR on this machine: branding, address, database, admin, firewall and service.

    Run it from the folder the service will run from, as an administrator (sudo on Linux). The
    executable is registered where it stands, and its folder holds the data. Terminal runs ask for
    the address, port and first admin; scripts take the defaults. Each step can be skipped.
    """
    with _errors():
        if (service or firewall) and not is_administrator():
            raise RuntimeError("tiqr install needs administrator rights (sudo on Linux)")
        if service and not getattr(sys, "frozen", False):
            raise RuntimeError(
                "Service registration needs the packaged executable; use --no-service"
            )
        reinstall = _reinstall_decision(service=service)
        origin_folder = source or _executable_folder()
        origin = origin_folder / BRANDING_FILE
        target = branding_path()
        # The data folder may not exist yet on a first Windows install; the database goes there too.
        target.parent.mkdir(parents=True, exist_ok=True)
        load_branding(origin)
        if origin.resolve() == target.resolve():
            typer.echo(f"{target} is already in place")
        elif target.exists():
            # A reinstall keeps the branding the site has already edited.
            typer.echo(f"Keeping the branding already in {target}")
        else:
            shutil.copyfile(origin, target)
            typer.echo(f"Copied {origin} to {target}")

        host = host or _ask("Address operators' PCs use to reach TiQR", lan_address())
        port = port or _ask("TCP port", 7102)
        if write_local_settings({"TIQR_HOST": host, "TIQR_PORT": str(port)}):
            typer.echo(f"Set TIQR_HOST and TIQR_PORT in {LOCAL_ENV_FILE}")

        setup()
        with SQLiteRepository(Settings.from_env().database_path) as repository:
            has_users = bool(repository.list_users())
        if not has_users:
            if _interactive():
                create_first_admin()
            else:
                typer.echo("No users yet. Next: tiqr user add <username> --role admin")

        if firewall:
            typer.echo(open_firewall(port))
        if service:
            _register(reinstall=reinstall, source=origin_folder)
            wait_until_healthy(host, port)
            typer.echo(f"TiQR is answering on {host}:{port}")
        _license_next_steps(host, port)


def _license_next_steps(host: str, port: int) -> None:
    """Say what is left after install: the program does nothing until a license is activated."""
    with _session() as runtime:
        if runtime.service.license_status().is_valid:
            return
    typer.echo("")
    typer.echo("Last step: activate a license. Send this request code to your vendor:")
    typer.echo(f"  {build_request_code('standard')}")
    typer.echo(
        f"Then paste the key they send back at http://{host}:{port} (License), or run:"
        "\n  tiqr license activate --as <admin> <key>"
    )


def _ask[T](text: str, default: T) -> T:
    """Ask at a terminal; a script takes the default."""
    if _interactive():
        return typer.prompt(text, default=default, type=type(default))
    return default


def _interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def create_first_admin() -> None:
    """Prompt until an admin account exists, or the user cancels."""
    typer.echo("No users yet. Create the first admin account.")
    while True:
        username = typer.prompt("Admin username")
        # A rejected attempt has printed its error; ask again.
        if not app(args=["user", "add", username, "--role", "admin"], standalone_mode=False):
            return


def _executable_folder() -> Path:
    # A frozen build runs from its own folder; a source checkout uses the working directory.
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()


@license_app.command("request-code")
def license_request_code() -> None:
    """Print this machine's request code; send it to the vendor to get a license key."""
    typer.echo(build_request_code("standard"))


@license_app.command("status")
def license_status() -> None:
    """Show the license state, holder and expiry."""
    with _session() as runtime:
        status = runtime.service.license_status()
        _json(
            {
                "state": status.state.value,
                "type": status.type.value if status.type else None,
                "licensed_to": status.licensed_to,
                "expires_at": status.expires_at.isoformat() if status.expires_at else None,
                "days_remaining": status.days_remaining,
                "machine_id": status.machine_id,
            }
        )


@license_app.command("activate")
def license_activate(
    actor: Actor,
    key: Annotated[str | None, typer.Argument(help="The key; or use --file.")] = None,
    file: Annotated[Path | None, typer.Option(help="A file holding the key.")] = None,
) -> None:
    """Store the vendor's license key (admin). A refused key leaves the current license in place."""
    with _errors():
        if (key is None) == (file is None):
            raise ValueError("Give the key as an argument, or --file, but not both")
        license_key = key if key is not None else (file or Path()).read_text(encoding="utf-8")
    with _session() as runtime:
        user = runtime.authenticate(actor, licensed=False)
        status = runtime.service.activate_license(user, license_key)
        expires = status.expires_at.date().isoformat() if status.expires_at else "?"
        typer.echo(f"License active for {status.licensed_to}, until {expires}")


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
def ticket_create(  # noqa: PLR0913, PLR0917 - one option per ticket field
    name: Annotated[str, typer.Option("--name", "-n")],
    visitor_type: Annotated[str, typer.Option("--type", "-t")],
    valid_from: Annotated[str, typer.Option("--from", "-f")],
    valid_until: Annotated[str, typer.Option("--until", "-u")],
    usage: Annotated[UsageType, typer.Option("--usage")],
    actor: Actor,
    timezone: Annotated[str | None, typer.Option("--tz")] = None,
    idempotency_key: Annotated[
        str | None,
        typer.Option(help="Repeat safely: the same key and options return the first ticket."),
    ] = None,
) -> None:
    """Issue a ticket using ISO datetimes (naive inputs use --tz or TIQR_DEFAULT_TZ)."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        zone = timezone or runtime.settings.default_tz
        definition: dict[str, object] = {
            "visitor_name": name,
            "visitor_type": visitor_type,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "usage_type": usage.value,
            "timezone": zone,
        }
        ticket = _create_once(runtime, user, definition, idempotency_key)[0]
        _json(runtime.ticket_data(ticket))


def _create_once(
    runtime: _Runtime, user: User, definition: dict[str, object], key: str | None
) -> tuple[Ticket, bool]:
    """Create a ticket, or return the one this key made; the bool says it was a replay.

    The same key with another definition is refused, as the API does with a 409.
    """
    service = runtime.service

    def create() -> Ticket:
        zone = str(definition["timezone"])
        return service.create_ticket(
            user,
            visitor_name=str(definition["visitor_name"]),
            visitor_type=str(definition["visitor_type"]),
            valid_from=parse_input_datetime(str(definition["valid_from"]), zone),
            valid_until=parse_input_datetime(str(definition["valid_until"]), zone),
            usage_type=UsageType(definition["usage_type"]),
        )

    if key is None:
        return create(), False
    scoped = f"cli:{user.id}:{key}"
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    with service.idempotency_lock:
        stored = service.idempotency_lookup(scoped, digest)
        if stored is not None:
            return service.get_ticket(user, UUID(json.loads(stored.body)["id"])), True
        ticket = create()
        ttl = timedelta(hours=int(os.environ.get("TIQR_IDEMPOTENCY_TTL_HOURS", "24")))
        service.idempotency_store(scoped, digest, 201, json.dumps({"id": str(ticket.id)}), ttl)
        return ticket, False


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
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    with _session() as runtime:
        path = runtime.service.print_ticket(
            runtime.authenticate(actor),
            ticket_id,
            output_dir=runtime.settings.output_dir,
            timezone=runtime.settings.default_tz,
            renderer=partial(render_pdf, title=runtime.settings.app_name),
        )
        typer.echo(str(path))


@ticket_app.command("print")
def ticket_print(ticket_id: Annotated[UUID, typer.Argument()], actor: Actor) -> None:
    """Save the PDF, then send it to the default printer; a failed print leaves the count alone."""
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    with _session() as runtime:
        title = runtime.settings.app_name

        def render_and_print(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
            path = render_pdf(ticket, output_dir, timezone, title=title)
            send_to_printer(path)
            return path

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


@ticket_app.command("revoke")
def ticket_revoke(
    ticket_id: Annotated[UUID, typer.Argument()],
    actor: Actor,
    reason: Annotated[str | None, typer.Option(help="Kept in the audit log.")] = None,
) -> None:
    """Cancel a ticket and remove its BioStar access; revoking a revoked ticket changes nothing."""
    with _session() as runtime:
        ticket = runtime.service.revoke_ticket(runtime.authenticate(actor), ticket_id, reason)
        _json(runtime.ticket_data(ticket))


@ticket_app.command("update")
def ticket_update(
    ticket_id: Annotated[UUID, typer.Argument()],
    actor: Actor,
    valid_from: Annotated[str | None, typer.Option("--from", "-f")] = None,
    valid_until: Annotated[str | None, typer.Option("--until", "-u")] = None,
    timezone: Annotated[str | None, typer.Option("--tz")] = None,
) -> None:
    """Change the validity window, in BioStar too; the end must be after the start."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        zone = timezone or runtime.settings.default_tz
        ticket = runtime.service.update_validity(
            user,
            ticket_id,
            valid_from=parse_input_datetime(valid_from, zone) if valid_from else None,
            valid_until=parse_input_datetime(valid_until, zone) if valid_until else None,
        )
        _json(runtime.ticket_data(ticket))


@ticket_app.command("reissue")
def ticket_reissue(
    ticket_id: Annotated[UUID, typer.Argument()],
    actor: Actor,
    valid_from: Annotated[str | None, typer.Option("--from", "-f")] = None,
    valid_until: Annotated[str | None, typer.Option("--until", "-u")] = None,
    timezone: Annotated[str | None, typer.Option("--tz")] = None,
) -> None:
    """Reissue a ticket in any state, as the same ticket; this is also how it is edited."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        zone = timezone or runtime.settings.default_tz
        ticket = runtime.service.reissue_ticket(
            user,
            ticket_id,
            valid_from=parse_input_datetime(valid_from, zone) if valid_from else None,
            valid_until=parse_input_datetime(valid_until, zone) if valid_until else None,
        )
        _json(runtime.ticket_data(ticket))


@ticket_app.command("audit")
def ticket_audit(ticket_id: Annotated[UUID, typer.Argument()], actor: Actor) -> None:
    """Show every recorded change to a ticket, oldest first (admins and managers)."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        runtime.service.get_ticket(user, ticket_id)
        _json(
            [
                {
                    "occurred_at": entry.occurred_at.isoformat(),
                    "actor": entry.actor,
                    "action": entry.action,
                    "reason": entry.reason,
                    "detail": entry.detail,
                }
                for entry in runtime.service.audit_trail(user, ticket_id)
            ]
        )


@ticket_app.command("batch")
def ticket_batch(
    file: Annotated[
        Path,
        typer.Argument(
            help="JSON list of tickets: visitor_name, visitor_type, valid_from, valid_until, "
            "usage_type, and optionally timezone, idempotency_key."
        ),
    ],
    actor: Actor,
    *,
    atomic: Annotated[
        bool, typer.Option("--atomic", help="All or nothing: undo the created ones on a failure.")
    ] = False,
    idempotency_key: Annotated[
        str | None, typer.Option(help="Item keys without their own become this plus :index.")
    ] = None,
) -> None:
    """Create many tickets with a result for each; exits 1 if any item failed."""
    with _errors():
        items: list[dict[str, object]] = json.loads(file.read_text(encoding="utf-8"))
        if not items:
            raise ValueError("The file must hold a non-empty JSON list of tickets")
        limit = int(os.environ.get("TIQR_BATCH_MAX_SIZE", "100"))
        if len(items) > limit:
            raise ValueError(f"A batch carries at most {limit} tickets")
    with _session() as runtime:
        user = runtime.authenticate(actor)
        results = _run_batch(runtime, user, items, idempotency_key, atomic=atomic)
        _json(
            {
                "atomic": atomic,
                "committed": not (atomic and any(r["status"] == "error" for r in results)),
                "results": results,
            }
        )
    if any(result["status"] in {"error", "rolled_back"} for result in results):
        raise typer.Exit(1)


def _run_batch(
    runtime: _Runtime,
    user: User,
    items: list[dict[str, object]],
    header_key: str | None,
    *,
    atomic: bool,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    created: list[int] = []
    failed = False
    seen: set[str] = set()
    for index, item in enumerate(items):
        if failed:
            results.append({"index": index, "status": "skipped"})
            continue
        try:
            own = item.get("idempotency_key")
            key = str(own) if own else (f"{header_key}:{index}" if header_key else None)
            if key is not None and key in seen:
                raise IdempotencyConflictError("Idempotency key repeated within the batch")  # noqa: TRY301
            definition = {k: v for k, v in item.items() if k != "idempotency_key"}
            definition.setdefault("timezone", runtime.settings.default_tz)
            definition.setdefault("usage_type", UsageType.ONE_TIME.value)
            ticket, replayed = _create_once(runtime, user, definition, key)
        except Exception as exc:  # noqa: BLE001 - becomes this item's result
            results.append({"index": index, "status": "error", "error": _describe(exc)})
            failed = atomic
            continue
        if key is not None:
            seen.add(str(key))
        if not replayed:
            created.append(index)
        results.append(
            {
                "index": index,
                "status": "replayed" if replayed else "created",
                "ticket": runtime.ticket_data(ticket),
            }
        )
    if atomic and failed:
        for index in created:
            ticket_id = UUID(str(results[index]["ticket"]["id"]))  # type: ignore[index]
            try:
                runtime.service.revoke_ticket(user, ticket_id, "Batch undone: an item failed")
                results[index] = {"index": index, "status": "rolled_back", "ticket_id": ticket_id}
            except Exception as exc:  # noqa: BLE001 - reported on the item
                results[index] = {
                    "index": index,
                    "status": "error",
                    "error": f"Rollback failed: {_describe(exc)}",
                }
    return results


def _key_data(key: ApiKey) -> dict[str, object]:
    return {
        "id": key.id,
        "name": key.name,
        "scopes": list(key.scopes),
        "acts_as": key.user_id,
        "created_at": key.created_at.isoformat(),
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "replaced_by": key.replaced_by,
    }


@key_app.command("create")
def key_create(
    name: Annotated[str, typer.Argument()],
    actor: Actor,
    scope: Annotated[
        list[str], typer.Option("--scope", help=f"One or more of: {', '.join(sorted(SCOPES))}.")
    ],
    acts_as: Annotated[str | None, typer.Option(help="Account it acts as; default you.")] = None,
    expires_at: Annotated[
        datetime | None, typer.Option(formats=["%Y-%m-%d"], help="Last day; default never.")
    ] = None,
) -> None:
    """Issue a service API key (admin). The secret is shown once; only its hash is kept."""
    with _session() as runtime:
        user = runtime.authenticate(actor)
        key, secret = runtime.service.create_api_key(
            user,
            name,
            scope,
            acts_as=acts_as,
            expires_at=expires_at.replace(tzinfo=UTC) if expires_at else None,
        )
        _json(_key_data(key) | {"secret": secret})


@key_app.command("list")
def key_list(actor: Actor) -> None:
    """List service keys, without secrets (admin)."""
    with _session() as runtime:
        _json(
            [_key_data(key) for key in runtime.service.list_api_keys(runtime.authenticate(actor))]
        )


@key_app.command("rotate")
def key_rotate(
    key_id: Annotated[UUID, typer.Argument()],
    actor: Actor,
    grace_minutes: Annotated[int, typer.Option(min=0, max=10080)] = 60,
) -> None:
    """Issue a successor key; the old one keeps working for the grace period."""
    with _session() as runtime:
        key, secret = runtime.service.rotate_api_key(
            runtime.authenticate(actor), key_id, timedelta(minutes=grace_minutes)
        )
        _json(_key_data(key) | {"secret": secret})


@key_app.command("revoke")
def key_revoke(key_id: Annotated[UUID, typer.Argument()], actor: Actor) -> None:
    """End a key at once; revoking a revoked key changes nothing."""
    with _session() as runtime:
        _json(_key_data(runtime.service.revoke_api_key(runtime.authenticate(actor), key_id)))


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
