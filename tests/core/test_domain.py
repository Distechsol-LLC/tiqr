from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from tiqr.core.fakes import InMemoryEventSource, InMemoryRegistrar
from tiqr.core.localtime import day_start
from tiqr.core.models import Mode, Outcome, RawEvent, TicketState, UsageType
from tiqr.core.service import StateError


@pytest.fixture(autouse=True)
def visitor_types(service, accounts):
    for name in ("Student", "Guest"):
        visitor_type = service.create_visitor_type(accounts["admin"], name)
        service.create_visitor_subtype(accounts["admin"], visitor_type.id, name)


def issue(service, accounts, clock, usage=UsageType.ONE_TIME, actor="operator"):
    # Multi-use passes are badges; the rest are tickets. Passages work alike in either mode.
    service.mode = Mode.BADGE if usage == UsageType.MULTI_USE else Mode.TICKET
    return service.create_ticket(
        accounts[actor],
        visitor_name="Visitor",
        visitor_type="Student",
        visitor_subtype="Student" if service.mode == Mode.TICKET else None,
        valid_from=clock.now - timedelta(hours=1),
        valid_until=clock.now + timedelta(hours=1),
        usage_type=usage,
    )


def scan(service, ticket, at, event_id="1", granted=True):
    service.event_source.events.append(RawEvent(event_id, ticket.external_id, at, granted))


def test_search_matches_serial_visitor_and_type_ignoring_case(service, accounts, clock):
    admin = accounts["admin"]
    # Only badges carry a visitor's name.
    service.mode = Mode.BADGE
    ada = service.create_ticket(
        accounts["operator"],
        visitor_name="Ada Lovelace",
        visitor_type="Guest",
        valid_from=clock.now - timedelta(hours=1),
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.MULTI_USE,
    )
    student = issue(service, accounts, clock)
    assert [t.id for t in service.list_tickets(admin, search="  LOVELACE ")] == [ada.id]
    assert [t.id for t in service.list_tickets(admin, search="guest")] == [ada.id]
    assert [t.id for t in service.list_tickets(admin, search=student.readable_serial)] == [
        student.id
    ]
    assert [t.id for t in service.list_tickets(admin, TicketState.ISSUED, "student")] == [
        student.id
    ]
    assert len(service.list_tickets(admin, search="  ")) == 2
    assert service.list_tickets(admin, search="nobody") == []


