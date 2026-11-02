import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tiqr.core.biostar import BioStarError
from tiqr.core.fakes import InMemoryRegistrar
from tiqr.core.models import TicketState, UsageType
from tiqr.core.repository import OLDEST_REVERSIBLE, SCHEMA_VERSION, SQLiteRepository
from tiqr.core.service import (
    CredentialFormatError,
    ExternalCodeTakenError,
    IdempotencyConflictError,
    PermissionDeniedError,
    StateError,
)

INVALID = r"(?i)invalid"
START = datetime(2026, 9, 17, 9, tzinfo=UTC)
END = datetime(2026, 9, 17, 11, tzinfo=UTC)


class FlakyRegistrar(InMemoryRegistrar):
    """Fails the named calls, as BioStar does when it is down."""

    def __init__(self):
        super().__init__()
        self.failing = set()
        self.calls = []

    def _call(self, name):
        self.calls.append(name)
        if name in self.failing:
            raise BioStarError(f"{name} refused")

    def deactivate(self, external_id):
        self._call("deactivate")
        super().deactivate(external_id)

    def activate(self, external_id):
        self._call("activate")
        super().activate(external_id)

    def set_window(self, external_id, start, end):
        self._call("set_window")
        super().set_window(external_id, start, end)


@pytest.fixture
def registrar(service):
    service.registrar = FlakyRegistrar()
    return service.registrar


@pytest.fixture
def make(service, accounts):
    service.create_visitor_type(accounts["admin"], "Visitor")

    def create(**overrides):
        arguments = {
            "visitor_name": "Ali",
            "visitor_type": "Visitor",
            "valid_from": START,
            "valid_until": END,
            "usage_type": UsageType.ONE_TIME,
        } | overrides
        return service.create_ticket(accounts["manager"], **arguments)

    return create


def actions(service, ticket):
    return [entry.action for entry in service.repository.list_audit(ticket.id)]


def test_revoke_moves_the_ticket_cancels_access_and_audits_the_reason(
    service, accounts, registrar, make
):
    ticket = make()
    revoked = service.revoke_ticket(accounts["manager"], ticket.id, "  lost card ")
    assert revoked.state == TicketState.REVOKED
    assert registrar.deactivated == [ticket.external_id]
    entry = service.repository.list_audit(ticket.id)[-1]
    assert (entry.action, entry.reason, entry.actor) == ("ticket.revoke", "lost card", "manager")


def test_revoking_twice_returns_the_current_state_without_touching_biostar(
    service, accounts, registrar, make
):
    ticket = make()
    first = service.revoke_ticket(accounts["manager"], ticket.id)
    registrar.calls.clear()
    assert service.revoke_ticket(accounts["manager"], ticket.id) == first
    assert registrar.calls == []
    assert actions(service, ticket).count("ticket.revoke") == 1


def test_an_expired_ticket_cannot_be_revoked(service, accounts, clock, make):
    ticket = make()
    clock.now = END + timedelta(minutes=1)
    with pytest.raises(StateError, match="Illegal transition"):
        service.revoke_ticket(accounts["manager"], ticket.id)
    assert "ticket.revoke.failed" in actions(service, ticket)


def test_an_operator_can_revoke_a_ticket_assigned_to_them(service, accounts, registrar, make):
    ticket = make()
    service.assign_ticket(accounts["manager"], ticket.id, "operator")
    revoked = service.revoke_ticket(accounts["operator"], ticket.id, "lost card")
    assert revoked.state == TicketState.REVOKED
    assert registrar.deactivated == [ticket.external_id]
    entry = service.repository.list_audit(ticket.id)[-1]
    assert (entry.action, entry.actor) == ("ticket.revoke", "operator")


def test_an_operator_can_reissue_a_ticket_assigned_to_them(service, accounts, make):
    ticket = make()
    service.assign_ticket(accounts["manager"], ticket.id, "operator")
    service.revoke_ticket(accounts["operator"], ticket.id)
    reissued = service.reissue_ticket(accounts["operator"], ticket.id)
    assert reissued.state == TicketState.ISSUED
    assert actions(service, ticket)[-1] == "ticket.reissue"


