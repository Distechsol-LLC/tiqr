from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tiqr.core.models import RawEvent, Role, TicketState, UsageType
from tiqr.core.service import NotFoundError, PermissionDeniedError, StateError

ACTIONS = ("create", "view", "view_other", "assign", "stats", "sync", "cleanup", "print", "reprint")


@pytest.fixture(autouse=True)
def visitor_type(service, accounts):
    guest = service.create_visitor_type(accounts["admin"], "Guest")
    service.create_visitor_subtype(accounts["admin"], guest.id, "Guest")


def issue(service, accounts, clock, actor="operator", usage=UsageType.ONE_TIME):
    return service.create_ticket(
        accounts[actor],
        visitor_name="Name",
        visitor_type="Guest",
        visitor_subtype="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=usage,
    )


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("action", ACTIONS)
def test_permission_matrix_cell(service, accounts, clock, tmp_path, role, action):
    actor = accounts[role.value]
    ticket = issue(service, accounts, clock, role.value)
    other = issue(service, accounts, clock, "other")

    def render(ticket, output_dir, timezone):
        path = output_dir / f"{ticket.id}.pdf"
        path.write_bytes(b"PDF")
        return path

    def perform():
        if action == "create":
            return issue(service, accounts, clock, role.value)
        if action == "view":
            return service.get_ticket(actor, ticket.id)
        if action == "view_other":
            return service.get_ticket(actor, other.id)
        if action == "assign":
            return service.assign_ticket(actor, ticket.id, "other")
        if action in ("print", "reprint"):
            result = service.print_ticket(actor, ticket.id, tmp_path, renderer=render)
            if action == "reprint":
                return service.print_ticket(actor, ticket.id, tmp_path, renderer=render)
            return result
        return getattr(service, action)(actor)

    allowed = (action != "assign" or role != Role.OPERATOR) and (
        action not in ("stats", "sync", "cleanup", "view_other") or role != Role.OPERATOR
    )
    if allowed:
        perform()
    else:
        with pytest.raises(PermissionDeniedError):
            perform()


@pytest.mark.parametrize("role", list(Role))
def test_creation_assignee_defaults_to_creator(service, accounts, clock, role):
    ticket = issue(service, accounts, clock, role.value)
    assert ticket.assigned_operator == ticket.created_by == accounts[role.value].id


def test_reassignment_changes_operator_visibility(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    other = issue(service, accounts, clock, "other")
    assert [t.id for t in service.list_tickets(accounts["operator"])] == [ticket.id]
    service.assign_ticket(accounts["manager"], ticket.id, "other")
    assert service.list_tickets(accounts["operator"]) == []
    assert {t.id for t in service.list_tickets(accounts["other"])} == {ticket.id, other.id}
    with pytest.raises(PermissionDeniedError):
        service.get_ticket(accounts["operator"], ticket.id)
    assert len(service.list_tickets(accounts["admin"])) == 2
    assert len(service.list_tickets(accounts["manager"])) == 2


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("state", [TicketState.PASSED, TicketState.EXPIRED])
def test_print_and_reprint_restricted_to_issued(service, accounts, clock, role, state, tmp_path):
    ticket = issue(service, accounts, clock, role.value)
    if state == TicketState.PASSED:
        service.event_source.events.append(RawEvent("1", ticket.external_id, clock.now, True))
        service.sync(accounts["manager"])
    else:
        clock.now = ticket.valid_until + timedelta(seconds=1)
    for _ in range(2):
        with pytest.raises(StateError):
            service.print_ticket(accounts[role.value], ticket.id, tmp_path)
    assert service.repository.get_ticket(ticket.id).state == state
    assert service.repository.get_ticket(ticket.id).print_count == 0


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MANAGER])
def test_privileged_roles_see_every_state(service, accounts, clock, role):
    ticket = issue(service, accounts, clock)
    assert service.get_ticket(accounts[role.value], ticket.id).state == TicketState.ISSUED
    service.event_source.events.append(RawEvent("1", ticket.external_id, clock.now, True))
    service.sync(accounts["manager"])
    assert service.get_ticket(accounts[role.value], ticket.id).state == TicketState.PASSED
    clock.now = ticket.valid_until + timedelta(seconds=1)
    assert service.get_ticket(accounts[role.value], ticket.id).state == TicketState.EXPIRED


def test_unlimited_reprints_count_only_success(service, accounts, clock, tmp_path):
    ticket = issue(service, accounts, clock)

    def render(ticket, output_dir, timezone):
        path = output_dir / f"{ticket.id}.pdf"
        path.write_bytes(b"PDF")
        return path

    for _ in range(5):
        service.print_ticket(accounts["operator"], ticket.id, tmp_path, renderer=render)
    assert service.repository.get_ticket(ticket.id).print_count == 5

    def failure(*args):
        raise OSError("disk full")

    with pytest.raises(OSError):
        service.print_ticket(accounts["operator"], ticket.id, tmp_path, renderer=failure)
    assert service.repository.get_ticket(ticket.id).print_count == 5


def test_operator_cannot_print_unassigned_ticket(service, accounts, clock, tmp_path):
    ticket = issue(service, accounts, clock, "other")
    with pytest.raises(PermissionDeniedError):
        service.print_ticket(accounts["operator"], ticket.id, tmp_path)


def test_spoofed_actor_role_is_not_trusted(service, accounts):
    with pytest.raises(PermissionDeniedError):
        service.stats(replace(accounts["operator"], role=Role.ADMIN))
    with pytest.raises(PermissionDeniedError):
        service.stats(replace(accounts["admin"], id=uuid4()))


def test_assignment_requires_existing_user(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    with pytest.raises(NotFoundError):
        service.assign_ticket(accounts["manager"], ticket.id, "missing")
    assert service.repository.get_ticket(ticket.id).assigned_operator == ticket.assigned_operator
