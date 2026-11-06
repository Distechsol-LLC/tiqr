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
            "visitor_subtype": "Guest",
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
    created = service.create_visitor_type(actor, "Student")
    assert (created.name, created.discount_percent) == ("Student", 0)

    renamed = service.edit_visitor_type(actor, created.id, name="Pupil")
    assert (renamed.name, renamed.discount_percent) == ("Pupil", 0)
    # A zero discount is no discount, so it is not refused.
    assert service.edit_visitor_type(actor, created.id, discount_percent=0) == renamed
    assert service.list_visitor_types(actor) == [renamed]

    service.delete_visitor_type(actor, created.id)
    assert service.list_visitor_types(actor) == []


def test_visitor_type_discount_defaults_to_none(service, accounts):
    assert service.create_visitor_type(accounts["admin"], "Guest").discount_percent == 0


def test_tickets_take_discounts_from_subtypes_not_types(service, accounts):
    admin = accounts["admin"]
    with pytest.raises(ValueError, match="Discounts are set on visitor subtypes"):
        service.create_visitor_type(admin, "Student", 30)
    student = service.create_visitor_type(admin, "Student")
    with pytest.raises(ValueError, match="Discounts are set on visitor subtypes"):
        service.edit_visitor_type(admin, student.id, discount_percent=30)
    assert service.list_visitor_types(admin) == [student]


@pytest.mark.parametrize("role", STAFF)
def test_staff_manage_visitor_subtypes(service, accounts, role):
    actor = accounts[role]
    student = service.create_visitor_type(actor, "Student")
    created = service.create_visitor_subtype(actor, student.id, "  Pupil ", 30)
    assert (created.visitor_type_id, created.name, created.discount_percent) == (
        student.id,
        "Pupil",
        30,
    )
    assert service.create_visitor_subtype(actor, student.id, "Adult").discount_percent == 0

    edited = service.edit_visitor_subtype(actor, student.id, created.id, discount_percent=40)
    assert (edited.name, edited.discount_percent) == ("Pupil", 40)
    renamed = service.edit_visitor_subtype(actor, student.id, created.id, name="Child")
    assert (renamed.id, renamed.name, renamed.discount_percent) == (created.id, "Child", 40)
    assert [subtype.name for subtype in service.list_visitor_subtypes(actor)] == ["Adult", "Child"]

    service.delete_visitor_subtype(actor, student.id, created.id)
    assert [subtype.name for subtype in service.list_visitor_subtypes(actor)] == ["Adult"]
    # Removing the type takes its subtypes with it.
    service.delete_visitor_type(actor, student.id)
    assert service.list_visitor_subtypes(actor) == []


def test_operators_read_subtypes_but_cannot_change_them(service, accounts):
    admin, operator = accounts["admin"], accounts["operator"]
    student = service.create_visitor_type(admin, "Student")
    pupil = service.create_visitor_subtype(admin, student.id, "Pupil", 10)

    assert service.list_visitor_subtypes(operator) == [pupil]
    for denied in (
        lambda: service.create_visitor_subtype(operator, student.id, "Adult"),
        lambda: service.edit_visitor_subtype(operator, student.id, pupil.id, discount_percent=1),
        lambda: service.delete_visitor_subtype(operator, student.id, pupil.id),
    ):
        with pytest.raises(PermissionDeniedError):
            denied()
    assert service.list_visitor_subtypes(admin) == [pupil]


def test_subtype_names_are_unique_across_every_type(service, accounts):
    admin = accounts["admin"]
    student = service.create_visitor_type(admin, "Student")
    staff = service.create_visitor_type(admin, "Staff")
    pupil = service.create_visitor_subtype(admin, student.id, "Pupil")
    teacher = service.create_visitor_subtype(admin, staff.id, "Teacher")
    with pytest.raises(ValueError, match="already exists"):
        service.create_visitor_subtype(admin, staff.id, " pupil ")
    with pytest.raises(ValueError, match="already exists"):
        service.edit_visitor_subtype(admin, staff.id, teacher.id, name="PUPIL")
    # Changing only the case of its own name is not a clash
    assert service.edit_visitor_subtype(admin, student.id, pupil.id, name="PUPIL").name == "PUPIL"