def test_operators_cannot_revoke_or_reissue_an_unassigned_ticket(service, accounts, make):
    ticket = make()
    with pytest.raises(PermissionDeniedError):
        service.revoke_ticket(accounts["operator"], ticket.id)
    with pytest.raises(PermissionDeniedError):
        service.reissue_ticket(accounts["operator"], ticket.id)
    assert service.repository.get_ticket(ticket.id).state == TicketState.ISSUED


def test_a_biostar_failure_leaves_the_ticket_issued_and_is_audited(
    service, accounts, registrar, make
):
    ticket = make()
    registrar.failing.add("deactivate")
    with pytest.raises(BioStarError):
        service.revoke_ticket(accounts["manager"], ticket.id, "fraud")
    assert service.get_ticket(accounts["manager"], ticket.id).state == TicketState.ISSUED
    failed = service.repository.list_audit(ticket.id)[-1]
    assert (failed.action, failed.reason) == ("ticket.revoke.failed", "fraud")
    # Retrying once BioStar answers again succeeds.
    registrar.failing.clear()
    assert service.revoke_ticket(accounts["manager"], ticket.id).state == TicketState.REVOKED


def test_a_revoked_ticket_no_longer_expires_or_counts_as_a_scan(service, accounts, clock, make):
    ticket = make()
    service.revoke_ticket(accounts["manager"], ticket.id)
    clock.now = END + timedelta(days=1)
    assert service.get_ticket(accounts["manager"], ticket.id).state == TicketState.REVOKED


def test_update_validity_moves_the_window_in_biostar_and_audits_it(
    service, accounts, registrar, make
):
    ticket = make()
    new_end = END + timedelta(hours=1)
    updated = service.update_validity(accounts["manager"], ticket.id, valid_until=new_end)
    assert (updated.valid_from, updated.valid_until) == (START, new_end)
    assert registrar.windows[ticket.external_id] == (START, new_end)
    assert service.repository.list_audit(ticket.id)[-1].action == "ticket.update_validity"


def test_update_validity_refuses_a_reversed_window_and_a_closed_ticket(
    service, accounts, registrar, make
):
    ticket = make()
    with pytest.raises(ValueError, match="after its start"):
        service.update_validity(accounts["manager"], ticket.id, valid_until=START)
    with pytest.raises(ValueError, match="Nothing to change"):
        service.update_validity(accounts["manager"], ticket.id)
    service.revoke_ticket(accounts["manager"], ticket.id)
    with pytest.raises(StateError, match="revoked ticket cannot be changed"):
        service.update_validity(accounts["manager"], ticket.id, valid_until=END + timedelta(1))
    assert registrar.windows[ticket.external_id] == (START, END)


def test_a_failed_window_sync_changes_nothing(service, accounts, registrar, make):
    ticket = make()
    registrar.failing.add("set_window")
    with pytest.raises(BioStarError):
        service.update_validity(accounts["manager"], ticket.id, valid_until=END + timedelta(1))
    assert service.get_ticket(accounts["manager"], ticket.id).valid_until == END


def test_a_failed_save_puts_the_biostar_window_back(
    service, accounts, registrar, make, monkeypatch
):
    ticket = make()
    new_end = END + timedelta(hours=2)

    def fail(_):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service.repository, "save_ticket", fail)
    with pytest.raises(RuntimeError):
        service.update_validity(accounts["manager"], ticket.id, valid_until=new_end)
    assert registrar.windows[ticket.external_id] == (START, END)


