import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from tiqr.auth import SESSION_LIFETIME, AuthenticationError, verify_password
from tiqr.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.models import AccessEvent, Outcome, Registration, Role, SyncCursor, UsageType, utc
from tiqr.qr import build_payload, make_serial, signature, validate_prefix, verify_payload
from tiqr.repository import SQLiteRepository
from tiqr.service import TicketService
from tiqr.settings import BioStarSettings, Settings

VECTORS = [
    (1, date(2026, 9, 17), "TQR-260917-00001", "TQR:260917-00001:NNFFGTUWhpXcZ0E"),
    (2, date(2026, 9, 17), "TQR-260917-00002", "TQR:260917-00002:RmCVYb98bnZwOgt"),
    (42, date(2026, 1, 3), "TQR-260103-00042", "TQR:260103-00042:9kkk38wybhZrE6F"),
    (99999, date(2026, 12, 31), "TQR-261231-99999", "TQR:261231-99999:9x_9DUEt8NBP-LL"),
    (7, date(2027, 6, 5), "TQR-270605-00007", "TQR:270605-00007:XaAFgKLrr86iNJM"),
]


@pytest.mark.parametrize(("counter", "when", "serial", "expected"), VECTORS)
def test_vectors_and_32_character_payload(counter, when, serial, expected):
    secret = "demo-secret-key-do-not-use"
    assert make_serial(counter, when) == serial
    payload = build_payload(serial, secret)
    assert len(payload) == 32
    assert payload == expected
    assert verify_payload(payload, secret)
    assert not verify_payload(payload, "wrong-secret")


PREFIX_VECTORS = [
    ("NMK", "NMK-260917-00001", "NMK:260917-00001:1VZ5NWLlB4qbrwu"),
    ("DTS", "DTS-260917-00001", "DTS:260917-00001:vpP8t-SrpuEV6Ed"),
]


@pytest.mark.parametrize(("prefix", "serial", "expected"), PREFIX_VECTORS)
def test_other_prefixes_keep_32_character_payloads(prefix, serial, expected):
    secret = "demo-secret-key-do-not-use"
    assert make_serial(1, date(2026, 9, 17), prefix) == serial
    payload = build_payload(serial, secret, prefix)
    assert len(payload) == 32
    assert payload == expected
    assert verify_payload(payload, secret, prefix)
    assert not verify_payload(payload, secret)


@pytest.mark.parametrize("prefix", ["TQR", "NMK", "DTS", "abc", "1A!", "~~~"])
def test_any_three_printable_ascii_characters_are_accepted(prefix):
    validate_prefix(prefix)


@pytest.mark.parametrize("prefix", ["", "TiQR", "NM", "NMKX", "N-M", "N:M", " NM", "雪雪雪"])
def test_unknown_prefix_is_rejected(prefix):
    with pytest.raises(ValueError, match="Ticket prefix"):
        validate_prefix(prefix)


@pytest.mark.parametrize("bad", [0, -1, 100000])
def test_invalid_sequence(bad):
    with pytest.raises(ValueError):
        make_serial(bad, date(2026, 9, 17))


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "雪",
        "TIQR:260917-00001:雪",
        "hello",
        "TIQR:260917-00001:rF2usad2lWplZp0",
        "TIQR:260917-00001:",
    ],
)
def test_qr_rejects_forgery_without_crashing(bad):
    assert not verify_payload(bad, "secret-for-tests")


def test_qr_signs_no_personal_data_and_detects_tampering(service, accounts, clock):
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Sensitive name",
        visitor_type="Sensitive type",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.ONE_TIME,
    )
    assert len(ticket.qr_payload) == 32
    assert str(ticket.id) not in ticket.qr_payload
    assert "Sensitive" not in ticket.qr_payload
    tampered = ticket.qr_payload.replace("00001", "00002")
    assert not verify_payload(tampered, service.secret_key)


def test_service_issues_tickets_under_the_configured_prefix(repository, accounts, clock):
    service = TicketService(repository, "test-prefix-secret-0123456789", clock=clock, prefix="DTS")
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Visitor",
        visitor_type="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.ONE_TIME,
    )
    assert ticket.readable_serial == "DTS-260917-00001"
    assert ticket.qr_payload.startswith("DTS:260917-00001:")
    assert len(ticket.qr_payload) == 32
    assert verify_payload(ticket.qr_payload, service.secret_key, "DTS")


@pytest.mark.parametrize(
    "serial", ["", "TQR-260917-00001\n", "TQR-260917-0001", "TQR-２６０９１７-00001"]
)
def test_qr_serial_must_match_exact_ascii_format(serial):
    with pytest.raises(ValueError):
        build_payload(serial, "a-secret")


