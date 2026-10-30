import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from tests.conftest import _vendor
from tiqr.api import server as api_server
from tiqr.cli import commands as cli
from tiqr.core import runtime as core_runtime
from tiqr.core.biostar import BioStarError
from tiqr.core.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.core.license import build_request_code, parse_request_code
from tiqr.core.models import LicenseRecord, RawEvent, Role
from tiqr.core.repository import _MIGRATIONS, SQLiteRepository
from tiqr.core.service import TicketService

NOW = datetime(2030, 1, 1, 8, tzinfo=UTC)
PASSWORD = "correct horse battery staple"
runner = CliRunner()


def vendor_key(license_pair, kind="standard", days=365):
    """A key for this machine, signed as the vendor tool does, issued at the suite's clock."""
    vendor = _vendor()
    request = parse_request_code(build_request_code("trial" if kind == "trial" else "standard"))
    payload = vendor.build_payload(request, kind=kind, licensed_to="Acme", days=days, now=NOW)
    return vendor.sign_license(payload, license_pair[0])


@pytest.fixture
def unlicensed(monkeypatch):
    monkeypatch.setenv("TIQR_TEST_UNLICENSED", "1")


@pytest.fixture
def cli_env(tmp_path, monkeypatch, license_pair, project_root):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "cli-suite-unique-signing-key")
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "Asia/Baku")
    registrar = InMemoryRegistrar()
    events = InMemoryEventSource()

    def service(repository, secret_key, **kwargs):
        # Every command is gated, so the suite starts licensed unless a test asks otherwise.
        if not os.environ.get("TIQR_TEST_UNLICENSED") and repository.active_license() is None:
            repository.activate_license(
                LicenseRecord(vendor_key(license_pair), NOW, NOW + timedelta(days=365), "Acme")
            )
        return TicketService(
            repository,
            secret_key,
            registrar=registrar,
            event_source=events,
            clock=lambda: NOW,
            license_public_key=license_pair[1],
        )

    monkeypatch.setattr(core_runtime, "TicketService", service)
    # Never let tests write the real .env.local.
    monkeypatch.setattr(cli, "provision_secret", lambda: False)
    monkeypatch.setattr(cli, "discard_secret", lambda: False)
    monkeypatch.setattr(cli, "discard_access_group_id", lambda: False)
    return tmp_path, registrar, events


def invoke(args, password=PASSWORD):
    return runner.invoke(cli.app, args, input=password + "\n")


def strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def add_user(username, role):
    result = runner.invoke(
        cli.app, ["user", "add", username, "--role", role], input=f"{PASSWORD}\n{PASSWORD}\n"
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output[result.output.index("{") :])


def create_ticket(actor="admin", **options):
    args = [
        "ticket",
        "create",
        "--name",
        "Əli Иванов",
        "--type",
        "Visitor",
        "--from",
        options.get("start", "2030-01-01T12:00"),
        "--until",
        options.get("end", "2030-01-01T14:00"),
        "--usage",
        "multi_use",
        "--as",
        actor,
    ]
    if "tz" in options:
        args += ["--tz", options["tz"]]
    return invoke(args)


def output_json(result):
    assert result.exit_code == 0, result.output
    output = result.output
    start = min(index for index in (output.find("{"), output.find("[")) if index >= 0)
    return json.loads(output[start:])


