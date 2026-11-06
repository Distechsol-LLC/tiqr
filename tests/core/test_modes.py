"""Badge and ticket modes: what each issues, group tickets, and switching between databases."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import SECRET
from tiqr.core import pdf
from tiqr.core.auth import AuthenticationError
from tiqr.core.models import Currency, Mode, Outcome, RawEvent, Role, TicketState, UsageType
from tiqr.core.repository import SQLiteRepository
from tiqr.core.runtime import open_service
from tiqr.core.service import ModeError, PermissionDeniedError, StateError
from tiqr.core.settings import Settings, adopt_legacy_database, database_path

_MEDIA_BOX = re.compile(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]")


def page_mm(path):
    """The single page's size in whole millimetres; the PDFs are written uncompressed."""
    (box,) = _MEDIA_BOX.findall(path.read_bytes())
    return tuple(round(float(points) / 72 * 25.4) for points in box)


@pytest.fixture(autouse=True)
def catalog(service, accounts):
    student = service.create_visitor_type(accounts["admin"], "Student")
    service.create_visitor_subtype(accounts["admin"], student.id, "Student", 50)
    service.create_ticket_type(accounts["admin"], "Entry", 1001, Currency.AZN)


def create(service, accounts, clock, **fields):
    # Tickets are issued for a subtype; badges take none.
    subtype = "Student" if service.mode == Mode.TICKET else None
    return service.create_ticket(
        accounts["operator"],
        **{
            "visitor_type": "Student",
            "visitor_subtype": subtype,
            "valid_from": clock.now - timedelta(hours=1),
            "valid_until": clock.now + timedelta(hours=1),
            "usage_type": UsageType.ONE_TIME,
        }
        | fields,
    )


def scan(service, ticket, at, event_id):
    service.event_source.events.append(RawEvent(event_id, ticket.external_id, at, True))


def test_tickets_name_nobody_and_admit_once_or_per_person(service, accounts, clock):
    one = create(service, accounts, clock, visitor_name="Dropped")
    group = create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=4)
    assert (one.visitor_name, one.group_size) == ("", 1)
    assert (group.usage_type, group.group_size) == (UsageType.GROUP, 4)
    with pytest.raises(ModeError, match="one-time or for a group"):
        create(service, accounts, clock, usage_type=UsageType.MULTI_USE)
    for size in (1, 1001):
        with pytest.raises(ValueError, match="A group is from 2"):
            create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=size)
    with pytest.raises(ModeError, match="Only a group"):
        create(service, accounts, clock, group_size=2)


def test_badges_name_their_visitor_and_carry_no_price(service, accounts, clock):
    service.mode = Mode.BADGE
    badge = create(service, accounts, clock, visitor_name=" Ada ", usage_type=UsageType.MULTI_USE)
    # The catalog's discount is for priced tickets; a badge has no price to take it off.
    assert (badge.visitor_name, badge.discount_percent, badge.price) == ("Ada", 0, None)
    with pytest.raises(ValueError, match="Visitor name"):
        create(service, accounts, clock, usage_type=UsageType.MULTI_USE)
    with pytest.raises(ModeError, match="always multi-use"):
        create(service, accounts, clock, visitor_name="Ada")
    with pytest.raises(ModeError, match="no ticket types"):
        create(
            service,
            accounts,
            clock,
            visitor_name="Ada",
            usage_type=UsageType.MULTI_USE,
            ticket_type="Entry",
        )
    admin = accounts["admin"]
    with pytest.raises(ModeError):
        service.create_ticket_type(admin, "Other", 100, Currency.AZN)
    with pytest.raises(ModeError):
        service.create_visitor_type(admin, "Discounted", 10)
    staff = service.create_visitor_type(admin, "Staff")
    assert staff.discount_percent == 0