def test_external_code_is_unique_per_tenant_and_filterable(service, accounts, repository, make):
    first = make(external_code=" BAR-1 ")
    assert first.external_code == "BAR-1"
    with pytest.raises(StateError, match="external code"):
        make(external_code="BAR-1")
    make(external_code="BAR-2")
    found = service.list_tickets(accounts["manager"], external_code="BAR-1")
    assert [ticket.id for ticket in found] == [first.id]
    # The index backs the check up when two writers race past it.
    with pytest.raises(sqlite3.IntegrityError):
        repository._connection.execute(
            "UPDATE tickets SET external_code='BAR-1' WHERE external_code='BAR-2'"
        )


@pytest.mark.parametrize("code", ["4821930057716642", "004821930057", "AB-12-cd"])
def test_readable_external_codes_are_accepted(make, code):
    assert make(external_code=code).external_code == code


@pytest.mark.parametrize("code", ["12345", "1234567890123", "AB_12", "ABC 12", "A" * 33])
def test_unreadable_external_codes_are_refused_before_any_write(
    service, accounts, registrar, make, code
):
    with pytest.raises(CredentialFormatError):
        make(external_code=code)
    assert registrar.tickets == {}


def test_a_taken_external_code_is_its_own_error(service, accounts, make):
    make(external_code="BAR-1")
    with pytest.raises(ExternalCodeTakenError) as taken:
        make(external_code="BAR-1")
    assert taken.value.code == "external_code_taken"


def test_the_same_code_may_exist_in_another_tenant(service, accounts, repository, make):
    make(external_code="SHARED")
    service.tenant = "second"
    other = make(external_code="SHARED")
    assert other.tenant_id == "second"


def test_idempotency_replays_conflicts_and_expires(service, clock):
    ttl = timedelta(hours=1)
    assert service.idempotency_lookup("k", "fp") is None
    service.idempotency_store("k", "fp", 201, '{"ok":true}', ttl)
    stored = service.idempotency_lookup("k", "fp")
    assert (stored.status, stored.body) == (201, '{"ok":true}')
    with pytest.raises(IdempotencyConflictError):
        service.idempotency_lookup("k", "other")
    clock.now += timedelta(hours=2)
    assert service.idempotency_lookup("k", "other") is None


def test_transfer_keeps_state_id_and_history(service, accounts, registrar, make):
    ticket = make(event_session="Evening")
    service.revoke_ticket(accounts["manager"], make().id)
    moved = service.transfer_ticket(
        accounts["manager"],
        ticket.id,
        "Matinee",
        valid_from=START - timedelta(hours=1),
        valid_until=END - timedelta(hours=1),
    )
    assert (moved.id, moved.state, moved.event_session) == (
        ticket.id,
        TicketState.ISSUED,
        "Matinee",
    )
    assert registrar.windows[ticket.external_id][0] == START - timedelta(hours=1)
    assert actions(service, ticket) == ["ticket.create", "ticket.transfer"]


def test_transfer_of_a_revoked_ticket_is_refused(service, accounts, make):
    ticket = make()
    service.revoke_ticket(accounts["manager"], ticket.id)
    with pytest.raises(StateError):
        service.transfer_ticket(accounts["manager"], ticket.id, "Other")


def test_reissue_brings_the_same_revoked_ticket_back(service, accounts, registrar, make):
    ticket = make()
    service.revoke_ticket(accounts["manager"], ticket.id, "lost")
    assert ticket.external_id in registrar.deactivated
    again = service.reissue_ticket(accounts["manager"], ticket.id)
    assert (again.id, again.state, again.readable_serial) == (
        ticket.id,
        TicketState.ISSUED,
        ticket.readable_serial,
    )
    assert ticket.external_id not in registrar.deactivated
    assert len(service.list_tickets(accounts["manager"])) == 1
    assert actions(service, ticket) == ["ticket.create", "ticket.revoke", "ticket.reissue"]


def test_reissue_of_an_expired_ticket_needs_a_future_window(
    service, accounts, clock, registrar, make
):
    ticket = make()
    clock.now = END + timedelta(minutes=1)
    with pytest.raises(ValueError, match="already expired"):
        service.reissue_ticket(accounts["manager"], ticket.id)
    new_end = END + timedelta(days=1)
    again = service.reissue_ticket(accounts["manager"], ticket.id, valid_until=new_end)
    assert (again.state, again.valid_until) == (TicketState.ISSUED, new_end)
    assert registrar.windows[ticket.external_id] == (START, new_end)