def test_all_commands_use_core_fakes(cli_env):
    directory, registrar, events = cli_env
    assert invoke(["setup"]).exit_code == 0
    assert invoke(["setup"]).exit_code == 0
    admin = add_user("admin", "admin")
    add_user("manager", "manager")
    operator = add_user("operator", "operator")
    users_result = invoke(["user", "list"])
    users = output_json(users_result)
    assert [user["username"] for user in users] == ["admin", "manager", "operator"]
    assert "password_hash" not in users_result.output
    assert "$argon2" not in users_result.output
    assert PASSWORD not in users_result.output

    created = output_json(create_ticket())
    ticket_id = created["id"]
    assert UUID(ticket_id)
    assert created["valid_from"] == "2030-01-01T12:00:00+04:00"
    assert ticket_id in registrar.tickets
    tickets = output_json(invoke(["ticket", "list", "--state", "issued", "--as", "admin"]))
    assert [ticket["id"] for ticket in tickets] == [ticket_id]
    assigned = output_json(invoke(["ticket", "assign", ticket_id, "operator", "--as", "manager"]))
    assert assigned["assigned_operator"] == operator["id"]
    saved = invoke(["ticket", "save", ticket_id, "--as", "operator"])
    assert saved.exit_code == 0, saved.output
    destination = directory / "out" / f"{ticket_id}.pdf"
    assert str(destination) in saved.output
    assert destination.read_bytes().startswith(b"%PDF-")

    events.events.append(RawEvent("scan-1", ticket_id, NOW, True))
    synced = invoke(["sync", "--as", "manager"])
    assert synced.exit_code == 0, synced.output
    assert "1" in synced.output
    stats = output_json(invoke(["stats", "--as", "admin"]))
    counts = {"issued": 0, "passed": 1, "expired": 0, "total": 1}
    assert stats == {
        **counts,
        "ticket_types": {"": counts},
        "visitor_types": {"Visitor": {**counts, "ticket_types": {"": counts}}},
    }
    dated = ["stats", "--since", "2000-01-01", "--until", "2999-12-31", "--as", "admin"]
    assert output_json(invoke(dated))["total"] == 1
    assert output_json(invoke(["stats", "--since", "2999-01-01", "--as", "admin"]))["total"] == 0
    assert invoke(["stats", "--since", "01.01.2000", "--as", "admin"]).exit_code == 2
    cleanup = invoke(["cleanup", "--as", "manager"])
    assert cleanup.exit_code == 0, cleanup.output
    assert "0" in cleanup.output
    assert admin["role"] == Role.ADMIN


@pytest.mark.parametrize(
    "args",
    [
        ["ticket", "list"],
        ["ticket", "create"],
        ["ticket", "save", str(uuid4())],
        ["ticket", "assign", str(uuid4()), "operator"],
        ["sync"],
        ["cleanup"],
        ["stats"],
    ],
)
def test_actor_is_required(cli_env, args):
    result = invoke(args)
    assert result.exit_code != 0
    assert "Missing option" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["ticket", "list", "--as", "admin"],
        ["ticket", "save", str(uuid4()), "--as", "admin"],
        ["ticket", "assign", str(uuid4()), "operator", "--as", "admin"],
        [
            "ticket",
            "create",
            "--name",
            "Guest",
            "--type",
            "Guest",
            "--from",
            "2030-01-01T12:00",
            "--until",
            "2030-01-01T14:00",
            "--usage",
            "one_time",
            "--as",
            "admin",
        ],
        ["sync", "--as", "admin"],
        ["cleanup", "--as", "admin"],
        ["stats", "--as", "admin"],
    ],
)
def test_each_actor_command_authenticates_and_hides_password(cli_env, monkeypatch, args):
    add_user("admin", "admin")
    attempts = []
    original = TicketService.authenticate

    def authenticate(self, username, password):
        attempts.append((username, password))
        return original(self, username, password)

    monkeypatch.setattr(TicketService, "authenticate", authenticate)
    result = invoke(args, "incorrect-password")
    assert result.exit_code == 1
    assert attempts == [("admin", "incorrect-password")]
    assert "Password" in result.output
    assert "incorrect-password" not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("password", ["", "   "])
def test_empty_actor_password_rejected_before_authentication(cli_env, monkeypatch, password):
    def forbidden(*args):
        pytest.fail("Empty passwords must not reach authentication")

    monkeypatch.setattr(TicketService, "authenticate", forbidden)
    result = invoke(["stats", "--as", "admin"], password)
    assert result.exit_code == 1
    assert "must not be empty" in result.output


def test_recent_login_skips_the_prompt_for_the_same_user(cli_env, monkeypatch):
    add_user("admin", "admin")
    assert invoke(["stats", "--as", "admin"]).exit_code == 0

    def forbidden(*args):
        pytest.fail("A recent login must not prompt again")

    monkeypatch.setattr(TicketService, "authenticate", forbidden)
    assert runner.invoke(cli.app, ["stats", "--as", "admin"], input="").exit_code == 0


