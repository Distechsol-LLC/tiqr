import sqlite3
from datetime import timedelta
from uuid import UUID

import pytest

from tiqr.core.auth import AuthenticationError
from tiqr.core.models import Role, UsageType
from tiqr.core.repository import _MIGRATIONS, SQLiteRepository
from tiqr.core.service import NotFoundError, PermissionDeniedError, StateError

PASSWORD = "correct-password"


def issue(service, actor, clock):
    return service.create_ticket(
        actor,
        visitor_name="Name",
        visitor_type="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.MULTI_USE,
    )


def test_existing_users_stay_active_through_the_upgrade(tmp_path):
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(";\n".join((*_MIGRATIONS[0], "PRAGMA user_version = 1;")))
        connection.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            ("8f5e0c3a-0d6c-4a43-9d1f-0d8c4f1b6a01", "veteran", "hash", "admin"),
        )
    with SQLiteRepository(path) as repository:
        repository.initialize(upgrade=True)
        assert repository.user_by_name("veteran").active


def test_deactivated_users_cannot_sign_in_act_or_be_assigned(service, accounts, clock):
    operator = accounts["operator"]
    ticket = issue(service, operator, clock)
    token, _ = service.open_web_session(operator)
    service.edit_user(operator.id, active=False)

    # The right password is still refused, and says why; a wrong one says nothing more.
    with pytest.raises(AuthenticationError, match="deactivated"):
        service.authenticate("operator", PASSWORD)
    with pytest.raises(AuthenticationError, match="Invalid username or password"):
        service.authenticate("operator", "wrong")
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)
    with pytest.raises(PermissionDeniedError, match="deactivated"):
        service.list_tickets(operator)
    with pytest.raises(StateError, match="deactivated"):
        service.assign_ticket(accounts["manager"], ticket.id, "operator")
    # Tickets and history stay, and a manager can hand them to someone active.
    assert service.assign_ticket(accounts["manager"], ticket.id, "other").assigned_operator == (
        accounts["other"].id
    )

    service.edit_user(operator.id, active=True)
    assert service.authenticate("operator", PASSWORD).active
    # Reactivating does not bring old sessions back.
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)


def test_deactivation_ends_the_cli_login_too(service, accounts):
    session = service.start_session(accounts["operator"])
    service.edit_user(accounts["operator"].id, active=False)
    with pytest.raises(AuthenticationError):
        service.resume_session(session)


def test_password_reset_ends_every_session(service, accounts):
    manager = accounts["manager"]
    token, _ = service.open_web_session(manager)
    cached = service.start_session(manager)
    service.edit_user(manager.id, password="brand-new-password")
    with pytest.raises(AuthenticationError):
        service.authenticate("manager", PASSWORD)
    assert service.authenticate("manager", "brand-new-password").id == manager.id
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)
    with pytest.raises(AuthenticationError):
        service.resume_session(cached)
    with pytest.raises(ValueError, match="must not be empty"):
        service.edit_user(manager.id, password="  ")


def test_role_change_applies_to_the_next_request_without_signing_out(service, accounts):
    operator = accounts["operator"]
    token, _ = service.open_web_session(operator)
    with pytest.raises(PermissionDeniedError):
        service.stats(operator)
    assert service.edit_user(operator.id, role=Role.MANAGER).role == Role.MANAGER
    user, _ = service.resume_web_session(token)
    assert user.role == Role.MANAGER
    assert service.stats(operator)["total"] == 0


def test_the_last_active_admin_is_kept(service, accounts):
    admin = accounts["admin"]
    for change in ({"active": False}, {"role": Role.MANAGER}):
        with pytest.raises(StateError, match="last active admin"):
            service.edit_user(admin.id, **change)
    service.edit_user(accounts["manager"].id, role=Role.ADMIN)
    service.edit_user(admin.id, active=False)
    # The other admin is now the last one.
    with pytest.raises(StateError, match="last active admin"):
        service.edit_user(accounts["manager"].id, role=Role.OPERATOR)


def test_edit_needs_a_change_and_an_existing_user(service, accounts):
    with pytest.raises(ValueError, match="Nothing to change"):
        service.edit_user(accounts["operator"].id)
    with pytest.raises(NotFoundError):
        service.edit_user(UUID(int=0), active=False)
    with pytest.raises(NotFoundError):
        service.find_user("nobody")
    assert service.find_user(" operator ") == accounts["operator"]


def test_operators_cannot_manage_users(service, accounts):
    with pytest.raises(PermissionDeniedError):
        service.manage_user(accounts["operator"], accounts["other"].id, active=False)


def test_managers_only_deactivate_and_reactivate_operators(service, accounts):
    manager, other = accounts["manager"], accounts["other"]
    assert service.manage_user(manager, other.id, active=False).active is False
    assert service.manage_user(manager, other.id, active=True).active is True
    for change in ({"role": Role.MANAGER}, {"password": "new-password"}):
        with pytest.raises(PermissionDeniedError, match="only deactivate or reactivate"):
            service.manage_user(manager, other.id, **change)
    for target in ("admin", "manager"):
        with pytest.raises(PermissionDeniedError, match="only deactivate or reactivate"):
            service.manage_user(manager, accounts[target].id, active=False)
    with pytest.raises(NotFoundError):
        service.manage_user(manager, UUID(int=0), active=False)


def test_only_deactivated_users_without_tickets_are_deleted(service, accounts, clock):
    admin, other, operator = accounts["admin"], accounts["other"], accounts["operator"]
    token, _ = service.open_web_session(other)
    with pytest.raises(StateError, match="Deactivate the user"):
        service.delete_user(admin, other.id)
    service.edit_user(other.id, active=False)
    for actor in ("manager", "operator"):
        with pytest.raises(PermissionDeniedError):
            service.delete_user(accounts[actor], other.id)
    service.delete_user(admin, other.id)
    assert service.repository.user_by_id(other.id) is None
    with pytest.raises(AuthenticationError):
        service.resume_web_session(token)
    with pytest.raises(NotFoundError):
        service.delete_user(admin, other.id)
    # Ticket history keeps its people.
    issue(service, operator, clock)
    service.edit_user(operator.id, active=False)
    with pytest.raises(StateError, match="with tickets"):
        service.remove_user(operator.id)


def test_admins_cannot_demote_or_deactivate_themselves(service, accounts):
    admin = accounts["admin"]
    for change in ({"active": False}, {"role": Role.OPERATOR}):
        with pytest.raises(PermissionDeniedError, match="their own role"):
            service.manage_user(admin, admin.id, **change)
    # Their own password, an unchanged role, and other accounts are fine.
    service.manage_user(admin, admin.id, role=Role.ADMIN, password="admin-new-password")
    assert service.manage_user(admin, accounts["other"].id, active=False).active is False


def test_a_deactivated_admin_cannot_manage_users(service, accounts):
    service.edit_user(accounts["manager"].id, role=Role.ADMIN)
    service.edit_user(accounts["admin"].id, active=False)
    with pytest.raises(PermissionDeniedError, match="deactivated"):
        service.manage_user(accounts["admin"], accounts["other"].id, active=False)