def test_a_viable_ticket_can_be_reissued_with_a_new_window(service, accounts, registrar, make):
    ticket = make()
    new_end = END + timedelta(days=1)
    again = service.reissue_ticket(accounts["manager"], ticket.id, valid_until=new_end)
    assert (again.id, again.state, again.valid_until) == (ticket.id, TicketState.ISSUED, new_end)
    assert registrar.windows[ticket.external_id] == (START, new_end)


def test_a_failed_biostar_reissue_leaves_the_ticket_revoked(service, accounts, registrar, make):
    ticket = make()
    service.revoke_ticket(accounts["manager"], ticket.id)
    registrar.failing.add("activate")
    with pytest.raises(BioStarError):
        service.reissue_ticket(accounts["manager"], ticket.id)
    assert service.get_ticket(accounts["manager"], ticket.id).state == TicketState.REVOKED


def test_api_keys_authenticate_rotate_and_revoke(service, accounts, clock):
    key, secret = service.create_api_key(
        accounts["admin"], "pos", ["tickets:read"], acts_as="manager"
    )
    user, found = service.authenticate_api_key(secret)
    assert (user.username, found.id) == ("manager", key.id)
    assert secret not in repr(service.repository.list_api_keys())
    new, new_secret = service.rotate_api_key(accounts["admin"], key.id, timedelta(minutes=30))
    service.authenticate_api_key(secret)
    clock.now += timedelta(minutes=31)
    with pytest.raises(Exception, match=INVALID):
        service.authenticate_api_key(secret)
    service.authenticate_api_key(new_secret)
    revoked = service.revoke_api_key(accounts["admin"], new.id)
    assert service.revoke_api_key(accounts["admin"], new.id) == revoked
    with pytest.raises(Exception, match=INVALID):
        service.authenticate_api_key(new_secret)


def test_only_the_admin_manages_keys_and_scopes_are_checked(service, accounts):
    with pytest.raises(PermissionDeniedError):
        service.create_api_key(accounts["manager"], "x", ["tickets:read"])
    with pytest.raises(ValueError, match="Scopes"):
        service.create_api_key(accounts["admin"], "x", ["tickets:everything"])


def test_the_attribution_is_written_with_the_actor(service, accounts, make):
    ticket = make()
    _, secret = service.create_api_key(accounts["admin"], "pos", ["tickets:revoke"])
    with service.attributed("api_key:pos"):
        service.revoke_ticket(accounts["manager"], ticket.id)
    assert service.repository.list_audit(ticket.id)[-1].actor == "api_key:pos (as manager)"
    assert secret


def test_migrations_8_to_10_reverse_cleanly(tmp_path, accounts):
    path = tmp_path / "reversible.db"
    with SQLiteRepository(path) as repository:
        repository.initialize()
        repository._connection.execute("PRAGMA user_version").fetchone()
        assert SCHEMA_VERSION == 10
        repository.downgrade(OLDEST_REVERSIBLE)
        columns = {row[1] for row in repository._connection.execute("PRAGMA table_info(tickets)")}
        tables = {
            row[0] for row in repository._connection.execute("SELECT name FROM sqlite_master")
        }
        assert "external_code" not in columns
        assert not {"audit_log", "idempotency_keys", "api_keys"} & tables
        event_columns = {
            row[1] for row in repository._connection.execute("PRAGMA table_info(access_events)")
        }
        assert not {"point_id", "point_name", "direction", "sequence"} & event_columns
        with pytest.raises(ValueError, match="Cannot downgrade"):
            repository.downgrade(OLDEST_REVERSIBLE - 1)
        repository.initialize(upgrade=True)
        assert repository._connection.execute("PRAGMA user_version").fetchone()[0] == 10
