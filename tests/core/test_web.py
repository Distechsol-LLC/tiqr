import sqlite3
from datetime import timedelta

import pytest

from tiqr.core import auth, settings
from tiqr.core import repository as repository_module
from tiqr.core.auth import WEB_SESSION_IDLE, WEB_SESSION_LIFETIME, AuthenticationError, new_user
from tiqr.core.models import RawEvent, Role, TicketState, UsageType
from tiqr.core.repository import _MIGRATIONS, SCHEMA_VERSION, SQLiteRepository
from tiqr.core.service import PermissionDeniedError, StateError


def version(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


def write_v1(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(";\n".join((*_MIGRATIONS[0], "PRAGMA user_version = 1;")))


def test_new_database_gets_the_latest_schema(tmp_path):
    path = tmp_path / "new.db"
    with SQLiteRepository(path) as repository:
        repository.initialize()
    assert version(path) == SCHEMA_VERSION == 7


def test_older_schema_is_refused_until_setup_upgrades_it(tmp_path):
    path = tmp_path / "v1.db"
    write_v1(path)
    with SQLiteRepository(path) as repository:
        with pytest.raises(ValueError, match=r"version 1 is out of date.*tiqr setup"):
            repository.initialize()
        assert version(path) == 1
        repository.initialize(upgrade=True)
    assert version(path) == SCHEMA_VERSION
    # Upgrading again, or from another process, changes nothing.
    with SQLiteRepository(path) as repository:
        repository.initialize(upgrade=True)
        repository.initialize()


def test_newer_schema_is_refused_even_when_upgrading(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with SQLiteRepository(path) as repository, pytest.raises(ValueError, match="Unsupported"):
        repository.initialize(upgrade=True)


def test_failed_migration_step_keeps_the_old_version(tmp_path, monkeypatch):
    path = tmp_path / "v1.db"
    write_v1(path)
    monkeypatch.setattr(
        repository_module, "_MIGRATIONS", (_MIGRATIONS[0], ("CREATE TABLE broken (",))
    )
    with SQLiteRepository(path) as repository, pytest.raises(sqlite3.OperationalError):
        repository.initialize(upgrade=True)
    assert version(path) == 1


def test_ping_answers_while_open_and_fails_once_closed(tmp_path):
    repository = SQLiteRepository(tmp_path / "ping.db")
    repository.initialize()
    assert repository.ping() is True
    repository.close()
    assert repository.ping() is False


def test_web_session_round_trip_and_logout(service, accounts):
    token, session = service.open_web_session(accounts["manager"])
    assert session.user_id == accounts["manager"].id
    assert token not in (session.token_hash, session.csrf_token)
    # Only the hash is stored, so the database alone cannot sign anyone in.
    assert service.repository.get_web_session(token) is None
    user, resumed = service.resume_web_session(token)
    assert user == accounts["manager"]
    assert resumed.csrf_token == session.csrf_token
    service.close_web_session(token)
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)


def test_unknown_or_blank_web_token_is_refused(service):
    for token in ("", "not-a-session"):
        with pytest.raises(AuthenticationError, match="Not signed in"):
            service.resume_web_session(token)


def test_web_session_ends_when_idle(service, accounts, clock):
    token, _ = service.open_web_session(accounts["operator"])
    clock.now += WEB_SESSION_IDLE - timedelta(seconds=1)
    service.resume_web_session(token)
    # Activity moved the idle deadline along.
    clock.now += WEB_SESSION_IDLE - timedelta(seconds=1)
    service.resume_web_session(token)
    clock.now += WEB_SESSION_IDLE
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)
    # The ended session was deleted, not just refused.
    clock.now -= WEB_SESSION_IDLE
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)


def test_web_session_ends_at_its_lifetime_despite_activity(service, accounts, clock):
    token, session = service.open_web_session(accounts["operator"])
    assert session.expires_at == clock.now + WEB_SESSION_LIFETIME
    end = clock.now + WEB_SESSION_LIFETIME
    while clock.now + WEB_SESSION_IDLE / 2 < end:
        clock.now += WEB_SESSION_IDLE / 2
        service.resume_web_session(token)
    clock.now = end
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)


def test_recent_requests_skip_the_seen_time_write(service, accounts, clock):
    token, session = service.open_web_session(accounts["operator"])
    clock.now += timedelta(seconds=30)
    assert service.resume_web_session(token)[1].last_seen_at == session.last_seen_at
    clock.now += timedelta(seconds=30)
    assert service.resume_web_session(token)[1].last_seen_at == clock.now


def test_login_sweeps_ended_sessions(service, accounts, clock):
    stale, _ = service.open_web_session(accounts["operator"])
    clock.now += WEB_SESSION_IDLE
    service.open_web_session(accounts["admin"])
    assert service.repository.get_web_session(auth.web_token_hash(stale)) is None


def test_web_session_needs_an_existing_account(service, accounts):
    with pytest.raises(PermissionDeniedError):
        service.open_web_session(new_user("ghost", "password", Role.ADMIN))


@pytest.mark.parametrize("role", list(Role))
def test_staff_create_and_list_users(service, accounts, role):
    actor = accounts[role.value]
    if role == Role.OPERATOR:
        with pytest.raises(PermissionDeniedError):
            service.list_accounts(actor)
        with pytest.raises(PermissionDeniedError):
            service.create_user(actor, "newcomer", "newcomer-password", Role.OPERATOR)
        return
    assert [user.username for user in service.list_accounts(actor)] == sorted(accounts)
    created = service.create_user(actor, "newcomer", "newcomer-password", Role.OPERATOR)
    assert service.repository.user_by_name("newcomer") == created
    # Managers add operators only; admins add any role but a second admin.
    if role == Role.MANAGER:
        with pytest.raises(PermissionDeniedError, match="only create operators"):
            service.create_user(actor, "boss", "boss-password", Role.MANAGER)
    else:
        assert (
            service.create_user(actor, "boss", "boss-password", Role.MANAGER).role == Role.MANAGER
        )
        with pytest.raises(StateError, match="Only one admin"):
            service.create_user(actor, "boss-two", "boss-password", Role.ADMIN)


def test_scheduled_runs_need_no_actor(service, accounts, clock):
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Name",
        visitor_type="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.ONE_TIME,
    )
    service.event_source.events.append(RawEvent("scan", ticket.external_id, clock.now, True))
    assert service.scheduled_sync() == 1
    assert service.repository.get_ticket(ticket.id).state == TicketState.PASSED
    assert service.scheduled_cleanup() == 1


def test_unknown_user_costs_a_hash_but_blank_password_does_not(service, monkeypatch):
    checked = []

    class Hasher:
        def hash(self, password):
            return "decoy"

        def verify(self, hashed, password):
            checked.append(password)

    monkeypatch.setattr(auth, "_HASHER", Hasher())
    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        service.authenticate("nobody", "some-password")
    assert checked == ["some-password"]
    with pytest.raises(AuthenticationError):
        service.authenticate("nobody", "  ")
    assert checked == ["some-password"]


def test_tiqr_home_relocates_config_and_data(monkeypatch, tmp_path):
    monkeypatch.setenv("TIQR_HOME", str(tmp_path / "home"))
    assert settings._project_root() == tmp_path / "home"
    monkeypatch.setenv("TIQR_HOME", " ")
    assert settings._project_root() != tmp_path / "home"
