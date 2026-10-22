import sqlite3
from dataclasses import replace
from datetime import timedelta
from http.cookies import SimpleCookie
from uuid import UUID, uuid4

import pytest

from tiqr.api import __version__
from tiqr.core.auth import WEB_SESSION_IDLE
from tiqr.core.biostar import BioStarError
from tiqr.core.models import RawEvent
from tiqr.core.printer import PrinterError

PASSWORD = "correct-password"
COOKIE = "tiqr-session"


def login(client, username="admin", password=PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def ticket_body(**overrides):
    return {
        "visitor_name": "Əli Иванов",
        "visitor_type": "Visitor",
        "valid_from": "2026-09-17T13:00",
        "valid_until": "2026-09-17T15:00",
        "usage_type": "one_time",
    } | overrides


def create_ticket(client, **overrides):
    response = client.post("/api/tickets", json=ticket_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def set_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    return cookie


def test_health_is_public_and_reports_the_version(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_is_unavailable_when_the_database_does_not_answer(client, service, monkeypatch):
    monkeypatch.setattr(service, "ping", lambda: False)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "version": __version__}


def test_health_is_unavailable_once_the_scheduler_has_stopped(make_client):
    with make_client(sync_interval=3600) as client:
        assert client.get("/api/health").status_code == 200
        client.app.state.tiqr.maintenance.stop()
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_login_sets_a_hardened_session_cookie(client, accounts):
    response = login(client)
    body = response.json()
    assert body["user"] == {
        "id": str(accounts["admin"].id),
        "username": "admin",
        "role": "admin",
        "active": True,
    }
    assert body["idle_timeout"] == WEB_SESSION_IDLE.total_seconds()
    morsel = set_cookie(response)[COOKIE]
    assert morsel["httponly"]
    # Plain HTTP by default, where a Secure cookie would never come back.
    assert not morsel["secure"]
    assert "strict-transport-security" not in response.headers
    assert morsel["samesite"].lower() == "strict"
    assert morsel["path"] == "/"
    # A browser-session cookie: the server, not the browser, decides when it ends.
    assert not morsel["max-age"]
    assert not morsel["expires"]
    assert morsel.value not in response.text


def test_session_and_config_need_a_cookie(client):
    for path in ("/api/auth/session", "/api/config", "/api/tickets", "/api/stats"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"
    login(client, "operator")
    session = client.get("/api/auth/session").json()
    assert session["user"]["username"] == "operator"
    assert session["csrf_token"] == client.headers["X-CSRF-Token"]
    assert client.get("/api/config").json() == {"timezone": "Asia/Baku", "server_printing": False}


def test_logout_revokes_the_session_on_the_server(client):
    token = set_cookie(login(client))[COOKIE].value
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert set_cookie(response)[COOKIE]["max-age"] == "0"
    # Replaying the old cookie fails: the session is gone, not just forgotten by the browser.
    client.cookies.clear()
    replay = client.get("/api/auth/session", headers={"Cookie": f"{COOKIE}={token}"})
    assert replay.status_code == 401


def test_a_new_login_closes_the_previous_session(client):
    first = set_cookie(login(client))[COOKIE].value
    login(client, "manager")
    client.cookies.clear()
    assert (
        client.get("/api/auth/session", headers={"Cookie": f"{COOKIE}={first}"}).status_code == 401
    )


def test_idle_sessions_end(client, clock):
    login(client)
    clock.now += WEB_SESSION_IDLE
    assert client.get("/api/auth/session").status_code == 401


def test_bad_password_and_unknown_user_look_alike(client):
    wrong = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_failed_logins_are_throttled_per_address_and_username(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    # Even the right password waits, so guessing gains nothing from continuing.
    blocked = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= 900
    # Another account from the same machine is not locked out by them.
    login(client, "manager")


def test_json_is_required_for_login(client):
    # A cross-site HTML form can only send form encodings, which are refused.
    response = client.post(
        "/api/auth/login",
        content=f'{{"username": "admin", "password": "{PASSWORD}"}}',
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    assert "set-cookie" not in response.headers


def test_writes_need_the_sessions_csrf_token(client):
    login(client)
    token = client.headers.pop("X-CSRF-Token")
    for header in ({}, {"X-CSRF-Token": "wrong"}):
        response = client.post("/api/tickets", json=ticket_body(), headers=header)
        assert response.status_code == 403
        assert response.json()["code"] == "csrf"
    assert client.post("/api/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = token
    create_ticket(client)


def test_cross_origin_writes_are_refused(client):
    credentials = {"username": "admin", "password": PASSWORD}
    response = client.post(
        "/api/auth/login", json=credentials, headers={"Origin": "http://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "cross_origin"
    same = client.post("/api/auth/login", json=credentials, headers={"Origin": "http://testserver"})
    assert same.status_code == 200
    # The scheme is part of the origin, so an HTTPS page on the same host is another site.
    other_scheme = client.post(
        "/api/auth/login", json=credentials, headers={"Origin": "https://testserver"}
    )
    assert other_scheme.status_code == 403
    # Reads are not refused; the browser keeps their answers from the other origin anyway.
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200


def test_security_headers(client):
    headers = client.get("/api/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "server" not in headers


def test_ticket_lifecycle_through_the_api(client, accounts):
    login(client, "operator")
    created = create_ticket(client)
    # Offset-less times are read in TIQR_DEFAULT_TZ and shown back in it.
    assert created["valid_from"] == "2026-09-17T13:00:00+04:00"
    assert created["timezone"] == "Asia/Baku"
    assert created["state"] == "issued"
    assert created["created_by"] == created["assigned_operator"] == str(accounts["operator"].id)
    assert {"qr_payload", "external_id"}.isdisjoint(created)
    ticket_id = created["id"]
    assert client.get(f"/api/tickets/{ticket_id}").json() == created
    assert [ticket["id"] for ticket in client.get("/api/tickets").json()["items"]] == [ticket_id]
    assert client.get("/api/tickets", params={"state": "passed"}).json()["items"] == []

    pdf = client.post(f"/api/tickets/{ticket_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == f'inline; filename="{ticket_id}.pdf"'
    assert pdf.content.startswith(b"%PDF-")
    assert client.get(f"/api/tickets/{ticket_id}").json()["print_count"] == 1


def test_explicit_offsets_and_timezones_are_honored(client):
    login(client)
    offset = create_ticket(client, valid_from="2026-09-17T09:00:00Z")
    assert offset["valid_from"] == "2026-09-17T13:00:00+04:00"
    almaty = create_ticket(client, timezone="Asia/Almaty")
    assert almaty["valid_from"] == "2026-09-17T12:00:00+04:00"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"valid_from": "tomorrow"}, "ISO datetime"),
        ({"valid_until": "2026-09-17T12:00"}, "reversed or already expired"),
        ({"valid_from": "2026-09-17T13:00:00.5"}, "whole-second"),
        ({"visitor_name": " "}, "required"),
        ({"timezone": "Mars/Base"}, "Unknown timezone"),
    ],
)
def test_domain_validation_errors_are_422(client, overrides, message):
    login(client)
    response = client.post("/api/tickets", json=ticket_body(**overrides))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid"
    assert message in response.json()["detail"]


def test_schema_validation_errors_are_422(client):
    login(client)
    assert client.post("/api/tickets", json=ticket_body(extra=1)).status_code == 422
    assert client.post("/api/tickets", json=ticket_body(usage_type="forever")).status_code == 422
    assert client.get("/api/tickets/not-a-uuid").status_code == 422
    assert client.get("/api/tickets", params={"state": "lost"}).status_code == 422


def test_operators_see_only_their_tickets_and_cannot_assign(client):
    login(client, "manager")
    ticket_id = create_ticket(client)["id"]
    login(client, "operator")
    assert client.get(f"/api/tickets/{ticket_id}").status_code == 403
    assert client.get("/api/tickets").json()["items"] == []
    assign = client.post(f"/api/tickets/{ticket_id}/assign", json={"assignee": "operator"})
    assert assign.status_code == 403
    login(client, "manager")
    assert (
        client.post(f"/api/tickets/{ticket_id}/assign", json={"assignee": "nobody"}).json()["code"]
        == "not_found"
    )
    assigned = client.post(f"/api/tickets/{ticket_id}/assign", json={"assignee": "operator"})
    assert assigned.status_code == 200
    login(client, "operator")
    assert client.get(f"/api/tickets/{ticket_id}").status_code == 200
    assert client.get(f"/api/tickets/{uuid4()}").status_code == 404


def test_passed_tickets_cannot_be_printed(client, service):
    login(client, "manager")
    ticket = create_ticket(client, valid_from="2026-09-17T12:00")
    external_id = service.repository.get_ticket(UUID(ticket["id"])).external_id
    service.event_source.events.append(RawEvent("scan-1", external_id, service._now(), True))
    assert client.post("/api/sync").json() == {"count": 1}
    response = client.post(f"/api/tickets/{ticket['id']}/pdf")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_user_management(client):
    login(client, "manager")
    assert [user["username"] for user in client.get("/api/users").json()["items"]] == [
        "admin",
        "manager",
        "operator",
        "other",
    ]
    body = {"username": "newcomer", "password": "newcomer-password", "role": "operator"}
    assert client.post("/api/users", json=body | {"role": "manager"}).status_code == 403
    assert client.post("/api/users", json=body | {"username": "clerk"}).status_code == 201
    login(client, "operator")
    assert client.get("/api/users").status_code == 403
    login(client, "admin")
    created = client.post("/api/users", json=body)
    assert created.status_code == 201
    assert created.json()["username"] == "newcomer"
    assert "password" not in created.text
    assert client.post("/api/users", json=body).json()["detail"] == "Username already exists"
    assert client.post("/api/users", json=body | {"role": "root"}).status_code == 422
    login(client, "newcomer", "newcomer-password")


def test_server_printing_is_off_by_default(client, printed):
    login(client)
    ticket_id = create_ticket(client)["id"]
    response = client.post(f"/api/tickets/{ticket_id}/print")
    assert response.status_code == 409
    assert response.json()["code"] == "server_printing_off"
    assert printed == []


def test_server_printing_sends_the_pdf_and_counts_it(make_client, printed, tmp_path):
    with make_client(server_printing=True) as client:
        login(client)
        assert client.get("/api/config").json()["server_printing"] is True
        ticket_id = create_ticket(client)["id"]
        response = client.post(f"/api/tickets/{ticket_id}/print")
        assert response.status_code == 200, response.text
        assert response.json()["print_count"] == 1
        assert printed == [tmp_path / "out" / f"{ticket_id}.pdf"]


def test_a_refused_print_is_not_counted(make_client, service, printed):
    def refuse(path):
        raise PrinterError("Printing failed: lp: Destination not set")

    with make_client(server_printing=True) as client:
        client.app.state.tiqr = replace(
            client.app.state.tiqr, runtime=replace(client.app.state.tiqr.runtime, printer=refuse)
        )
        login(client)
        ticket_id = create_ticket(client)["id"]
        response = client.post(f"/api/tickets/{ticket_id}/print")
        assert response.status_code == 502
        assert response.json() == {
            "detail": "Printing failed: lp: Destination not set",
            "code": "printer",
        }
        assert client.get(f"/api/tickets/{ticket_id}").json()["print_count"] == 0


def test_sync_cleanup_and_stats(client, service):
    login(client, "operator")
    ticket = create_ticket(client, valid_from="2026-09-17T12:00")
    for path in ("/api/sync", "/api/cleanup"):
        assert client.post(path).status_code == 403
    assert client.get("/api/stats").status_code == 403
    login(client, "admin")
    external_id = service.repository.get_ticket(UUID(ticket["id"])).external_id
    service.event_source.events.append(RawEvent("scan-1", external_id, service._now(), True))
    assert client.post("/api/sync").json() == {"count": 1}
    assert client.post("/api/sync").json() == {"count": 0}
    assert client.post("/api/cleanup").json() == {"count": 1}
    counts = {"total": 1, "issued": 0, "passed": 1, "expired": 0, "uses": 1, "prints": 0}
    assert client.get("/api/stats").json() == {**counts, "visitor_types": {"Visitor": counts}}
    assert client.get("/api/stats?since=2026-09-17&until=2026-09-17").json()["total"] == 1
    assert client.get("/api/stats?until=2026-09-16").json()["total"] == 0
    assert client.get("/api/stats?since=2026-13-01").status_code == 422
    backwards = client.get("/api/stats?since=2026-09-18&until=2026-09-17")
    assert backwards.status_code == 422
    assert backwards.json()["code"] == "invalid"


def test_biostar_failures_are_502_with_their_codes(client, service, monkeypatch):
    def fail(ticket):
        raise BioStarError("Server busy", code="20", http_status=503)

    monkeypatch.setattr(service.registrar, "register", fail)
    login(client)
    response = client.post("/api/tickets", json=ticket_body())
    assert response.status_code == 502
    assert response.json() == {
        "detail": "Server busy (BioStar code 20, HTTP 503)",
        "code": "biostar",
    }


def test_unexpected_errors_reveal_nothing(make_client, service, monkeypatch):
    def fail(actor):
        raise sqlite3.OperationalError("unable to open /var/lib/tiqr/tiqr.db")

    monkeypatch.setattr(service, "stats", fail)
    with make_client(raise_server_exceptions=False) as client:
        login(client)
        response = client.get("/api/stats")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "code": "internal"}


def test_docs_are_served_in_development_only(client, make_client):
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404
    with make_client(dev=True) as dev:
        assert dev.get("/api/docs").status_code == 200
        assert dev.get("/api/openapi.json").json()["info"]["title"] == "TiQR"


def test_tls_adds_a_host_only_secure_cookie_and_hsts(make_client):
    with make_client(tls=True) as client:
        response = login(client)
        morsel = set_cookie(response)["__Host-tiqr-session"]
        assert morsel["secure"]
        assert morsel["httponly"]
        assert morsel["path"] == "/"
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert client.get("/api/auth/session").status_code == 200
        same = client.post("/api/auth/logout", headers={"Origin": "https://testserver"})
        assert same.status_code == 204


def test_unknown_api_paths_are_json_404s(client):
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_session_idle_window_moves_with_requests(client, clock):
    login(client)
    clock.now += WEB_SESSION_IDLE - timedelta(minutes=1)
    assert client.get("/api/auth/session").status_code == 200
    clock.now += WEB_SESSION_IDLE - timedelta(minutes=1)
    assert client.get("/api/auth/session").status_code == 200


def test_admins_change_roles_deactivate_and_reset_passwords(client, accounts):
    operator = accounts["operator"]
    url = f"/api/users/{operator.id}"
    login(client, "manager")
    assert client.patch(url, json={"role": "manager"}).status_code == 403
    assert client.patch(url, json={"active": False}).json()["active"] is False
    assert client.patch(url, json={"active": True}).json()["active"] is True
    login(client, "admin")
    promoted = client.patch(url, json={"role": "manager"})
    assert promoted.status_code == 200
    assert promoted.json() == {
        "id": str(operator.id),
        "username": "operator",
        "role": "manager",
        "active": True,
    }
    assert client.patch(url, json={"active": False}).json()["active"] is False
    refused = client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
    assert refused.status_code == 401
    assert refused.json()["detail"] == "This account is deactivated"
    listed = {user["username"]: user["active"] for user in client.get("/api/users").json()["items"]}
    assert listed["operator"] is False
    assert client.patch(url, json={"active": True, "password": "reset-password"}).status_code == 200
    login(client, "operator", "reset-password")


def test_password_reset_signs_the_user_out_everywhere(make_client, accounts):
    with make_client() as admin, make_client() as manager:
        login(manager, "manager")
        login(admin)
        reset = admin.patch(
            f"/api/users/{accounts['manager'].id}", json={"password": "manager-new-password"}
        )
        assert reset.status_code == 200
        assert "manager-new-password" not in reset.text
        assert manager.get("/api/auth/session").status_code == 401


def test_user_update_refusals(client, accounts):
    login(client)
    me = f"/api/users/{accounts['admin'].id}"
    assert client.patch(me, json={"active": False}).json()["code"] == "forbidden"
    assert client.patch(me, json={"role": "operator"}).json()["code"] == "forbidden"
    assert client.patch(me, json={}).json() == {"detail": "Nothing to change", "code": "invalid"}
    assert client.patch(f"/api/users/{uuid4()}", json={"active": False}).status_code == 404
    assert client.patch(me, json={"username": "renamed"}).status_code == 422
    assert client.patch(me, json={"role": "root"}).status_code == 422
    other = f"/api/users/{accounts['other'].id}"
    assert client.patch(other, json={"password": " "}).json()["code"] == "invalid"
    assert client.delete(other).json()["code"] == "conflict"
    assert client.patch(other, json={"active": False}).status_code == 200
    assert client.delete(other).status_code == 204
    assert client.delete(other).status_code == 404
    # Writes still need the CSRF token.
    token = client.headers.pop("X-CSRF-Token")
    assert client.patch(other, json={"active": False}).json()["code"] == "csrf"
    client.headers["X-CSRF-Token"] = token


def test_lists_are_paged_newest_ticket_first(client):
    login(client)
    serials = [create_ticket(client)["readable_serial"] for _ in range(3)]
    first = client.get("/api/tickets", params={"size": 2}).json()
    assert (first["total"], first["page"], first["size"]) == (3, 1, 2)
    assert [ticket["readable_serial"] for ticket in first["items"]] == serials[:0:-1]
    second = client.get("/api/tickets", params={"size": 2, "page": 2}).json()
    assert [ticket["readable_serial"] for ticket in second["items"]] == serials[:1]
    beyond = client.get("/api/tickets", params={"size": 2, "page": 9}).json()
    assert (beyond["items"], beyond["total"]) == ([], 3)
    users = client.get("/api/users", params={"size": 3, "page": 2}).json()
    assert [user["username"] for user in users["items"]] == ["other"]
    assert users["total"] == 4


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}, {"page": "x"}])
def test_bad_paging_is_422(client, params):
    login(client)
    for path in ("/api/tickets", "/api/users"):
        assert client.get(path, params=params).status_code == 422


def test_ticket_types_are_managed_by_staff_and_read_by_everyone(client):
    login(client, "manager")
    created = client.post("/api/ticket-types", json={"name": "Day pass", "price_minor": 1250})
    assert created.status_code == 201
    day = created.json()
    assert day["name"] == "Day pass"
    assert day["price_minor"] == 1250

    login(client, "operator")
    page = client.get("/api/ticket-types").json()
    assert page["items"] == [day]
    assert page["total"] == 1
    assert (
        client.post("/api/ticket-types", json={"name": "Night", "price_minor": 1}).status_code
        == 403
    )
    assert (
        client.patch(f"/api/ticket-types/{day['id']}", json={"price_minor": 1}).status_code == 403
    )
    assert client.delete(f"/api/ticket-types/{day['id']}").status_code == 403

    login(client, "admin")
    patched = client.patch(
        f"/api/ticket-types/{day['id']}", json={"name": "Daily", "price_minor": 2000}
    )
    assert patched.json() == day | {"name": "Daily", "price_minor": 2000}
    assert client.delete(f"/api/ticket-types/{day['id']}").status_code == 204
    assert client.get("/api/ticket-types").json()["items"] == []
    assert client.delete(f"/api/ticket-types/{day['id']}").status_code == 404
    assert client.patch(f"/api/ticket-types/{uuid4()}", json={"price_minor": 1}).status_code == 404


def test_visitor_types_are_managed_by_staff_and_read_by_everyone(client):
    login(client, "manager")
    created = client.post("/api/visitor-types", json={"name": "Student", "discount_percent": 30})
    assert created.status_code == 201
    student = created.json()
    assert student["discount_percent"] == 30

    login(client, "operator")
    assert client.get("/api/visitor-types").json()["items"] == [student]
    assert client.post("/api/visitor-types", json={"name": "Staff"}).status_code == 403
    assert client.delete(f"/api/visitor-types/{student['id']}").status_code == 403

    login(client, "admin")
    patched = client.patch(f"/api/visitor-types/{student['id']}", json={"discount_percent": 40})
    assert patched.json() == student | {"discount_percent": 40}
    assert client.post("/api/visitor-types", json={"name": "Staff"}).json()["discount_percent"] == 0
    assert client.delete(f"/api/visitor-types/{student['id']}").status_code == 204
    assert client.delete(f"/api/visitor-types/{student['id']}").status_code == 404


def test_catalog_refusals(client):
    login(client, "admin")
    assert (
        client.post("/api/ticket-types", json={"name": "Day", "price_minor": 100}).status_code
        == 201
    )
    duplicate = client.post("/api/ticket-types", json={"name": "day", "price_minor": 100})
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "invalid"
    for body in (
        {"name": "Night", "price_minor": -1},
        {"name": "Night", "price_minor": 10**9 + 1},
        {"name": "Night", "price_minor": 1.5},
        {"name": "Night"},
        {"name": " ", "price_minor": 1},
    ):
        assert client.post("/api/ticket-types", json=body).status_code == 422
    for body in (
        {"name": "Student", "discount_percent": 101},
        {"name": "Student", "discount_percent": -1},
        {"name": " "},
    ):
        assert client.post("/api/visitor-types", json=body).status_code == 422
    day = client.get("/api/ticket-types").json()["items"][0]
    assert client.patch(f"/api/ticket-types/{day['id']}", json={}).status_code == 422
    assert client.get("/api/ticket-types", params={"size": 0}).status_code == 422
    client.headers.pop("X-CSRF-Token")
    assert (
        client.post("/api/ticket-types", json={"name": "Night", "price_minor": 1}).status_code
        == 403
    )


def test_a_ticket_is_priced_from_its_types(client):
    login(client, "admin")
    client.post("/api/ticket-types", json={"name": "Day pass", "price_minor": 1250})
    client.post("/api/visitor-types", json={"name": "Student", "discount_percent": 20})

    login(client, "operator")
    ticket = create_ticket(client, ticket_type="Day pass", visitor_type="Student")
    assert ticket["ticket_type"] == "Day pass"
    assert ticket["base_price_minor"] == 1250
    assert ticket["discount_percent"] == 20
    assert ticket["price_minor"] == 1000
    assert client.get(f"/api/tickets/{ticket['id']}").json() == ticket

    plain = create_ticket(client)
    assert plain["ticket_type"] is None
    assert plain["price_minor"] is None
    assert plain["discount_percent"] == 0

    unknown = client.post("/api/tickets", json=ticket_body(ticket_type="Nope"))
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "Unknown ticket type"