def test_recent_login_lasts_five_minutes(cli_env, monkeypatch):
    add_user("admin", "admin")
    assert invoke(["stats", "--as", "admin"]).exit_code == 0

    last_moment = NOW + timedelta(minutes=5) - timedelta(seconds=1)
    monkeypatch.setattr(TicketService, "_now", lambda self: last_moment)
    assert runner.invoke(cli.app, ["stats", "--as", "admin"], input="").exit_code == 0

    monkeypatch.setattr(TicketService, "_now", lambda self: last_moment + timedelta(seconds=1))
    result = invoke(["stats", "--as", "admin"], "incorrect-password")
    assert result.exit_code == 1
    assert "Password" in result.output


def test_recent_login_does_not_carry_over_to_another_user(cli_env):
    add_user("admin", "admin")
    add_user("manager", "manager")
    assert invoke(["stats", "--as", "admin"]).exit_code == 0
    result = invoke(["stats", "--as", "manager"], "incorrect-password")
    assert result.exit_code == 1
    assert "Password" in result.output


def test_recent_login_file_holds_no_password_and_is_owner_only(cli_env):
    tmp_path, _, _ = cli_env
    add_user("admin", "admin")
    assert invoke(["stats", "--as", "admin"]).exit_code == 0
    path = tmp_path / ".tiqr-session.json"
    assert PASSWORD not in path.read_text(encoding="utf-8")
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_tampered_recent_login_asks_for_the_password(cli_env):
    tmp_path, _, _ = cli_env
    add_user("admin", "admin")
    assert invoke(["stats", "--as", "admin"]).exit_code == 0
    path = tmp_path / ".tiqr-session.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] += 3600
    path.write_text(json.dumps(data), encoding="utf-8")
    result = invoke(["stats", "--as", "admin"], "incorrect-password")
    assert result.exit_code == 1
    assert "Password" in result.output


@pytest.mark.parametrize("password", ["", "   "])
def test_bootstrap_rejects_empty_confirmed_password(cli_env, password):
    result = runner.invoke(
        cli.app, ["user", "add", "admin", "--role", "admin"], input=f"{password}\n{password}\n"
    )
    assert result.exit_code == 1
    assert "must not be empty" in result.output
    assert output_json(invoke(["user", "list"])) == []


def test_password_confirmation_and_roles(cli_env):
    mismatch = runner.invoke(
        cli.app, ["user", "add", "admin", "--role", "admin"], input="first\nsecond\n"
    )
    assert mismatch.exit_code != 0
    invalid = invoke(["user", "add", "admin", "--role", "superuser"])
    assert invalid.exit_code != 0
    assert "superuser" in invalid.output
    assert output_json(invoke(["user", "list"])) == []


def test_permissions_are_enforced_by_service(cli_env):
    add_user("admin", "admin")
    add_user("operator", "operator")
    ticket_id = output_json(create_ticket())["id"]
    result = invoke(["ticket", "save", ticket_id, "--as", "operator"])
    assert result.exit_code == 1
    assert not (cli_env[0] / "out" / f"{ticket_id}.pdf").exists()
    assert invoke(["stats", "--as", "operator"]).exit_code == 1
    assert invoke(["ticket", "assign", ticket_id, "operator", "--as", "operator"]).exit_code == 1
    own = output_json(create_ticket("operator"))
    visible = output_json(invoke(["ticket", "list", "--as", "operator"]))
    assert [ticket["id"] for ticket in visible] == [own["id"]]


@pytest.mark.parametrize(
    ("start", "end", "tz"),
    [
        ("2030-01-01", "2030-01-02", "Asia/Baku"),
        ("bad-date", "2030-01-01T14:00", "Asia/Baku"),
        ("2030-01-01T15:00", "2030-01-01T14:00", "Asia/Baku"),
        ("2030-01-01T12:00", "2030-01-01T14:00", "Invalid/Zone"),
        ("2024-03-10T02:30", "2024-03-10T04:00", "America/New_York"),
        ("2024-11-03T01:30", "2024-11-03T04:00", "America/New_York"),
    ],
)
def test_invalid_dates_do_not_issue_ticket(cli_env, start, end, tz):
    add_user("admin", "admin")
    result = create_ticket(start=start, end=end, tz=tz)
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert output_json(invoke(["ticket", "list", "--as", "admin"])) == []
    assert cli_env[1].tickets == {}


