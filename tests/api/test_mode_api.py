from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import IDLE, PLAIN
from tests.api.test_api import PASSWORD, login
from tests.api.test_api import ticket_body as suite_body
from tiqr.api.app import create_app
from tiqr.api.runtime import Runtime
from tiqr.core.models import Mode, Role
from tiqr.core.runtime import open_service
from tiqr.core.settings import Settings


def ticket_body(**fields):
    # This server runs on the real clock, so its windows lie ahead of it.
    return suite_body(valid_from="2030-01-01T10:00", valid_until="2030-01-01T12:00", **fields)


@pytest.fixture
def saved():
    return []


@pytest.fixture
def switching(tmp_path, issue, license_pair, saved):
    """A client on a server whose two databases are real files, so it can switch between them."""
    settings = Settings(
        secret_key="api-suite-unique-signing-key",
        database_path=tmp_path / "tiqr_ticket.db",
        output_dir=tmp_path / "out",
        default_tz="Asia/Baku",
    )

    @contextmanager
    def runtime():
        with open_service(settings, saved.append) as service:
            service._license_public_key = license_pair[1]
            admin = service.add_user("admin", PASSWORD, Role.ADMIN)
            service.create_user(admin, "manager", PASSWORD, Role.MANAGER)
            service.activate_license(admin, issue())
            service.repository.save_active_hours(None)
            service.create_visitor_type(admin, "Visitor")
            yield Runtime(settings, service)

    app = create_app(PLAIN, runtime=runtime, web_root=tmp_path / "no-web", scheduler=IDLE)
    with TestClient(app, base_url="http://testserver") as client:
        yield client


def test_admins_switch_between_tickets_and_badges(switching, saved):
    login(switching)
    assert switching.get("/api/settings/mode").json() == {"mode": "ticket", "pinned": False}
    assert switching.get("/api/branding").json()["mode"] == "ticket"
    ticket = switching.post("/api/tickets", json=ticket_body(usage_type="group", group_size=5))
    assert (ticket.status_code, ticket.json()["group_size"]) == (201, 5)

    switched = switching.put("/api/settings/mode", json={"mode": "badge"})
    assert switched.json() == {"mode": "badge", "pinned": False}
    assert saved == [Mode.BADGE]
    assert switching.get("/api/branding").json()["mode"] == "badge"
    # Still signed in and licensed, on a database of its own.
    assert switching.get("/api/tickets").json()["total"] == 0
    assert switching.post("/api/visitor-types", json={"name": "Visitor"}).status_code == 201
    badge = switching.post(
        "/api/tickets", json=ticket_body(visitor_name="Ada", usage_type="multi_use")
    )
    assert (badge.status_code, badge.json()["visitor_name"]) == (201, "Ada")
    priced = ticket_body(visitor_name="Ada", usage_type="multi_use", ticket_type="Entry")
    assert switching.post("/api/tickets", json=priced).status_code == 422

    assert switching.put("/api/settings/mode", json={"mode": "ticket"}).status_code == 200
    assert [item["id"] for item in switching.get("/api/tickets").json()["items"]] == [
        ticket.json()["id"]
    ]


def test_only_admins_switch_and_never_against_the_environment(switching, monkeypatch):
    login(switching, "manager")
    assert switching.get("/api/settings/mode").json()["mode"] == "ticket"
    assert switching.put("/api/settings/mode", json={"mode": "badge"}).status_code == 403
    login(switching)
    assert switching.put("/api/settings/mode", json={"mode": "bogus"}).status_code == 422
    monkeypatch.setenv("TIQR_MODE", "ticket")
    pinned = switching.put("/api/settings/mode", json={"mode": "badge"})
    assert (pinned.status_code, pinned.json()["code"]) == (409, "mode_pinned")
    assert switching.get("/api/settings/mode").json() == {"mode": "ticket", "pinned": True}