def test_badges_have_no_visitor_subtypes(service, accounts, clock):
    admin = accounts["admin"]
    student = service.repository.visitor_type_by_name("Student")
    (subtype,) = service.list_visitor_subtypes(admin)
    service.mode = Mode.BADGE
    # The tickets' subtypes are out of sight, and none can be added, changed or removed.
    assert service.list_visitor_subtypes(admin) == []
    for refused in (
        lambda: service.create_visitor_subtype(admin, student.id, "Adult"),
        lambda: service.edit_visitor_subtype(admin, student.id, subtype.id, name="Adult"),
        lambda: service.delete_visitor_subtype(admin, student.id, subtype.id),
        lambda: create(
            service,
            accounts,
            clock,
            visitor_name="Ada",
            usage_type=UsageType.MULTI_USE,
            visitor_subtype="Student",
        ),
    ):
        with pytest.raises(ModeError, match="no visitor subtypes"):
            refused()
    # A badge carries the type itself.
    badge = create(service, accounts, clock, visitor_name="Ada", usage_type=UsageType.MULTI_USE)
    assert (badge.visitor_type, badge.discount_percent) == ("Student", 0)
    service.mode = Mode.TICKET
    assert service.list_visitor_subtypes(admin) == [subtype]


def test_a_group_pays_and_counts_once_per_person(service, accounts, clock):
    group = create(
        service, accounts, clock, usage_type=UsageType.GROUP, group_size=10, ticket_type="Entry"
    )
    single = create(service, accounts, clock, ticket_type="Entry")
    # Half of 10.01, rounded half up, is 5.01 a person.
    assert (single.price, group.price) == (501, 5010)
    stats = service.stats(accounts["admin"])
    assert (stats["total"], stats["issued"]) == (11, 11)
    assert stats["visitor_types"]["Student"]["ticket_types"]["Entry"]["total"] == 11


def test_a_group_admits_its_size_then_stops(service, accounts, clock):
    group = create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=3)
    for index in range(4):
        scan(service, group, clock.now, f"g{index}")
    service.sync(accounts["admin"])
    outcomes = [event.outcome for event in service.repository.list_events()]
    assert outcomes == [Outcome.APPLIED] * 3 + [Outcome.IGNORED_SECOND_ONE_TIME_SCAN]
    stored = service.repository.get_ticket(group.id)
    assert (stored.state, stored.use_count, stored.is_spent) == (TicketState.PASSED, 3, True)
    assert service.registrar.deactivated == [group.external_id]
    stats = service.stats(accounts["admin"])
    assert (stats["passed"], stats["passes"]) == (3, 3)
    assert service.cleanup(accounts["admin"]) == 1


def test_a_partly_used_group_can_still_be_changed(service, accounts, clock):
    group = create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=2)
    scan(service, group, clock.now, "g0")
    service.sync(accounts["admin"])
    later = group.valid_until + timedelta(hours=1)
    assert service.update_validity(accounts["admin"], group.id, valid_until=later).valid_until == (
        later
    )
    assert service.registrar.deactivated == []


def test_the_ticket_prints_on_a_narrow_slip(service, accounts, clock, tmp_path):
    group = create(
        service, accounts, clock, usage_type=UsageType.GROUP, group_size=10, ticket_type="Entry"
    )
    assert page_mm(service.print_ticket(accounts["admin"], group.id, tmp_path)) == (80, 160)
    service.mode = Mode.BADGE
    badge = create(service, accounts, clock, visitor_name="Ada", usage_type=UsageType.MULTI_USE)
    # A badge is the foldable A4 sheet.
    assert page_mm(service.print_ticket(accounts["admin"], badge.id, tmp_path)) == (210, 297)


def test_the_ticket_says_how_many_people_a_group_admits(service, accounts, clock):
    group = create(
        service, accounts, clock, usage_type=UsageType.GROUP, group_size=100, ticket_type="Entry"
    )
    assert pdf._admits(group) == "GROUP · 100 PEOPLE"
    assert pdf._admits(group, "az") == "QRUP · 100 NƏFƏR"
    assert pdf._admits(group, "kk") == "ТОП · 100 АДАМ"


@pytest.mark.parametrize(
    ("count", "people"), [(2, "ЧЕЛОВЕКА"), (5, "ЧЕЛОВЕК"), (12, "ЧЕЛОВЕК"), (22, "ЧЕЛОВЕКА")]
)
def test_russian_group_sizes_take_the_right_case(count, people):
    assert pdf._russian_people(count) == people