@pytest.mark.parametrize(
    ("text", "timezone", "expected"),
    [
        ("2030-01-01T12:00", "Asia/Baku", datetime(2030, 1, 1, 8, tzinfo=UTC)),
        (
            "2030-01-01T12:00:01.123456+05:30",
            "Asia/Baku",
            datetime(2030, 1, 1, 6, 30, 1, 123456, tzinfo=UTC),
        ),
        ("2024-11-03T01:30-04:00", "America/New_York", datetime(2024, 11, 3, 5, 30, tzinfo=UTC)),
        ("2024-11-03T01:30-05:00", "America/New_York", datetime(2024, 11, 3, 6, 30, tzinfo=UTC)),
        ("2024-03-10T02:30-05:00", "America/New_York", datetime(2024, 3, 10, 7, 30, tzinfo=UTC)),
        ("2024-04-07T01:45+11:00", "Australia/Lord_Howe", datetime(2024, 4, 6, 14, 45, tzinfo=UTC)),
        ("2030-01-01T08:00Z", "Asia/Baku", NOW),
    ],
)
def test_datetime_parser_normalizes_utc(text, timezone, expected):
    result = cli.parse_input_datetime(text, timezone)
    assert result == expected
    assert result.tzinfo is UTC


@pytest.mark.parametrize(
    ("text", "timezone"),
    [
        ("2030-01-01", "Asia/Baku"),
        ("20300101", "Asia/Baku"),
        ("not a date", "Asia/Baku"),
        ("2030-01-01T12:00", "No/SuchZone"),
        ("2024-11-03T01:30", "America/New_York"),
        ("2024-03-10T02:30", "America/New_York"),
        ("2024-04-07T01:45", "Australia/Lord_Howe"),
        ("2024-10-06T02:15", "Australia/Lord_Howe"),
    ],
)
def test_datetime_parser_rejects_invalid_local_times(text, timezone):
    with pytest.raises(ValueError):
        cli.parse_input_datetime(text, timezone)


def test_help_without_secret_and_placeholder_refusal(cli_env, monkeypatch):
    for value in (None, "change-me-now", "placeholder", "   "):
        if value is None:
            monkeypatch.delenv("TIQR_SECRET_KEY", raising=False)
        else:
            monkeypatch.setenv("TIQR_SECRET_KEY", value)
        for args in (
            ["--help"],
            ["ticket", "--help"],
            ["ticket", "create", "--help"],
            ["user", "add", "--help"],
        ):
            help_result = invoke(args)
            assert help_result.exit_code == 0, help_result.output
        result = invoke(["setup"])
        assert result.exit_code == 1
        assert "TIQR_SECRET_KEY" in result.output


@pytest.mark.parametrize("args", [["-h"], ["ticket", "-h"], ["ticket", "create", "-h"]])
def test_short_help_flag(cli_env, args):
    result = invoke(args)
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_short_option_aliases_match_long_forms(cli_env):
    assert invoke(["setup"]).exit_code == 0
    add_user("admin", "admin")
    created = output_json(
        invoke(
            [
                "ticket",
                "create",
                "-n",
                "Guest",
                "-t",
                "Visitor",
                "-f",
                "2030-01-01T12:00",
                "-u",
                "2030-01-01T14:00",
                "--usage",
                "one_time",
                "-a",
                "admin",
            ]
        )
    )
    assert created["visitor_name"] == "Guest"
    assert created["visitor_type"] == "Visitor"
    listed = output_json(invoke(["ticket", "list", "-a", "admin"]))
    assert [ticket["id"] for ticket in listed] == [created["id"]]


def test_old_database_refused_and_connection_closed(cli_env, monkeypatch):
    directory = cli_env[0]
    with sqlite3.connect(directory / "tiqr.db") as connection:
        connection.execute("CREATE TABLE guests (id INTEGER)")
    closed = []
    original = SQLiteRepository.close

    def close(self):
        closed.append(self)
        original(self)

    monkeypatch.setattr(SQLiteRepository, "close", close)
    result = invoke(["setup"])
    assert result.exit_code == 1
    assert "Reference application database" in result.output
    assert len(closed) == 1


