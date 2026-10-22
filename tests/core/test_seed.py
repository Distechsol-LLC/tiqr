from dataclasses import replace

import pytest

from tiqr.core import seed
from tiqr.core.auth import new_user
from tiqr.core.models import Outcome, Role, TicketState
from tiqr.core.qr import verify_payload
from tiqr.core.repository import SQLiteRepository
from tiqr.core.seed import DEACTIVATED_OPERATOR, OPERATORS, SeedError, seed_demo
from tiqr.core.service import TicketService

SECRET = "development-only-64e2d7e02b9f49828c52d840565de390"
PASSWORD = "demo-password"


@pytest.fixture
def seeded(repository, clock, accounts):
    report = seed_demo(repository, SECRET, PASSWORD, clock=clock)
    return repository, report


@pytest.fixture
def reader(repository, clock):
    return TicketService(repository, SECRET, clock=clock)


def by_visitor(tickets):
    return {ticket.visitor_name: ticket for ticket in tickets}


def test_seed_adds_operators_and_keeps_the_deactivated_one(seeded, repository):
    _, report = seeded

    assert report.operators == (*OPERATORS, DEACTIVATED_OPERATOR)
    for name in OPERATORS:
        user = repository.user_by_name(name)
        assert user.role == Role.OPERATOR
        assert user.active
    assert not repository.user_by_name(DEACTIVATED_OPERATOR).active


def test_visits_cover_every_state(seeded, reader, accounts):
    states = [ticket.state for ticket in reader.list_tickets(accounts["manager"])]

    assert states.count(TicketState.ISSUED) == 4
    assert states.count(TicketState.PASSED) == 2
    assert states.count(TicketState.EXPIRED) == 2
    assert len(states) == len(seed.VISITS)


def test_tickets_are_assigned_as_planned(seeded, reader, repository, accounts):
    tickets = by_visitor(reader.list_tickets(accounts["manager"]))

    assert tickets["Adam Tələbə"].assigned_operator == repository.user_by_name("leyla").id
    assert tickets["Ləman Cəfərova"].assigned_operator == (
        repository.user_by_name(DEACTIVATED_OPERATOR).id
    )
    assert tickets["Səbinə Rzayeva"].assigned_operator == repository.user_by_name("aynur").id


def test_passed_tickets_count_their_granted_scans(seeded, reader, accounts):
    tickets = by_visitor(reader.list_tickets(accounts["manager"]))

    assert tickets["Nigar Həsənova"].use_count == 1
    assert tickets["Nigar Həsənova"].passed_at is not None
    assert tickets["Orxan Quliyev"].use_count == 2
    assert tickets["Orxan Quliyev"].state == TicketState.PASSED


def test_denied_scans_are_recorded_without_using_the_ticket(seeded, reader, repository, accounts):
    tickets = by_visitor(reader.list_tickets(accounts["manager"]))
    outcomes = [event.outcome for event in repository.list_events()]

    assert tickets["Günel Məmmədova"].use_count == 0
    assert tickets["Günel Məmmədova"].state == TicketState.ISSUED
    assert outcomes.count(Outcome.DENIED) == 1
    assert outcomes.count(Outcome.APPLIED) == 3


def test_seeded_payloads_verify_and_windows_are_whole_seconds(seeded, reader, accounts):
    for ticket in reader.list_tickets(accounts["manager"]):
        assert verify_payload(ticket.qr_payload, SECRET)
        assert ticket.valid_from.microsecond == 0
        assert ticket.valid_until.microsecond == 0


def test_seed_refuses_a_database_that_already_has_tickets(seeded, repository, clock):
    with pytest.raises(SeedError, match="already has tickets"):
        seed_demo(repository, SECRET, PASSWORD, clock=clock)


def test_existing_operators_are_reused_not_duplicated(repository, clock, accounts):
    repository.add_user(new_user("leyla", "already-set", Role.OPERATOR))

    report = seed_demo(repository, SECRET, PASSWORD, clock=clock)

    assert "leyla" not in report.operators
    assert len([user for user in repository.list_users() if user.username == "leyla"]) == 1


def test_seed_needs_an_active_manager(repository, clock, accounts):
    repository.save_user(replace(accounts["manager"], active=False))

    with pytest.raises(SeedError, match="active manager"):
        seed_demo(repository, SECRET, PASSWORD, clock=clock)
    assert repository.list_tickets() == []


def test_blank_password_is_rejected_before_anything_is_written(repository, clock):
    users_before = len(repository.list_users())

    with pytest.raises(ValueError, match="Password must not be empty"):
        seed_demo(repository, SECRET, "   ", clock=clock)
    assert len(repository.list_users()) == users_before
    assert repository.list_tickets() == []


def test_main_requires_the_seed_password(monkeypatch):
    monkeypatch.delenv(seed.PASSWORD_VARIABLE, raising=False)

    with pytest.raises(SystemExit, match=seed.PASSWORD_VARIABLE):
        seed.main()


def test_main_refuses_to_seed_a_biostar_server(monkeypatch):
    monkeypatch.setenv(seed.PASSWORD_VARIABLE, PASSWORD)
    monkeypatch.setenv("TIQR_SECRET_KEY", SECRET)
    monkeypatch.setenv("TIQR_BIOSTAR_BASE_URL", "https://biostar.example.test")
    monkeypatch.setenv("TIQR_BIOSTAR_USERNAME", "admin")
    monkeypatch.setenv("TIQR_BIOSTAR_PASSWORD", "biostar-password")
    monkeypatch.setenv("TIQR_BIOSTAR_DEVICE_IDS", "546000001")

    with pytest.raises(SystemExit, match="local mode"):
        seed.main()


def test_main_seeds_the_configured_database(monkeypatch, tmp_path, capsys):
    for name in ("TIQR_BIOSTAR_BASE_URL", "TIQR_BIOSTAR_USERNAME", "TIQR_BIOSTAR_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    database = tmp_path / "demo.db"
    monkeypatch.setenv("TIQR_DB", str(database))
    monkeypatch.setenv("TIQR_SECRET_KEY", SECRET)
    monkeypatch.setenv(seed.PASSWORD_VARIABLE, PASSWORD)
    with SQLiteRepository(database) as repository:
        repository.initialize()
        repository.add_user(new_user("manager", PASSWORD, Role.MANAGER))

    seed.main()

    output = capsys.readouterr().out
    assert f"Created {len(seed.VISITS)} tickets" in output
    with SQLiteRepository(database) as repository:
        repository.initialize()
        assert len(repository.list_tickets()) == len(seed.VISITS)
        assert repository.user_by_name("leyla").active


def test_seed_adds_the_catalog_and_prices_the_visits(seeded, repository, reader, accounts):
    assert {item.name: item.price for item in repository.list_ticket_types()} == dict(
        seed.TICKET_TYPES.values()
    )
    assert {item.name: item.discount_percent for item in repository.list_visitor_types()} == dict(
        seed.VISITOR_TYPES
    )
    tickets = by_visitor(reader.list_tickets(accounts["manager"]))
    # A one-time ticket at 15.00 for a student, who gets 30% off
    assert tickets["Adam Tələbə"].price == 1050
    assert tickets["Günel Məmmədova"].price == 6000
    assert tickets["Rəşad Əliyev"].price == 750
