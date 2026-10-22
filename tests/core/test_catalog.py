import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest

from tiqr.core.models import Currency, UsageType, discounted
from tiqr.core.repository import _MIGRATIONS, SQLiteRepository
from tiqr.core.service import NotFoundError, PermissionDeniedError

STAFF = ("admin", "manager")


def issue(service, accounts, clock, *, actor="operator", **overrides):
    return service.create_ticket(
        accounts[actor],
        **{
            "visitor_name": "Name",
            "visitor_type": "Guest",
            "valid_from": clock.now,
            "valid_until": clock.now + timedelta(hours=1),
            "usage_type": UsageType.ONE_TIME,
        }
        | overrides,
    )


@pytest.mark.parametrize(
    ("price", "percent", "expected"),
    [(1000, 0, 1000), (1000, 25, 750), (1000, 100, 0), (999, 50, 500), (1, 50, 1), (0, 30, 0)],
)
def test_discount_rounds_half_up_in_minor_units(price, percent, expected):
    assert discounted(price, percent) == expected


@pytest.mark.parametrize("role", STAFF)
def test_staff_manage_ticket_types(service, accounts, role):
    actor = accounts[role]
    created = service.create_ticket_type(actor, "  Day pass ", 1500, Currency.USD)
    assert (created.name, created.price) == ("Day pass", 1500)

    renamed = service.edit_ticket_type(actor, created.id, name="Daily")
    assert (renamed.name, renamed.price) == ("Daily", 1500)
    repriced = service.edit_ticket_type(actor, created.id, price=2000)
    assert (repriced.name, repriced.price) == ("Daily", 2000)
    changed = service.edit_ticket_type(actor, created.id, currency=Currency.AZN)
    assert (changed.price, changed.currency) == (2000, Currency.AZN)
    assert service.list_ticket_types(actor) == [changed]

    service.delete_ticket_type(actor, created.id)
    assert service.list_ticket_types(actor) == []


@pytest.mark.parametrize("role", STAFF)
def test_staff_manage_visitor_types(service, accounts, role):
    actor = accounts[role]
    created = service.create_visitor_type(actor, "Student", 30)
    assert (created.name, created.discount_percent) == ("Student", 30)

    edited = service.edit_visitor_type(actor, created.id, discount_percent=40)
    assert (edited.name, edited.discount_percent) == ("Student", 40)
    renamed = service.edit_visitor_type(actor, created.id, name="Pupil")
    assert (renamed.name, renamed.discount_percent) == ("Pupil", 40)
    assert service.list_visitor_types(actor) == [renamed]

    service.delete_visitor_type(actor, created.id)
    assert service.list_visitor_types(actor) == []


def test_visitor_type_discount_defaults_to_none(service, accounts):
    assert service.create_visitor_type(accounts["admin"], "Guest").discount_percent == 0


def test_operators_read_the_catalog_but_cannot_change_it(service, accounts):
    admin, operator = accounts["admin"], accounts["operator"]
    ticket_type = service.create_ticket_type(admin, "Day", 100, Currency.USD)
    visitor_type = service.create_visitor_type(admin, "Student", 10)

    assert service.list_ticket_types(operator) == [ticket_type]
    assert service.list_visitor_types(operator) == [visitor_type]
    for denied in (
        lambda: service.create_ticket_type(operator, "Night", 1, Currency.USD),
        lambda: service.edit_ticket_type(operator, ticket_type.id, price=1),
        lambda: service.delete_ticket_type(operator, ticket_type.id),
        lambda: service.create_visitor_type(operator, "Staff", 1),
        lambda: service.edit_visitor_type(operator, visitor_type.id, discount_percent=1),
        lambda: service.delete_visitor_type(operator, visitor_type.id),
    ):
        with pytest.raises(PermissionDeniedError):
            denied()
    assert service.list_ticket_types(admin) == [ticket_type]
    assert service.list_visitor_types(admin) == [visitor_type]


def test_deactivated_actors_are_refused(service, accounts):
    service.edit_user(accounts["manager"].id, active=False)
    with pytest.raises(PermissionDeniedError):
        service.create_ticket_type(accounts["manager"], "Day", 100, Currency.USD)
    with pytest.raises(PermissionDeniedError):
        service.list_visitor_types(accounts["manager"])


@pytest.mark.parametrize(
    "create",
    [
        lambda service, actor: service.create_ticket_type(actor, " ", 100, Currency.USD),
        lambda service, actor: service.create_ticket_type(actor, "Day", -1, Currency.USD),
        lambda service, actor: service.create_ticket_type(actor, "Day", 10**9 + 1, Currency.USD),
        lambda service, actor: service.create_visitor_type(actor, "", 10),
        lambda service, actor: service.create_visitor_type(actor, "Student", -1),
        lambda service, actor: service.create_visitor_type(actor, "Student", 101),
    ],
)
def test_invalid_catalog_entries_are_refused(service, accounts, create):
    with pytest.raises(ValueError):
        create(service, accounts["admin"])
    assert service.list_ticket_types(accounts["admin"]) == []
    assert service.list_visitor_types(accounts["admin"]) == []