def test_repository_closed_on_command_failure(cli_env, monkeypatch):
    closed = []
    original = SQLiteRepository.close

    def close(self):
        closed.append(self)
        original(self)

    monkeypatch.setattr(SQLiteRepository, "close", close)
    assert invoke(["stats", "--as", "missing"]).exit_code == 1
    assert len(closed) == 1


def test_duplicate_users_are_friendly_errors(cli_env):
    add_user("admin", "admin")
    result = runner.invoke(
        cli.app, ["user", "add", "admin", "--role", "admin"], input=f"{PASSWORD}\n{PASSWORD}\n"
    )
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            BioStarError("invalid access group", code="1234", http_status=400),
            "invalid access group (BioStar code 1234, HTTP 400)",
        ),
        (BioStarError("transport failed"), "transport failed"),
        (BioStarError("HTTP failed", http_status=500), "HTTP failed (HTTP 500)"),
        (ValueError("plain"), "plain"),
    ],
)
def test_error_output_names_biostar_code_and_status(error, expected):
    assert cli._describe(error) == expected


@pytest.mark.parametrize("option", ["--name", "--type", "--from", "--until", "--usage", "--as"])
def test_each_create_option_required(cli_env, option):
    args = [
        "ticket",
        "create",
        "--name",
        "Guest",
        "--type",
        "Visitor",
        "--from",
        "2030-01-01T12:00",
        "--until",
        "2030-01-01T14:00",
        "--usage",
        "one_time",
        "--as",
        "admin",
    ]
    index = args.index(option)
    del args[index : index + 2]
    result = invoke(args)
    assert result.exit_code == 2
    assert option in strip_ansi(result.output)
    assert "Missing option" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["ticket", "list", "--state", "unknown", "--as", "admin"],
        ["ticket", "save", "not-a-uuid", "--as", "admin"],
        [
            "ticket",
            "create",
            "--name",
            "Guest",
            "--type",
            "Visitor",
            "--from",
            "2030-01-01T12:00",
            "--until",
            "2030-01-01T14:00",
            "--usage",
            "forever",
            "--as",
            "admin",
        ],
    ],
)
def test_invalid_cli_types_are_rejected(cli_env, args):
    result = invoke(args)
    assert result.exit_code == 2
    assert "Invalid value" in result.output


@pytest.mark.parametrize("fail_construction", [False, True])
def test_biostar_adapters_selected_and_resources_closed(cli_env, monkeypatch, fail_construction):
    for key, value in {
        "BASE_URL": "https://biostar.example/api",
        "USERNAME": "remote-user",
        "PASSWORD": "remote-password",
        "DEVICE_IDS": "1",
        "ACCESS_GROUP_ID": "2",
    }.items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", value)
    observed = {}

    class Client:
        def __init__(self, settings):
            observed["settings"] = settings
            observed["client"] = self

        def close(self):
            observed["client_closed"] = True

    def registrar(client, repository):
        assert client is observed["client"]
        observed["repository"] = repository
        return cli_env[1]

    def event_source(client, repository):
        assert client is observed["client"]
        assert repository is observed["repository"]
        return cli_env[2]

    def service(repository, secret_key, **kwargs):
        assert kwargs == {"registrar": cli_env[1], "event_source": cli_env[2], "prefix": "TQR"}
        if fail_construction:
            raise RuntimeError("adapter startup failure")
        return TicketService(repository, secret_key, **kwargs, clock=lambda: NOW)

    monkeypatch.setattr(core_runtime, "BioStarClient", Client)
    monkeypatch.setattr(core_runtime, "BioStarXRegistrar", registrar)
    monkeypatch.setattr(core_runtime, "BioStarXEventSource", event_source)
    monkeypatch.setattr(core_runtime, "TicketService", service)
    result = invoke(["user", "list"])
    assert result.exit_code == (1 if fail_construction else 0), result.output
    assert observed["settings"].username == "remote-user"
    assert observed["client_closed"]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed["repository"].list_users()


