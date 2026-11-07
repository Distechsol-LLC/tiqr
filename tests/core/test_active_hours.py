from datetime import UTC, datetime, time, timedelta

import pytest

from tiqr.core.models import ActiveHours, UsageType
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import OutsideActiveHoursError, PermissionDeniedError, TicketService

SECRET = "active-hours-suite-unique-signing-key"
# Baku is UTC+4 with no DST, so 10:00 UTC is 14:00 local
BAKU = "Asia/Baku"


def at_local(hour: int, minute: int = 0) -> datetime:
    """A UTC instant whose Baku wall-clock time is `hour:minute` on 17 September 2026."""
    return datetime(2026, 9, 17, hour, minute, tzinfo=UTC) - timedelta(hours=4)


@pytest.fixture
def staff_service(repository, clock, accounts):
    service = TicketService(repository, SECRET, clock=clock, timezone=BAKU)
    guest = service.create_visitor_type(accounts["admin"], "Guest")
    service.create_visitor_subtype(accounts["admin"], guest.id, "Guest")
    return service


def issue(service, accounts, clock, *, actor="operator", length=timedelta(hours=1)):
    return service.create_ticket(
        accounts[actor],
        visitor_name="Name",
        visitor_type="Guest",
        visitor_subtype="Guest",
        valid_from=clock.now,
        valid_until=clock.now + length,
        usage_type=UsageType.ONE_TIME,
    )


def test_a_window_may_close_exactly_when_the_hours_do():
    hours = ActiveHours(time(9), time(17))

    assert hours.allows_end(time(17))
    assert hours.allows_end(time(12))
    assert not hours.allows_end(time(17, 0, 1))
    assert not hours.allows_end(time(23, 59))
    assert ActiveHours(time(22), time(6)).allows_end(time(6))
    assert ActiveHours(time(18), time(0)).allows_end(time(0))


def test_a_limit_is_inclusive_at_the_start_and_exclusive_at_the_end():
    hours = ActiveHours(time(9), time(17))

    assert hours.allows(time(9))
    assert hours.allows(time(16, 59, 59))
    assert not hours.allows(time(8, 59, 59))
    assert not hours.allows(time(17))


def test_hours_that_end_before_they_start_run_past_midnight():
    night = ActiveHours(time(22), time(6))

    assert night.allows(time(23, 30))
    assert night.allows(time(0))
    assert night.allows(time(5, 59))
    assert not night.allows(time(6))
    assert not night.allows(time(12))


def test_hours_ending_at_midnight_run_to_the_end_of_the_day():
    evening = ActiveHours(time(18), time(0))

    assert evening.allows(time(23, 59, 59))
    assert not evening.allows(time(17, 59))


def test_hours_must_start_and_end_at_different_times():
    with pytest.raises(ValueError, match="different times"):
        ActiveHours(time(9), time(9))


@pytest.mark.parametrize("role", ["admin", "manager"])
def test_staff_set_the_hours_and_everyone_reads_them(staff_service, accounts, role):
    hours = staff_service.set_active_hours(accounts[role], time(9), time(17))

    assert hours == ActiveHours(time(9), time(17))
    assert staff_service.active_hours(accounts["operator"]) == hours
    assert staff_service.active_hours(accounts["admin"]) == hours


def test_operators_cannot_set_the_hours(staff_service, accounts):
    with pytest.raises(PermissionDeniedError):
        staff_service.set_active_hours(accounts["operator"], time(9), time(17))

    assert staff_service.active_hours(accounts["operator"]) is None


def test_setting_hours_needs_both_times_or_neither(staff_service, accounts):
    with pytest.raises(ValueError, match="both a start and an end"):
        staff_service.set_active_hours(accounts["admin"], time(9), None)
    with pytest.raises(ValueError, match="both a start and an end"):
        staff_service.set_active_hours(accounts["admin"], None, time(17))


def test_changing_the_hours_is_audited(staff_service, accounts):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))
    staff_service.set_active_hours(accounts["manager"], None, None)

    details = [
        entry.detail
        for entry in staff_service.audit_trail(accounts["admin"])
        if entry.action == "active_hours.set"
    ]
    assert details == ["09:00 to 17:00", "any time"]


def test_tickets_are_made_any_time_until_hours_are_set(staff_service, accounts, clock):
    clock.now = at_local(3)

    assert issue(staff_service, accounts, clock).visitor_type == "Guest"


def test_tickets_are_made_inside_the_hours_in_the_server_zone(
    staff_service, accounts, clock, repository
):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    clock.now = at_local(9)
    assert issue(staff_service, accounts, clock)
    clock.now = at_local(16, 59)
    assert issue(staff_service, accounts, clock, length=timedelta(minutes=1))


def test_tickets_are_refused_outside_the_hours_and_nothing_is_saved(
    staff_service, accounts, clock, repository
):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))
    before = len(repository.list_tickets())

    clock.now = at_local(17)
    with pytest.raises(
        OutsideActiveHoursError, match=r"from 09:00 to 17:00 .*Asia/Baku"
    ) as refused:
        issue(staff_service, accounts, clock)

    assert refused.value.code == "outside_active_hours"
    assert len(repository.list_tickets()) == before


def test_operators_are_held_to_the_hours_too(staff_service, accounts, clock):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    clock.now = at_local(20)
    with pytest.raises(OutsideActiveHoursError):
        issue(staff_service, accounts, clock, actor="operator")