def test_empty_qr_secret_rejected():
    with pytest.raises(ValueError):
        signature("TQR-260917-00001", "")


@pytest.mark.parametrize("password", ["", " ", "\t\n"])
def test_user_add_rejects_empty_password(service, password):
    with pytest.raises(ValueError, match="Password"):
        service.add_user("new", password, Role.ADMIN)
    assert service.repository.user_by_name("new") is None


def test_argon2_authentication_has_no_empty_password_bypass(service, accounts):
    user = accounts["operator"]
    assert user.password_hash.startswith("$argon2id$")
    assert service.authenticate(user.username, "correct-password") == user
    for password in ("", "incorrect"):
        with pytest.raises(AuthenticationError):
            service.authenticate(user.username, password)
    with pytest.raises(AuthenticationError):
        service.authenticate("unknown", "correct-password")


def test_session_resumes_only_until_its_lifetime_ends(service, accounts, clock):
    operator = accounts["operator"]
    session = service.start_session(operator)
    assert session.expires_at == clock.now + SESSION_LIFETIME
    assert service.resume_session(session) == operator
    clock.now = session.expires_at - timedelta(seconds=1)
    assert service.resume_session(session) == operator
    clock.now = session.expires_at
    with pytest.raises(AuthenticationError):
        service.resume_session(session)


def test_session_rejects_forged_and_retargeted_tokens(service, accounts):
    session = service.start_session(accounts["operator"])
    forged = replace(session, token="0" * 64)
    retargeted = replace(session, username=accounts["admin"].username)
    for bad in (forged, retargeted):
        with pytest.raises(AuthenticationError):
            service.resume_session(bad)


def test_add_individual_account_and_reject_duplicate(service):
    user = service.add_user(" new-admin ", "a-long-password", Role.ADMIN)
    assert user.username == "new-admin"
    verify_password(user, "a-long-password")
    assert user in service.list_users()
    with pytest.raises(ValueError, match="exists"):
        service.add_user("new-admin", "different-password", Role.MANAGER)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        " ",
        "secret",
        "placeholder",
        "change-me",
        "change-me-in-production",
        "demo-secret-key-do-not-use",
        "your-secret-key",
        "test-secret-key",
    ],
)
def test_startup_refuses_placeholder_secret(monkeypatch, repository, secret):
    monkeypatch.setenv("TIQR_SECRET_KEY", secret)
    with pytest.raises(ValueError, match="TIQR_SECRET_KEY"):
        Settings.from_env()
    with pytest.raises(ValueError, match="TIQR_SECRET_KEY"):
        TicketService(repository, secret)


def test_default_settings_and_fakes(monkeypatch, repository, tmp_path):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setattr("tiqr.settings._detected_timezone", lambda: None)
    settings = Settings.from_env()
    assert settings.default_tz == "UTC"
    assert settings.biostar is None
    service = TicketService(repository, settings.secret_key)
    assert isinstance(service.registrar, InMemoryRegistrar)
    assert isinstance(service.event_source, InMemoryEventSource)


@pytest.mark.parametrize(
    ("field", "value"), [("BASE_URL", "https://example.com"), ("VERIFY_TLS", "false")]
)
def test_partial_live_configuration_is_never_silently_fake(monkeypatch, tmp_path, field, value):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_BIOSTAR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setenv(f"TIQR_BIOSTAR_{field}", value)
    with pytest.raises(ValueError, match="Incomplete"):
        Settings.from_env()


def test_blank_password_beside_configured_url_is_rejected(monkeypatch, tmp_path):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_BIOSTAR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setenv("TIQR_BIOSTAR_BASE_URL", "https://example.com")
    monkeypatch.setenv("TIQR_BIOSTAR_PASSWORD", "")
    with pytest.raises(ValueError, match="Incomplete"):
        Settings.from_env()


def test_blank_biostar_placeholders_in_env_file_mean_unset(monkeypatch, tmp_path):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    (tmp_path / ".env").write_text(
        "TIQR_SECRET_KEY=shared-file-key-0123456789abcdef\n"
        "TIQR_BIOSTAR_BASE_URL=\n"
        "TIQR_BIOSTAR_USERNAME=\n"
        "TIQR_BIOSTAR_PASSWORD=\n"
        "TIQR_BIOSTAR_DEVICE_IDS=\n"
        "TIQR_BIOSTAR_ACCESS_GROUP_ID=\n"
        "TIQR_BIOSTAR_VERIFY_TLS=\n"
    )
    assert Settings.from_env().biostar is None