def test_no_biostar_client_without_settings(cli_env, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("BioStar client must not be constructed without BioStar settings")

    monkeypatch.setattr(cli, "BioStarClient", forbidden)
    monkeypatch.setattr(core_runtime, "BioStarClient", forbidden)
    assert invoke(["setup"]).exit_code == 0
    assert invoke(["user", "list"]).exit_code == 0


def test_setup_provisions_the_tiqr_access_group_when_biostar_is_configured(cli_env, monkeypatch):
    for key, value in {
        "BASE_URL": "https://biostar.example",
        "USERNAME": "remote-user",
        "PASSWORD": "remote-password",
        "DEVICE_IDS": "1,2",
    }.items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", value)
    observed = {}

    class Client:
        def __init__(self, settings):
            observed["devices"] = settings.device_ids

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            observed["closed"] = True

    class Provisioner:
        def __init__(self, client):
            assert isinstance(client, Client)

        def ensure_access(self):
            return "30"

    monkeypatch.setattr(cli, "BioStarClient", Client)
    monkeypatch.setattr(cli, "BioStarXProvisioner", Provisioner)
    result = runner.invoke(cli.app, ["setup"])
    assert result.exit_code == 0, result.output
    assert "access group TiQR AG ready: id 30" in result.output
    assert observed == {"devices": ("1", "2"), "closed": True}


def test_reset_deletes_the_database_so_setup_starts_fresh(cli_env):
    directory, _, _ = cli_env
    assert invoke(["setup"]).exit_code == 0
    add_user("admin", "admin")
    database = directory / "tiqr.db"
    sidecar = directory / "tiqr.db-wal"
    sidecar.write_bytes(b"")

    result = runner.invoke(cli.app, ["reset"], input="y\n")

    assert result.exit_code == 0, result.output
    assert not database.exists()
    assert not sidecar.exists()
    assert invoke(["setup"]).exit_code == 0
    assert output_json(invoke(["user", "list"])) == []


def test_reset_aborts_without_confirmation(cli_env):
    directory, _, _ = cli_env
    assert invoke(["setup"]).exit_code == 0

    result = runner.invoke(cli.app, ["reset"], input="n\n")

    assert result.exit_code != 0
    assert (directory / "tiqr.db").exists()


def test_reset_yes_works_on_a_fresh_checkout(cli_env):
    result = runner.invoke(cli.app, ["reset", "--yes"])

    assert result.exit_code == 0, result.output


def issued_ticket_id():
    assert invoke(["setup"]).exit_code == 0
    add_user("admin", "admin")
    return output_json(create_ticket())["id"]


def test_ticket_print_saves_pdf_and_sends_it_to_printer(cli_env, monkeypatch):
    directory, _, _ = cli_env
    ticket_id = issued_ticket_id()
    sent = []
    monkeypatch.setattr(cli, "send_to_printer", sent.append)

    result = invoke(["ticket", "print", ticket_id, "--as", "admin"])

    destination = directory / "out" / f"{ticket_id}.pdf"
    assert result.exit_code == 0, result.output
    assert sent == [destination]
    assert destination.read_bytes().startswith(b"%PDF-")


def test_ticket_print_failure_keeps_print_count(cli_env, monkeypatch):
    ticket_id = issued_ticket_id()

    def fail(path):
        raise RuntimeError("Printing failed: no default destination")

    monkeypatch.setattr(cli, "send_to_printer", fail)

    result = invoke(["ticket", "print", ticket_id, "--as", "admin"])

    assert result.exit_code == 1
    assert "no default destination" in result.output
    assert output_json(invoke(["ticket", "list", "--as", "admin"]))[0]["print_count"] == 0


def write_v1_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(";\n".join((*_MIGRATIONS[0], "PRAGMA user_version = 1;")))


def test_old_schema_needs_setup_which_upgrades_it(cli_env):
    directory, _, _ = cli_env
    write_v1_database(directory / "tiqr.db")
    refused = invoke(["user", "list"])
    assert refused.exit_code == 1
    assert "out of date" in refused.output
    assert invoke(["setup"]).exit_code == 0
    assert invoke(["user", "list"]).exit_code == 0


def test_serve_checks_settings_then_runs_the_server(cli_env, monkeypatch):
    directory, _, _ = cli_env
    started = []
    monkeypatch.setattr(api_server, "run", started.append)
    assert invoke(["serve"]).exit_code == 0
    assert invoke(["serve", "--dev", "--port", "8123"]).exit_code == 0
    plain, dev = started
    # Plain HTTP on 7102 unless a certificate is configured.
    assert (plain.host, plain.port, plain.dev, plain.secure) == ("127.0.0.1", 7102, False, False)
    assert (dev.port, dev.dev) == (8123, True)
    assert (directory / "tiqr.db").exists()


@pytest.mark.parametrize(
    ("args", "message"),
    [(["serve"], "out of date"), (["serve", "--dev", "--host", "10.0.0.5"], "loopback")],
)
def test_serve_stops_before_listening(cli_env, monkeypatch, args, message):
    directory, _, _ = cli_env
    write_v1_database(directory / "tiqr.db")
    monkeypatch.setattr(api_server, "run", lambda config: pytest.fail("the server started"))
    result = invoke(args)
    assert result.exit_code == 1
    assert message in result.output


def test_user_role_deactivate_activate_and_password(cli_env):
    add_user("admin", "admin")
    add_user("operator", "operator")

    promoted = output_json(invoke(["user", "role", "operator", "manager"]))
    assert promoted["role"] == "manager"
    deactivated = output_json(invoke(["user", "deactivate", "operator"]))
    assert deactivated["active"] is False
    refused = invoke(["stats", "--as", "operator"])
    assert refused.exit_code == 1
    assert "deactivated" in refused.output
    assert output_json(invoke(["user", "activate", "operator"]))["active"] is True

    reset = runner.invoke(
        cli.app, ["user", "password", "operator"], input="new-password-1\nnew-password-1\n"
    )
    assert reset.exit_code == 0, reset.output
    assert "new-password-1" not in reset.output
    # The cached CLI login from before the reset no longer stands in for the password.
    assert invoke(["stats", "--as", "operator"]).exit_code == 1
    assert invoke(["stats", "--as", "operator"], password="new-password-1").exit_code == 0
    users = {user["username"]: user for user in output_json(invoke(["user", "list"]))}
    assert users["operator"] == promoted | {"active": True}


def test_user_commands_keep_the_last_admin_and_name_unknown_users(cli_env):
    add_user("admin", "admin")
    for args in (["user", "deactivate", "admin"], ["user", "role", "admin", "operator"]):
        result = invoke(args)
        assert result.exit_code == 1
        assert "last active admin" in result.output
    missing = invoke(["user", "deactivate", "nobody"])
    assert missing.exit_code == 1
    assert "User not found" in missing.output


def test_unlicensed_commands_are_refused_until_activated(cli_env, unlicensed, license_pair):
    assert invoke(["setup"]).exit_code == 0
    add_user("admin", "admin")
    refused = create_ticket()
    assert refused.exit_code == 1
    assert "A valid license is required (none)" in refused.output
    assert output_json(invoke(["license", "status"]))["state"] == "none"

    key = vendor_key(license_pair)
    activated = invoke(["license", "activate", key, "--as", "admin"])
    assert activated.exit_code == 0, activated.output
    assert "License active for Acme" in activated.output
    status = output_json(invoke(["license", "status"]))
    assert status["state"] == "active"
    assert create_ticket().exit_code == 0


def test_license_activate_takes_a_file_and_refuses_bad_keys(cli_env, unlicensed, license_pair):
    directory = cli_env[0]
    assert invoke(["setup"]).exit_code == 0
    add_user("admin", "admin")
    key_file = directory / "license.key"
    key_file.write_text(vendor_key(license_pair) + "\n")
    assert invoke(["license", "activate", "--file", str(key_file), "--as", "admin"]).exit_code == 0
    bad = invoke(["license", "activate", "not-a-key", "--as", "admin"])
    assert bad.exit_code == 1
    assert "not valid for this product" in bad.output
    both = invoke(["license", "activate", "key", "--file", str(key_file), "--as", "admin"])
    assert both.exit_code == 1
    # A refused key left the active license in place
    assert output_json(invoke(["license", "status"]))["state"] == "active"


def test_license_request_code_needs_no_account(cli_env, unlicensed):
    result = runner.invoke(cli.app, ["license", "request-code"])
    assert result.exit_code == 0
    request = parse_request_code(result.stdout.strip())
    assert request.request_type == "standard"


def test_selftest_renders_a_badge_without_setup_or_license(cli_env, unlicensed):
    result = runner.invoke(cli.app, ["selftest"])
    assert result.exit_code == 0, result.output
    assert "Self-test passed" in result.output