def test_overnight_hours_admit_tickets_after_midnight(staff_service, accounts, clock):
    staff_service.set_active_hours(accounts["admin"], time(22), time(6))

    clock.now = at_local(1)
    assert issue(staff_service, accounts, clock)
    clock.now = at_local(12)
    with pytest.raises(OutsideActiveHoursError):
        issue(staff_service, accounts, clock)


def test_lifting_the_limit_allows_any_time_again(staff_service, accounts, clock):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))
    staff_service.set_active_hours(accounts["manager"], None, None)

    clock.now = at_local(20)
    assert issue(staff_service, accounts, clock)
    assert staff_service.active_hours(accounts["operator"]) is None


def test_the_hours_follow_the_servers_zone_not_utc(repository, clock, accounts):
    # 22:00 UTC is 02:00 in Baku, already outside 09:00 to 17:00 there
    service = TicketService(repository, SECRET, clock=clock, timezone=BAKU)
    guest = service.create_visitor_type(accounts["admin"], "Guest")
    service.create_visitor_subtype(accounts["admin"], guest.id, "Guest")
    service.set_active_hours(accounts["manager"], time(9), time(17))

    clock.now = datetime(2026, 9, 17, 22, tzinfo=UTC)
    with pytest.raises(OutsideActiveHoursError):
        issue(service, accounts, clock)


def test_an_unknown_timezone_is_refused_at_construction(repository, clock):
    with pytest.raises(ValueError, match="Unknown timezone"):
        TicketService(repository, SECRET, clock=clock, timezone="Mars/Olympus")


def test_a_new_database_starts_on_working_hours():
    with SQLiteRepository(":memory:") as repository:
        repository.initialize()

        assert repository.active_hours() == ActiveHours(time(9), time(17))


def test_any_time_is_kept_as_a_choice_not_reset_to_the_default():
    with SQLiteRepository(":memory:") as repository:
        repository.initialize()
        repository.save_active_hours(None)

        assert repository.active_hours() is None


def test_a_window_running_past_the_hours_is_refused_and_nothing_is_saved(
    staff_service, accounts, clock, repository
):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))
    before = len(repository.list_tickets())

    clock.now = at_local(10)
    with pytest.raises(OutsideActiveHoursError, match=r"access window .*09:00 to 17:00") as refused:
        issue(staff_service, accounts, clock, length=timedelta(hours=14))

    assert refused.value.code == "outside_active_hours"
    assert len(repository.list_tickets()) == before


def test_a_window_starting_before_the_hours_is_refused(staff_service, accounts, clock):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    clock.now = at_local(10)
    with pytest.raises(OutsideActiveHoursError):
        staff_service.create_ticket(
            accounts["operator"],
            visitor_type="Guest",
            visitor_subtype="Guest",
            valid_from=at_local(8),
            valid_until=at_local(12),
            usage_type=UsageType.ONE_TIME,
        )


def test_a_window_spanning_exactly_the_hours_is_accepted(staff_service, accounts, clock):
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    clock.now = at_local(10)
    ticket = staff_service.create_ticket(
        accounts["operator"],
        visitor_type="Guest",
        visitor_subtype="Guest",
        valid_from=at_local(9),
        valid_until=at_local(17),
        usage_type=UsageType.ONE_TIME,
    )

    assert ticket.valid_until == at_local(17)


def test_a_reissue_is_held_to_the_hours_for_the_ends_it_moves(staff_service, accounts, clock):
    clock.now = at_local(10)
    ticket = issue(staff_service, accounts, clock)
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    with pytest.raises(OutsideActiveHoursError, match="access window"):
        staff_service.reissue_ticket(
            accounts["manager"], ticket.id, valid_from=at_local(9), valid_until=at_local(23, 59)
        )
    with pytest.raises(OutsideActiveHoursError):
        staff_service.reissue_ticket(
            accounts["manager"], ticket.id, valid_from=at_local(8), valid_until=at_local(12)
        )

    moved = staff_service.reissue_ticket(
        accounts["manager"], ticket.id, valid_from=at_local(9), valid_until=at_local(17)
    )
    assert moved.valid_until == at_local(17)


def test_a_reissue_leaving_the_window_alone_is_not_held_to_hours_set_after_it(
    staff_service, accounts, clock
):
    clock.now = at_local(10)
    ticket = staff_service.create_ticket(
        accounts["operator"],
        visitor_type="Guest",
        visitor_subtype="Guest",
        valid_from=at_local(10),
        valid_until=at_local(23, 59),
        usage_type=UsageType.ONE_TIME,
    )
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    assert staff_service.reissue_ticket(accounts["manager"], ticket.id).valid_until == at_local(
        23, 59
    )
    # Moving only the start leaves the old end alone too
    assert staff_service.reissue_ticket(
        accounts["manager"], ticket.id, valid_from=at_local(11), valid_until=at_local(23, 59)
    )


def test_moving_a_validity_window_is_held_to_the_hours(staff_service, accounts, clock):
    clock.now = at_local(10)
    ticket = issue(staff_service, accounts, clock)
    staff_service.set_active_hours(accounts["manager"], time(9), time(17))

    with pytest.raises(OutsideActiveHoursError):
        staff_service.update_validity(accounts["manager"], ticket.id, valid_until=at_local(20))

    assert staff_service.update_validity(
        accounts["manager"], ticket.id, valid_until=at_local(15)
    ).valid_until == at_local(15)