def test_names_are_unique_whatever_their_case(service, accounts):
    admin = accounts["admin"]
    day = service.create_ticket_type(admin, "Day", 100, Currency.USD)
    night = service.create_ticket_type(admin, "Night", 200, Currency.USD)
    with pytest.raises(ValueError, match="already exists"):
        service.create_ticket_type(admin, " day ", 1, Currency.USD)
    with pytest.raises(ValueError, match="already exists"):
        service.edit_ticket_type(admin, night.id, name="DAY")
    # Changing only the case of its own name is not a clash
    assert service.edit_ticket_type(admin, day.id, name="DAY").name == "DAY"

    student = service.create_visitor_type(admin, "Student", 10)
    staff = service.create_visitor_type(admin, "Staff", 20)
    with pytest.raises(ValueError, match="already exists"):
        service.create_visitor_type(admin, "student", 5)
    with pytest.raises(ValueError, match="already exists"):
        service.edit_visitor_type(admin, staff.id, name="STUDENT")
    assert service.edit_visitor_type(admin, student.id, name="STUDENT").name == "STUDENT"


def test_edits_need_a_change_and_an_existing_entry(service, accounts):
    admin = accounts["admin"]
    day = service.create_ticket_type(admin, "Day", 100, Currency.USD)
    student = service.create_visitor_type(admin, "Student", 10)
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_ticket_type(admin, day.id)
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_visitor_type(admin, student.id)
    for missing in (
        lambda: service.edit_ticket_type(admin, uuid4(), price=1),
        lambda: service.delete_ticket_type(admin, uuid4()),
        lambda: service.edit_visitor_type(admin, uuid4(), discount_percent=1),
        lambda: service.delete_visitor_type(admin, uuid4()),
    ):
        with pytest.raises(NotFoundError):
            missing()


def test_ticket_price_is_the_type_price_less_the_visitor_discount(service, accounts, clock):
    admin = accounts["admin"]
    service.create_ticket_type(admin, "Day pass", 1250, Currency.USD)
    service.create_visitor_type(admin, "Student", 20)

    ticket = issue(service, accounts, clock, ticket_type="day pass", visitor_type="student")

    assert ticket.ticket_type == "Day pass"
    assert ticket.visitor_type == "Student"
    assert (ticket.base_price, ticket.discount_percent, ticket.price) == (1250, 20, 1000)
    assert ticket.currency == Currency.USD
    assert service.repository.get_ticket(ticket.id) == ticket


def test_other_visitor_types_pay_the_full_price(service, accounts, clock):
    service.create_ticket_type(accounts["admin"], "Day pass", 1250, Currency.USD)

    ticket = issue(service, accounts, clock, ticket_type="Day pass", visitor_type="Walk-in")

    assert (ticket.visitor_type, ticket.discount_percent, ticket.price) == ("Walk-in", 0, 1250)


def test_tickets_without_a_ticket_type_have_no_price(service, accounts, clock):
    service.create_visitor_type(accounts["admin"], "Student", 20)

    ticket = issue(service, accounts, clock, visitor_type="Student")

    assert (ticket.ticket_type, ticket.base_price, ticket.price) == (None, None, None)
    assert ticket.discount_percent == 20


def test_an_unknown_ticket_type_is_refused_before_anything_is_issued(service, accounts, clock):
    with pytest.raises(ValueError, match="Unknown ticket type"):
        issue(service, accounts, clock, ticket_type="Nope")
    assert service.repository.list_tickets() == []
    assert service.registrar.removed == []


def test_issued_tickets_keep_their_price_when_the_catalog_changes(service, accounts, clock):
    admin = accounts["admin"]
    day = service.create_ticket_type(admin, "Day pass", 1000, Currency.USD)
    student = service.create_visitor_type(admin, "Student", 50)
    ticket = issue(service, accounts, clock, ticket_type="Day pass", visitor_type="Student")
    assert ticket.price == 500

    service.edit_ticket_type(admin, day.id, name="Daily", price=9999)
    service.edit_visitor_type(admin, student.id, name="Pupil", discount_percent=0)
    assert service.get_ticket(admin, ticket.id).price == 500

    service.delete_ticket_type(admin, day.id)
    service.delete_visitor_type(admin, student.id)
    kept = service.get_ticket(admin, ticket.id)
    assert (kept.ticket_type, kept.visitor_type, kept.price) == ("Day pass", "Student", 500)


def test_tickets_from_before_the_catalog_upgrade_without_a_price(
    service, accounts, clock, tmp_path
):
    ticket = issue(service, accounts, clock)
    path = tmp_path / "v3.db"
    with sqlite3.connect(path) as connection:
        for step in _MIGRATIONS[:3]:
            for statement in step:
                connection.execute(statement)
        connection.execute("PRAGMA user_version = 3")
        connection.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (?,?,?,?)",
            (str(ticket.created_by), "operator", "hash", "operator"),
        )
        connection.execute(
            "INSERT INTO tickets (id, external_id, qr_payload, readable_serial, visitor_name,"
            " visitor_type, valid_from, valid_until, usage_type, state, created_by,"
            " assigned_operator, created_at, print_count, use_count)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)",
            (
                str(ticket.id),
                ticket.external_id,
                ticket.qr_payload,
                ticket.readable_serial,
                ticket.visitor_name,
                ticket.visitor_type,
                ticket.valid_from.isoformat(),
                ticket.valid_until.isoformat(),
                ticket.usage_type.value,
                ticket.state.value,
                str(ticket.created_by),
                str(ticket.assigned_operator),
                ticket.created_at.isoformat(),
            ),
        )

    with SQLiteRepository(path) as repository:
        repository.initialize(upgrade=True)
        upgraded = repository.get_ticket(ticket.id)

    assert upgraded == ticket
    assert (upgraded.ticket_type, upgraded.base_price, upgraded.discount_percent) == (None, None, 0)