@pytest.mark.parametrize(("name", "percent"), [("", 0), (" ", 0), ("Pupil", -1), ("Pupil", 101)])
def test_invalid_subtypes_are_refused(service, accounts, name, percent):
    admin = accounts["admin"]
    student = service.create_visitor_type(admin, "Student")
    with pytest.raises(ValueError):
        service.create_visitor_subtype(admin, student.id, name, percent)
    pupil = service.create_visitor_subtype(admin, student.id, "Pupil")
    with pytest.raises(ValueError):
        service.edit_visitor_subtype(
            admin, student.id, pupil.id, name=name, discount_percent=percent
        )
    assert service.list_visitor_subtypes(admin) == [pupil]


def test_subtype_edits_need_a_change_and_a_subtype_of_that_type(service, accounts):
    admin = accounts["admin"]
    student = service.create_visitor_type(admin, "Student")
    staff = service.create_visitor_type(admin, "Staff")
    pupil = service.create_visitor_subtype(admin, student.id, "Pupil")
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_visitor_subtype(admin, student.id, pupil.id)
    with pytest.raises(NotFoundError, match="Visitor type not found"):
        service.create_visitor_subtype(admin, uuid4(), "Adult")
    for missing in (
        lambda: service.edit_visitor_subtype(admin, student.id, uuid4(), name="Adult"),
        lambda: service.delete_visitor_subtype(admin, student.id, uuid4()),
        # A subtype is only found under its own type.
        lambda: service.edit_visitor_subtype(admin, staff.id, pupil.id, name="Adult"),
        lambda: service.delete_visitor_subtype(admin, staff.id, pupil.id),
    ):
        with pytest.raises(NotFoundError, match="Visitor subtype not found"):
            missing()
    assert service.list_visitor_subtypes(admin) == [pupil]