@pytest.mark.parametrize(
    ("asked", "expected"), [("ru", "ru"), ("ru-RU", "ru"), ("kk", "en"), (None, "en")]
)
def test_the_ticket_speaks_the_apps_language_when_the_install_offers_it(asked, expected):
    assert pdf._ticket_language(("en-US", "ru-RU"), asked) == expected


@pytest.fixture
def settings(tmp_path):
    return Settings(
        secret_key=SECRET, database_path=tmp_path / "tiqr_ticket.db", output_dir=tmp_path / "out"
    )


def prepare(service):
    """A first admin, with the hours lifted and a visitor type, in the mode's database."""
    admin = service.repository.user_by_name("admin") or service.add_user(
        "admin", "admin-password", Role.ADMIN
    )
    service.repository.save_active_hours(None)
    if service.repository.visitor_type_by_name("Guest") is None:
        guest = service.create_visitor_type(admin, "Guest")
        if service.mode == Mode.TICKET:
            service.create_visitor_subtype(admin, guest.id, "Guest")
    return admin


def make(service, admin, **fields):
    now = datetime.now(UTC).replace(microsecond=0)
    subtype = "Guest" if service.mode == Mode.TICKET else None
    return service.create_ticket(
        admin,
        visitor_type="Guest",
        visitor_subtype=subtype,
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        **fields,
    )


def test_each_mode_keeps_its_own_database_and_shares_the_accounts(settings, tmp_path):
    saved = []
    with open_service(settings, saved.append) as service:
        admin = prepare(service)
        token, _ = service.open_web_session(admin)
        ticket = make(service, admin, usage_type=UsageType.ONE_TIME)

        assert service.mode_switch.switch(admin, Mode.BADGE) == Mode.BADGE
        assert (service.mode, saved) == (Mode.BADGE, [Mode.BADGE])
        assert (tmp_path / "tiqr_badge.db").is_file()
        # Still signed in, with nothing of the tickets' in sight.
        assert service.resume_web_session(token)[0].id == admin.id
        assert service.list_tickets(admin) == []
        operator = service.add_user("op", "operator-password", Role.OPERATOR)
        prepare(service)
        badge = make(service, admin, visitor_name="Ada", usage_type=UsageType.MULTI_USE)
        # One BioStar holds both, so serials never repeat across the modes.
        assert badge.readable_serial != ticket.readable_serial
        assert badge.qr_payload != ticket.qr_payload

        service.mode_switch.switch(admin, Mode.TICKET)
        assert [found.id for found in service.list_tickets(admin)] == [ticket.id]
        assert service.find_user("op").id == operator.id
        # Switching to the mode already on changes nothing.
        service.mode_switch.switch(admin, Mode.TICKET)
        assert saved == [Mode.BADGE, Mode.TICKET]
        actions = [entry.action for entry in service.audit_trail(admin)]
        assert actions.count("mode.switch") == 1


def test_only_an_admin_switches(settings):
    with open_service(settings, None) as service:
        admin = prepare(service)
        manager = service.create_user(admin, "manager", "manager-password", Role.MANAGER)
        with pytest.raises(PermissionDeniedError):
            service.mode_switch.switch(manager, Mode.BADGE)
        assert service.mode == Mode.TICKET


def test_a_mirror_keeps_accounts_the_other_database_still_needs(settings):
    with open_service(settings, None) as service:
        admin = prepare(service)
        guest = service.add_user("guest", "guest-password", Role.OPERATOR)
        service.mode_switch.switch(admin, Mode.BADGE)
        prepare(service)
        make(service, guest, visitor_name="Ada", usage_type=UsageType.MULTI_USE)
        service.mode_switch.switch(admin, Mode.TICKET)
        # Gone from the tickets' database, and the name given to someone else...
        service.edit_user(guest.id, active=False)
        service.remove_user(guest.id)
        newcomer = service.add_user("guest", "other-password", Role.OPERATOR)
        token, _ = service.open_web_session(newcomer)
        service.mode_switch.switch(admin, Mode.BADGE)
        # ...the badge that names the old account keeps it, deactivated and renamed.
        kept = service.repository.user_by_id(guest.id)
        assert (kept.active, kept.username) == (False, f"guest~{str(guest.id)[:8]}")
        assert service.find_user("guest").id == newcomer.id
        assert service.resume_web_session(token)[0].id == newcomer.id
        with pytest.raises(AuthenticationError):
            service.authenticate(kept.username, "guest-password")