def test_local_file_completes_blank_biostar_placeholders(monkeypatch, tmp_path):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    (tmp_path / ".env").write_text(
        "TIQR_BIOSTAR_BASE_URL=\nTIQR_BIOSTAR_USERNAME=\nTIQR_BIOSTAR_PASSWORD=\n"
        "TIQR_BIOSTAR_DEVICE_IDS=\nTIQR_BIOSTAR_ACCESS_GROUP_ID=\nTIQR_BIOSTAR_VERIFY_TLS=\n"
    )
    (tmp_path / ".env.local").write_text(
        "TIQR_SECRET_KEY=local-file-key-0123456789abcdef\n"
        "TIQR_BIOSTAR_BASE_URL=https://example.com/api\n"
        "TIQR_BIOSTAR_USERNAME=admin\n"
        "TIQR_BIOSTAR_PASSWORD=password\n"
        "TIQR_BIOSTAR_DEVICE_IDS=540598970, 540598971,540598970\n"
        "TIQR_BIOSTAR_ACCESS_GROUP_ID=3\n"
        "TIQR_BIOSTAR_VERIFY_TLS=false\n"
    )
    settings = Settings.from_env()
    assert settings.biostar.base_url == "https://example.com/api"
    assert settings.biostar.device_ids == ("540598970", "540598971")
    assert not settings.biostar.verify_tls


def test_full_live_configuration_is_explicit(monkeypatch, tmp_path):
    values = {
        "BASE_URL": "https://example.com/api",
        "USERNAME": "admin",
        "PASSWORD": "password",
        "DEVICE_IDS": "540598970",
        "ACCESS_GROUP_ID": "3",
        "VERIFY_TLS": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", value)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    settings = Settings.from_env()
    assert settings.biostar.access_group_id == "3"
    assert settings.biostar.device_ids == ("540598970",)
    assert not settings.biostar.verify_tls


@pytest.mark.parametrize(("value", "verify_tls"), [(None, False), ("", False), ("true", True)])
def test_tls_verification_is_off_unless_set_true(monkeypatch, value, verify_tls):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_BIOSTAR_"):
            monkeypatch.delenv(key)
    values = {
        "BASE_URL": "https://example.com/api",
        "USERNAME": "admin",
        "PASSWORD": "password",
        "DEVICE_IDS": "540598970",
    }
    for key, setting in values.items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", setting)
    if value is not None:
        monkeypatch.setenv("TIQR_BIOSTAR_VERIFY_TLS", value)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    assert Settings.from_env().biostar.verify_tls is verify_tls


@pytest.mark.parametrize("required", ["true", "TRUE"])
def test_required_biostar_refuses_local_mode(monkeypatch, required):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setenv("TIQR_BIOSTAR_REQUIRED", required)
    with pytest.raises(ValueError, match="not configured"):
        Settings.from_env()


def test_required_biostar_accepts_full_configuration(monkeypatch):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setenv("TIQR_BIOSTAR_REQUIRED", "true")
    for key, value in {
        "BASE_URL": "https://example.com",
        "USERNAME": "admin",
        "PASSWORD": "password",
        "DEVICE_IDS": "1",
        "ACCESS_GROUP_ID": "2",
    }.items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", value)
    assert Settings.from_env().biostar is not None


def test_biostar_required_flag_must_be_boolean(monkeypatch):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    monkeypatch.setenv("TIQR_BIOSTAR_REQUIRED", "yes")
    with pytest.raises(ValueError, match="TIQR_BIOSTAR_REQUIRED"):
        Settings.from_env()


def test_dotenv_files_override_in_order_and_process_environment_wins(monkeypatch, tmp_path):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    (tmp_path / ".env").write_text(
        "TIQR_SECRET_KEY=shared-file-key-0123456789abcdef\n"
        "TIQR_DB=from-env.db\n"
        "TIQR_OUT=from-env-out\n"
    )
    (tmp_path / ".env.local").write_text("TIQR_SECRET_KEY=local-file-key-0123456789abcdef\n")
    monkeypatch.setenv("TIQR_OUT", "from-process")
    settings = Settings.from_env()
    assert settings.secret_key == "local-file-key-0123456789abcdef"
    assert settings.database_path == tmp_path / "from-env.db"
    assert settings.output_dir == tmp_path / "from-process"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/invalid",
        "https://example.com?secret=x",
    ],
)
def test_live_url_validation(url):
    with pytest.raises(ValueError):
        BioStarSettings(url, "user", "password", ("device",), "group")