def test_operators_read_the_catalog_but_cannot_change_it(service, accounts):
    admin, operator = accounts["admin"], accounts["operator"]
    ticket_type = service.create_ticket_type(admin, "Day", 100, Currency.USD)
    visitor_type = service.create_visitor_type(admin, "Student")

    assert service.list_ticket_types(operator) == [ticket_type]
    assert service.list_visitor_types(operator) == [visitor_type]
    for denied in (
        lambda: service.create_ticket_type(operator, "Night", 1, Currency.USD),
        lambda: service.edit_ticket_type(operator, ticket_type.id, price=1),
        lambda: service.delete_ticket_type(operator, ticket_type.id),
        lambda: service.create_visitor_type(operator, "Staff"),
        lambda: service.edit_visitor_type(operator, visitor_type.id, name="Pupil"),
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
        lambda service, actor: service.create_ticket_type(actor, "Day", 10**11 + 1, Currency.USD),
        lambda service, actor: service.create_visitor_type(actor, ""),
        lambda service, actor: service.create_visitor_type(actor, " "),
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

    student = service.create_visitor_type(admin, "Student")
    staff = service.create_visitor_type(admin, "Staff")
    with pytest.raises(ValueError, match="already exists"):
        service.create_visitor_type(admin, "student")
    with pytest.raises(ValueError, match="already exists"):
        service.edit_visitor_type(admin, staff.id, name="STUDENT")
    assert service.edit_visitor_type(admin, student.id, name="STUDENT").name == "STUDENT"


def test_edits_need_a_change_and_an_existing_entry(service, accounts):
    admin = accounts["admin"]
    day = service.create_ticket_type(admin, "Day", 100, Currency.USD)
    student = service.create_visitor_type(admin, "Student")
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_ticket_type(admin, day.id)
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_visitor_type(admin, student.id)
    for missing in (
        lambda: service.edit_ticket_type(admin, uuid4(), price=1),
        lambda: service.delete_ticket_type(admin, uuid4()),
        lambda: service.edit_visitor_type(admin, uuid4(), name="Pupil"),
        lambda: service.delete_visitor_type(admin, uuid4()),
    ):
        with pytest.raises(NotFoundError):
            missing()


def student_with(service, admin, *subtypes):
    """A Student visitor type with subtypes given as (name, discount) pairs."""
    student = service.create_visitor_type(admin, "Student")
    for name, percent in subtypes:
        service.create_visitor_subtype(admin, student.id, name, percent)
    return student


def test_ticket_price_is_the_type_price_less_the_subtype_discount(service, accounts, clock):
    admin = accounts["admin"]
    service.create_ticket_type(admin, "Day pass", 1250, Currency.USD)
    student_with(service, admin, ("Pupil", 20), ("Adult", 0))

    ticket = issue(
        service,
        accounts,
        clock,
        ticket_type="day pass",
        visitor_type="student",
        visitor_subtype=" pupil ",
    )

    assert ticket.ticket_type == "Day pass"
    # The ticket carries its subtype's name in the type's place.
    assert ticket.visitor_type == "Pupil"
    assert (ticket.base_price, ticket.discount_percent, ticket.price) == (1250, 20, 1000)
    assert ticket.currency == Currency.USD
    assert service.repository.get_ticket(ticket.id) == ticket


def test_visitor_types_outside_the_catalog_are_refused(service, accounts, clock):
    service.create_ticket_type(accounts["admin"], "Day pass", 1250, Currency.USD)

    with pytest.raises(ValueError, match="Unknown visitor type"):
        issue(service, accounts, clock, ticket_type="Day pass", visitor_type="Walk-in")
    assert service.repository.list_tickets() == []
    assert service.registrar.removed == []


@pytest.mark.parametrize(
    ("subtype", "message"),
    [
        (None, "A visitor subtype is required"),
        ("", "A visitor subtype is required"),
        ("  ", "A visitor subtype is required"),
        ("Nobody", "Unknown visitor subtype"),
        # A subtype of another visitor type does not do.
        ("Guest", "Unknown visitor subtype"),
    ],
)
def test_a_ticket_needs_a_subtype_of_its_visitor_type(service, accounts, clock, subtype, message):
    admin = accounts["admin"]
    guest = service.create_visitor_type(admin, "Guest")
    service.create_visitor_subtype(admin, guest.id, "Guest")
    student_with(service, admin, ("Pupil", 20))

    with pytest.raises(ValueError, match=message):
        issue(service, accounts, clock, visitor_type="Student", visitor_subtype=subtype)
    assert service.repository.list_tickets() == []
    assert service.registrar.removed == []


def test_tickets_without_a_ticket_type_have_no_price(service, accounts, clock):
    student_with(service, accounts["admin"], ("Pupil", 20))

    ticket = issue(service, accounts, clock, visitor_type="Student", visitor_subtype="Pupil")

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
    student = student_with(service, admin, ("Pupil", 50))
    (pupil,) = service.list_visitor_subtypes(admin)
    ticket = issue(
        service,
        accounts,
        clock,
        ticket_type="Day pass",
        visitor_type="Student",
        visitor_subtype="Pupil",
    )
    assert ticket.price == 500

    service.edit_ticket_type(admin, day.id, name="Daily", price=9999)
    service.edit_visitor_type(admin, student.id, name="Learner")
    service.edit_visitor_subtype(admin, student.id, pupil.id, name="Child", discount_percent=0)
    assert service.get_ticket(admin, ticket.id).price == 500

    service.delete_ticket_type(admin, day.id)
    service.delete_visitor_subtype(admin, student.id, pupil.id)
    service.delete_visitor_type(admin, student.id)
    kept = service.get_ticket(admin, ticket.id)
    assert (kept.ticket_type, kept.visitor_type, kept.price) == ("Day pass", "Pupil", 500)


def test_tickets_from_before_the_catalog_upgrade_without_a_price(
    service, accounts, clock, tmp_path
):
    guest = service.create_visitor_type(accounts["admin"], "Guest")
    service.create_visitor_subtype(accounts["admin"], guest.id, "Guest")
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