def test_granted_pass_uses_scan_time(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    happened = clock.now - timedelta(minutes=3)
    scan(service, ticket, happened)
    assert service.sync(accounts["manager"]) == 1
    passed = service.get_ticket(accounts["operator"], ticket.id)
    assert passed.state == TicketState.PASSED
    assert passed.passed_at == happened
    assert passed.use_count == 1
    assert service.repository.get_event("1").processed_at == clock.now
    assert service.registrar.deactivated == [ticket.external_id]


@pytest.mark.parametrize("boundary", ["valid_from", "valid_until"])
def test_inclusive_boundaries(service, accounts, clock, boundary):
    ticket = issue(service, accounts, clock)
    at = getattr(ticket, boundary)
    if boundary == "valid_until":
        clock.now = at
    scan(service, ticket, at)
    service.sync(accounts["admin"])
    passed = service.get_ticket(accounts["admin"], ticket.id)
    assert passed.state == TicketState.PASSED
    assert passed.passed_at == at
    assert service.repository.get_event("1").outcome == Outcome.APPLIED


@pytest.mark.parametrize(("boundary", "offset"), [("valid_from", -1), ("valid_until", 1)])
def test_outside_window(service, accounts, clock, boundary, offset):
    ticket = issue(service, accounts, clock)
    scan(service, ticket, getattr(ticket, boundary) + timedelta(microseconds=offset))
    service.sync(accounts["manager"])
    assert service.get_ticket(accounts["manager"], ticket.id) == ticket
    assert service.repository.get_event("1").outcome == Outcome.IGNORED_OUTSIDE_WINDOW
    assert service.registrar.deactivated == []


def test_denied_changes_nothing(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    scan(service, ticket, clock.now, granted=False)
    service.sync(accounts["manager"])
    assert service.get_ticket(accounts["manager"], ticket.id) == ticket
    assert service.repository.get_event("1").outcome == Outcome.DENIED
    assert service.registrar.deactivated == []


@pytest.mark.parametrize("external_id", [None, "unknown"])
def test_unknown_grant(service, accounts, clock, external_id):
    service.event_source.events.append(RawEvent("1", external_id, clock.now, True))
    service.sync(accounts["admin"])
    event = service.repository.get_event("1")
    assert event.outcome == Outcome.IGNORED_UNKNOWN_TICKET
    assert event.ticket_id is None


def test_one_time_second_grant_ignored(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    scan(service, ticket, clock.now, "1")
    scan(service, ticket, clock.now + timedelta(seconds=1), "2")
    service.sync(accounts["admin"])
    assert service.repository.get_event("2").outcome == Outcome.IGNORED_SECOND_ONE_TIME_SCAN
    assert service.get_ticket(accounts["admin"], ticket.id).use_count == 1
    assert service.registrar.deactivated == [ticket.external_id]


def test_multi_use_counts_every_grant_but_not_denials(service, accounts, clock):
    ticket = issue(service, accounts, clock, UsageType.MULTI_USE)
    for index in (3, 1, 2):
        scan(service, ticket, clock.now - timedelta(seconds=4 - index), str(index))
    scan(service, ticket, clock.now, "4", False)
    service.sync(accounts["manager"])
    passed = service.get_ticket(accounts["manager"], ticket.id)
    assert passed.state == TicketState.PASSED
    assert passed.use_count == 3
    assert passed.passed_at == clock.now - timedelta(seconds=3)
    assert service.registrar.deactivated == []
    assert service.registrar.windows[ticket.external_id] == (ticket.valid_from, ticket.valid_until)


def test_multi_use_outside_window_not_counted(service, accounts, clock):
    ticket = issue(service, accounts, clock, UsageType.MULTI_USE)
    scan(service, ticket, clock.now, "1")
    service.sync(accounts["admin"])
    scan(service, ticket, ticket.valid_until + timedelta(seconds=1), "2")
    service.sync(accounts["admin"])
    assert service.get_ticket(accounts["admin"], ticket.id).use_count == 1
    assert service.repository.get_event("2").outcome == Outcome.IGNORED_OUTSIDE_WINDOW


@pytest.mark.parametrize("passed", [False, True])
@pytest.mark.parametrize("action", ["read", "list", "sync", "cleanup", "stats"])
def test_expiry_persists_for_issued_and_passed(service, accounts, clock, passed, action):
    ticket = issue(service, accounts, clock, UsageType.MULTI_USE)
    if passed:
        scan(service, ticket, clock.now)
        service.sync(accounts["admin"])
    clock.now = ticket.valid_until
    assert service.get_ticket(accounts["admin"], ticket.id).state != TicketState.EXPIRED
    clock.now += timedelta(microseconds=1)
    if action == "read":
        service.get_ticket(accounts["admin"], ticket.id)
    elif action == "list":
        assert service.list_tickets(accounts["admin"], TicketState.EXPIRED)[0].id == ticket.id
    else:
        getattr(service, action)(accounts["admin"])
    expired = service.repository.get_ticket(ticket.id)
    assert expired.state == TicketState.EXPIRED
    clock.now = ticket.created_at
    assert service.get_ticket(accounts["admin"], ticket.id).state == TicketState.EXPIRED


def test_grant_on_expired_ignored_even_if_scan_was_in_window(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    scan(service, ticket, ticket.valid_until)
    clock.now = ticket.valid_until + timedelta(microseconds=1)
    service.sync(accounts["manager"])
    assert service.repository.get_event("1").outcome == Outcome.IGNORED_EXPIRED
    assert service.repository.get_ticket(ticket.id).passed_at is None
    assert service.registrar.deactivated == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (TicketState.ISSUED, TicketState.ISSUED),
        (TicketState.PASSED, TicketState.ISSUED),
        (TicketState.PASSED, TicketState.PASSED),
        (TicketState.EXPIRED, TicketState.ISSUED),
        (TicketState.EXPIRED, TicketState.PASSED),
        (TicketState.EXPIRED, TicketState.EXPIRED),
    ],
)
def test_illegal_transitions(service, accounts, clock, before, after):
    ticket = replace(issue(service, accounts, clock), state=before)
    with pytest.raises(StateError):
        service._transition(ticket, after)


def test_models_are_immutable(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    with pytest.raises(FrozenInstanceError):
        ticket.state = TicketState.PASSED


def test_sync_idempotent_in_batch_and_across_runs(service, accounts, clock):
    ticket = issue(service, accounts, clock, UsageType.MULTI_USE)
    scan(service, ticket, clock.now)
    scan(service, ticket, clock.now)
    assert service.sync(accounts["manager"]) == 1
    before = service.get_ticket(accounts["manager"], ticket.id)
    events = service.repository.list_events()
    cursor = service.repository.get_cursor()
    assert service.sync(accounts["manager"]) == 0
    assert service.get_ticket(accounts["manager"], ticket.id) == before
    assert service.repository.list_events() == events
    assert service.repository.get_cursor() == cursor
    assert service.event_source.cursors == [None, cursor]


def test_concurrent_sync_is_idempotent(service, accounts, clock):
    ticket = issue(service, accounts, clock)
    scan(service, ticket, clock.now)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.sync(accounts["manager"]), range(2)))
    assert sorted(results) == [0, 1]
    assert service.repository.get_ticket(ticket.id).use_count == 1
    assert service.registrar.deactivated == [ticket.external_id]


def test_deactivation_failure_does_not_commit_event_or_cursor(service, accounts, clock):
    class FailingRegistrar(InMemoryRegistrar):
        fail = True

        def deactivate(self, external_id):
            if self.fail:
                raise RuntimeError("offline")
            super().deactivate(external_id)

    service.registrar = FailingRegistrar()
    ticket = issue(service, accounts, clock)
    scan(service, ticket, clock.now)
    with pytest.raises(RuntimeError, match="offline"):
        service.sync(accounts["admin"])
    assert service.repository.get_ticket(ticket.id) == ticket
    assert service.repository.get_event("1") is None
    assert service.repository.get_cursor() is None
    service.registrar.fail = False
    assert service.sync(accounts["admin"]) == 1
    assert service.repository.get_ticket(ticket.id).use_count == 1


def test_expiry_survives_fetch_failure(service, accounts, clock):
    class FailedSource(InMemoryEventSource):
        def fetch_events(self, cursor):
            raise RuntimeError("offline")

    ticket = issue(service, accounts, clock)
    service.event_source = FailedSource()
    clock.now = ticket.valid_until + timedelta(seconds=1)
    with pytest.raises(RuntimeError):
        service.sync(accounts["admin"])
    assert service.repository.get_ticket(ticket.id).state == TicketState.EXPIRED


def test_cleanup_selection_retains_history_and_is_repeatable(service, accounts, clock):
    expired_issued = issue(service, accounts, clock)
    spent = issue(service, accounts, clock)
    reusable = issue(service, accounts, clock, UsageType.MULTI_USE)
    untouched = issue(service, accounts, clock, UsageType.MULTI_USE)
    scan(service, spent, clock.now, "1")
    scan(service, reusable, clock.now, "2")
    service.sync(accounts["admin"])
    assert service.cleanup(accounts["manager"]) == 1
    assert service.registrar.removed == [spent.external_id]
    assert service.cleanup(accounts["manager"]) == 0
    clock.now = expired_issued.valid_until + timedelta(seconds=1)
    assert service.cleanup(accounts["manager"]) == 3
    assert set(service.registrar.removed) == {
        ticket.external_id for ticket in (expired_issued, spent, reusable, untouched)
    }
    assert len(service.repository.list_tickets()) == 4
    assert len(service.repository.list_events()) == 2


def test_cleanup_failure_is_retryable_and_expiry_persisted(service, accounts, clock):
    class FailedRemoval(InMemoryRegistrar):
        fail = True

        def remove(self, external_id):
            if self.fail:
                raise RuntimeError("offline")
            super().remove(external_id)

    service.registrar = FailedRemoval()
    ticket = issue(service, accounts, clock)
    clock.now = ticket.valid_until + timedelta(seconds=1)
    with pytest.raises(RuntimeError):
        service.cleanup(accounts["admin"])
    assert service.repository.get_ticket(ticket.id).state == TicketState.EXPIRED
    assert not service.repository.is_cleaned(ticket.id)
    service.registrar.fail = False
    assert service.cleanup(accounts["admin"]) == 1


def test_window_failure_rolls_back_and_serial_is_not_reused(service, accounts, clock):
    class FailedWindow(InMemoryRegistrar):
        def set_window(self, external_id, start, end):
            raise RuntimeError("offline")

    service.registrar = FailedWindow()
    with pytest.raises(RuntimeError):
        issue(service, accounts, clock)
    assert service.repository.list_tickets() == []
    assert len(service.registrar.removed) == 1
    service.registrar = InMemoryRegistrar()
    assert issue(service, accounts, clock).readable_serial.endswith("00002")


@pytest.mark.parametrize(
    "change",
    [
        {"usage_type": UsageType.MULTI_USE},
        {"usage_type": UsageType.ONE_TIME, "group_size": 3},
        {"usage_type": UsageType.GROUP, "group_size": 1},
        {"visitor_type": ""},
        {"usage_type": "bogus"},
        {"valid_until": "past"},
        {"valid_from": "naive"},
    ],
)
def test_invalid_creation(service, accounts, clock, change):
    draft = {
        "visitor_name": "Visitor",
        "visitor_type": "Guest",
        "visitor_subtype": "Guest",
        "valid_from": clock.now,
        "valid_until": clock.now + timedelta(hours=1),
        "usage_type": UsageType.ONE_TIME,
    }
    if change.get("valid_until") == "past":
        change = {"valid_until": clock.now - timedelta(seconds=1)}
    if change.get("valid_from") == "naive":
        change = {"valid_from": clock.now.replace(tzinfo=None)}
    with pytest.raises(ValueError):
        service.create_ticket(accounts["operator"], **(draft | change))
    assert service.repository.list_tickets() == []
    assert service.registrar.tickets == {}


@pytest.mark.parametrize(
    ("timezone", "start"),
    [
        ("UTC", datetime(2026, 9, 17, tzinfo=UTC)),
        # Baku is four hours ahead, so its day starts at 20:00 UTC the day before.
        ("Asia/Baku", datetime(2026, 9, 16, 20, tzinfo=UTC)),
        # Paris is on summer time in September and winter time in January.
        ("Europe/Paris", datetime(2026, 9, 16, 22, tzinfo=UTC)),
    ],
)
def test_day_starts_at_local_midnight(timezone, start):
    assert day_start(date(2026, 9, 17), timezone) == start
    assert day_start(date(2026, 1, 1), "Europe/Paris") == datetime(2025, 12, 31, 23, tzinfo=UTC)


def test_stats_count_only_tickets_created_within_the_dates(service, accounts, clock):
    for created in (
        datetime(2025, 12, 31, 12, tzinfo=UTC),
        datetime(2026, 8, 31, 12, tzinfo=UTC),
        datetime(2026, 9, 16, 21, tzinfo=UTC),
        datetime(2026, 9, 17, 9, tzinfo=UTC),
    ):
        clock.now = created
        issue(service, accounts, clock)
    admin = accounts["admin"]

    def total(since=None, until=None, timezone="UTC"):
        return service.stats(admin, since=since, until=until, timezone=timezone)["total"]

    assert total() == 4
    assert total(date(2026, 1, 1), date(2026, 12, 31)) == 3
    assert total(date(2026, 9, 1), date(2026, 9, 30)) == 2
    assert total(date(2026, 9, 17), date(2026, 9, 17)) == 1
    # Either end may stay open, and both are inclusive.
    assert total(since=date(2026, 8, 31)) == 3
    assert total(until=date(2026, 8, 31)) == 2
    # By Baku's clock, 21:00 UTC on the 16th was already the 17th.
    assert total(date(2026, 9, 17), date(2026, 9, 17), "Asia/Baku") == 2
    day = service.stats(admin, since=date(2026, 9, 17), until=date(2026, 9, 17))
    assert day["visitor_types"]["Student"]["total"] == 1
    assert sum(counts["total"] for counts in day["ticket_types"].values()) == day["total"]
    for visitor in day["visitor_types"].values():
        assert (
            sum(counts["total"] for counts in visitor["ticket_types"].values()) == visitor["total"]
        )
    with pytest.raises(ValueError, match="before the start"):
        total(date(2026, 9, 2), date(2026, 9, 1))