def test_the_single_database_of_earlier_releases_becomes_the_ticket_one(tmp_path):
    legacy = tmp_path / "tiqr.db"
    with SQLiteRepository(legacy) as repository:
        repository.initialize()
    (tmp_path / "tiqr.db-wal").write_bytes(b"")
    assert adopt_legacy_database(tmp_path)
    assert not legacy.exists()
    assert database_path(Mode.TICKET, tmp_path).is_file()
    assert (tmp_path / "tiqr_ticket.db-wal").exists()
    # Never over a ticket database that already exists.
    legacy.write_bytes(b"older")
    assert not adopt_legacy_database(tmp_path)
    assert legacy.read_bytes() == b"older"


def test_the_mode_is_read_from_the_environment(monkeypatch, project_root):
    monkeypatch.setenv("TIQR_SECRET_KEY", SECRET)
    monkeypatch.setenv("TIQR_MODE", "badge")
    settings = Settings.from_env()
    assert (settings.mode, settings.database_path) == (Mode.BADGE, project_root / "tiqr_badge.db")
    monkeypatch.setenv("TIQR_MODE", "festival")
    with pytest.raises(ValueError, match="TIQR_MODE"):
        Settings.from_env()


def test_a_reissue_changes_a_groups_visitors_and_the_price_follows(service, accounts, clock):
    ticket = create(
        service, accounts, clock, usage_type=UsageType.GROUP, group_size=2, ticket_type="Entry"
    )
    group = service.reissue_ticket(accounts["operator"], ticket.id, group_size=3)
    assert (group.usage_type, group.group_size, group.price) == (UsageType.GROUP, 3, 1503)
    detail = service.repository.list_audit(ticket.id)[-1].detail
    assert "group_size 2 -> 3; price 1002 -> 1503" in detail
    for size in (0, 101):
        with pytest.raises(ValueError, match="from 2 to 100"):
            service.reissue_ticket(accounts["operator"], ticket.id, group_size=size)


def test_a_reissue_never_turns_a_group_into_one_time_or_back(service, accounts, clock):
    group = create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=3)
    with pytest.raises(ValueError, match="from 2 to 100"):
        service.reissue_ticket(accounts["operator"], group.id, group_size=1)
    single = create(service, accounts, clock)
    with pytest.raises(ValueError, match="Only a group ticket"):
        service.reissue_ticket(accounts["operator"], single.id, group_size=3)
    # Its own size is no change, so the reissue itself still goes through.
    again = service.reissue_ticket(accounts["operator"], single.id, group_size=1)
    assert (again.usage_type, again.group_size) == (UsageType.ONE_TIME, 1)


def test_the_visitors_cannot_change_once_the_window_has_ended(service, accounts, clock):
    ticket = create(service, accounts, clock, usage_type=UsageType.GROUP, group_size=2)
    clock.now = ticket.valid_until + timedelta(minutes=1)
    later = clock.now + timedelta(hours=1)
    with pytest.raises(StateError, match="window has ended"):
        service.reissue_ticket(accounts["admin"], ticket.id, valid_until=later, group_size=4)
    # The same size is no change, so the reissue itself still goes through.
    again = service.reissue_ticket(accounts["admin"], ticket.id, valid_until=later, group_size=2)
    assert (again.state, again.group_size) == (TicketState.ISSUED, 2)


def test_a_badge_admits_one_person_whatever_a_reissue_asks(service, accounts, clock):
    service.mode = Mode.BADGE
    badge = create(service, accounts, clock, visitor_name="Ada", usage_type=UsageType.MULTI_USE)
    with pytest.raises(ModeError, match="always multi-use"):
        service.reissue_ticket(accounts["admin"], badge.id, group_size=2)