@pytest.mark.parametrize(("zone", "hour"), [("Asia/Baku", 4), ("Asia/Almaty", 5)])
def test_timezone_normalization_at_core_input(service, accounts, clock, zone, hour):
    local = datetime(2026, 9, 17, 12, tzinfo=ZoneInfo(zone))
    clock.now = utc(local)
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Name",
        visitor_type="Guest",
        valid_from=local,
        valid_until=local + timedelta(hours=1),
        usage_type=UsageType.ONE_TIME,
    )
    assert ticket.valid_from == datetime(2026, 9, 17, 12 - hour, tzinfo=UTC)
    assert ticket.valid_from.tzinfo == UTC
    assert service.registrar.windows[ticket.external_id] == (ticket.valid_from, ticket.valid_until)


@pytest.mark.parametrize("boundary", ["valid_from", "valid_until"])
def test_subsecond_window_rejected_instead_of_silently_widened(service, accounts, clock, boundary):
    values = {"valid_from": clock.now, "valid_until": clock.now + timedelta(hours=1)}
    values[boundary] += timedelta(microseconds=1)
    with pytest.raises(ValueError, match="whole-second"):
        service.create_ticket(
            accounts["operator"],
            visitor_name="Name",
            visitor_type="Guest",
            usage_type=UsageType.ONE_TIME,
            **values,
        )
    assert service.repository.list_tickets() == []


def test_repository_roundtrip_utc_uuid_enums_and_cursor(service, accounts, clock):
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Əli",
        visitor_type="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.MULTI_USE,
    )
    repo = service.repository
    assert repo.get_ticket(ticket.id) == ticket
    assert repo.ticket_by_external_id(ticket.external_id) == ticket
    row = repo._connection.execute("SELECT * FROM tickets").fetchone()
    for field in ("valid_from", "valid_until", "created_at"):
        assert row[field].endswith("+00:00")
    cursor = SyncCursor('{"upper":"2026-09-17T08:00:00+00:00"}')
    repo.save_cursor(cursor)
    assert repo.get_cursor() == cursor
    event = AccessEvent("id", ticket.id, clock.now, True, Outcome.APPLIED, clock.now)
    repo.add_event(event)
    assert repo.get_event("id") == event
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_event(event)
    assert repo.get_event("id") == event


def test_repository_transactions_roll_back(repository, accounts):
    with pytest.raises(RuntimeError), repository.transaction():
        repository.add_user(replace(accounts["admin"], id=uuid4(), username="rolled-back"))
        repository.save_cursor(SyncCursor("rolled-back"))
        raise RuntimeError("failure")
    assert repository.user_by_name("rolled-back") is None
    assert repository.get_cursor() is None


def test_sequences_and_registration_progress_survive_restart(tmp_path):
    path = tmp_path / "nested" / "tickets.db"
    repo = SQLiteRepository(path)
    repo.initialize()
    assert repo.allocate("remote", 1000000) == 1000000
    registration = Registration("1000000", "30", True, False)
    repo.save_registration(registration)
    repo.close()
    repo = SQLiteRepository(path)
    try:
        repo.initialize()
        assert repo.allocate("remote", 1000000) == 1000001
        assert repo.get_registration("1000000") == registration
    finally:
        repo.close()


def test_old_database_is_not_migrated_or_modified(tmp_path):
    path = tmp_path / "reference.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE guests (id INTEGER)")
    repo = SQLiteRepository(path)
    try:
        with pytest.raises(ValueError, match="Reference"):
            repo.initialize()
        assert repo._connection.execute("SELECT name FROM sqlite_master").fetchone()[0] == "guests"
    finally:
        repo.close()


def _biostar_env(monkeypatch, **values):
    for key in tuple(__import__("os").environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("TIQR_SECRET_KEY", "d23bfaf431a349fea87c38ddcb62ff10")
    base = {"BASE_URL": "https://example.com", "USERNAME": "admin", "PASSWORD": "password"}
    for key, value in (base | values).items():
        monkeypatch.setenv(f"TIQR_BIOSTAR_{key}", value)


def test_access_group_is_optional_and_devices_are_a_list(monkeypatch):
    _biostar_env(monkeypatch, DEVICE_IDS="1, 2,,1")
    biostar = Settings.from_env().biostar
    assert biostar.device_ids == ("1", "2")
    assert biostar.access_group_id == ""


@pytest.mark.parametrize("devices", ["", " ", ","])
def test_at_least_one_device_is_required(monkeypatch, devices):
    _biostar_env(monkeypatch, DEVICE_IDS=devices)
    with pytest.raises(ValueError, match=r"DEVICE_IDS|device ID"):
        Settings.from_env()
