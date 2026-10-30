from datetime import timedelta

import pytest

from tests.api.test_api import create_ticket, login, ticket_body
from tiqr.core.biostar import BioStarError
from tiqr.core.fakes import InMemoryRegistrar


class FlakyRegistrar(InMemoryRegistrar):
    def __init__(self):
        super().__init__()
        self.failing = set()

    def deactivate(self, external_id):
        if "deactivate" in self.failing:
            raise BioStarError("deactivate refused")
        super().deactivate(external_id)

    def activate(self, external_id):
        if "activate" in self.failing:
            raise BioStarError("activate refused")
        super().activate(external_id)

    def set_window(self, external_id, start, end):
        if "set_window" in self.failing:
            raise BioStarError("set_window refused")
        super().set_window(external_id, start, end)


@pytest.fixture
def registrar(service):
    service.registrar = FlakyRegistrar()
    return service.registrar


@pytest.fixture
def admin(client):
    login(client, "admin")
    return client


def new_key(client, *scopes, acts_as="manager", **extra):
    response = client.post(
        "/api/service-keys",
        json={"name": "pos", "scopes": list(scopes), "acts_as": acts_as} | extra,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def machine(make_client):
    """A client with no cookie, as a service is: it sends only its key."""

    def build(secret):
        client = make_client()
        client.__enter__()
        client.headers["Authorization"] = f"Bearer {secret}"
        return client

    return build


def test_revoke_endpoint_is_idempotent_and_audited(admin, registrar):
    ticket = create_ticket(admin)
    first = admin.post(f"/api/tickets/{ticket['id']}/revoke", json={"reason": "lost"})
    again = admin.post(f"/api/tickets/{ticket['id']}/revoke")
    assert first.status_code == again.status_code == 200
    assert first.json()["state"] == again.json()["state"] == "revoked"
    audit = admin.get(f"/api/tickets/{ticket['id']}/audit").json()
    assert [(row["action"], row["reason"]) for row in audit] == [
        ("ticket.create", None),
        ("ticket.revoke", "lost"),
    ]


def test_revoking_an_expired_ticket_is_a_409(admin, clock):
    ticket = create_ticket(admin, valid_from="2026-09-17T12:05", valid_until="2026-09-17T12:20")
    # Shorter than the 30-minute idle limit, so the browser session is still alive.
    clock.now += timedelta(minutes=25)
    response = admin.post(f"/api/tickets/{ticket['id']}/revoke")
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_state"


def test_a_biostar_failure_on_revoke_is_a_502_and_keeps_the_ticket(admin, registrar):
    ticket = create_ticket(admin)
    registrar.failing.add("deactivate")
    response = admin.post(f"/api/tickets/{ticket['id']}/revoke")
    assert response.status_code == 502
    assert response.json()["code"] == "biostar"
    assert admin.get(f"/api/tickets/{ticket['id']}").json()["state"] == "issued"


def test_patch_changes_the_window_and_validates_it(admin, registrar):
    ticket = create_ticket(admin)
    ok = admin.patch(f"/api/tickets/{ticket['id']}", json={"valid_until": "2026-09-17T18:00"})
    assert ok.status_code == 200
    assert ok.json()["valid_until"].startswith("2026-09-17T18:00")
    bad = admin.patch(f"/api/tickets/{ticket['id']}", json={"valid_until": "2026-09-17T12:00"})
    assert bad.status_code == 422
    assert admin.patch(f"/api/tickets/{ticket['id']}", json={}).status_code == 422
    registrar.failing.add("set_window")
    refused = admin.patch(f"/api/tickets/{ticket['id']}", json={"valid_until": "2026-09-17T19:00"})
    assert refused.status_code == 502


def test_state_filter_lists_revoked_tickets(admin):
    revoked = create_ticket(admin)
    create_ticket(admin)
    admin.post(f"/api/tickets/{revoked['id']}/revoke")
    page = admin.get("/api/tickets", params={"state": "revoked"}).json()
    assert [item["id"] for item in page["items"]] == [revoked["id"]]
    assert page["total"] == 1


def test_patch_of_a_revoked_ticket_is_a_409(admin):
    ticket = create_ticket(admin)
    admin.post(f"/api/tickets/{ticket['id']}/revoke")
    response = admin.patch(f"/api/tickets/{ticket['id']}", json={"valid_until": "2026-09-17T18:00"})
    assert response.status_code == 409


def test_external_code_is_accepted_returned_filtered_and_unique(admin):
    ticket = create_ticket(admin, external_code="BAR-1")
    assert ticket["external_code"] == "BAR-1"
    create_ticket(admin, external_code="BAR-2")
    page = admin.get("/api/tickets", params={"external_code": "BAR-1"}).json()
    assert [item["id"] for item in page["items"]] == [ticket["id"]]
    clash = admin.post("/api/tickets", json=ticket_body(external_code="BAR-1"))
    assert clash.status_code == 409


def test_existing_clients_see_the_same_shape_plus_new_optional_fields(admin):
    ticket = create_ticket(admin)
    assert ticket["external_code"] is None
    assert ticket["event_session"] is None
    assert admin.get("/api/tickets").json()["total"] == 1


def test_same_key_and_payload_replays_the_first_answer(admin):
    headers = {"Idempotency-Key": "abc"}
    first = admin.post("/api/tickets", json=ticket_body(), headers=headers)
    again = admin.post("/api/tickets", json=ticket_body(), headers=headers)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert admin.get("/api/tickets").json()["total"] == 1


def test_same_key_with_another_payload_is_a_409(admin):
    headers = {"Idempotency-Key": "abc"}
    admin.post("/api/tickets", json=ticket_body(), headers=headers)
    other = admin.post(
        "/api/tickets", json=ticket_body(visitor_name="Someone else"), headers=headers
    )
    assert other.status_code == 409
    assert admin.get("/api/tickets").json()["total"] == 1


def test_a_key_expires_after_its_ttl(make_client, clock):
    with make_client(idempotency_ttl_hours=1) as client:
        login(client)
        headers = {"Idempotency-Key": "abc"}
        client.post("/api/tickets", json=ticket_body(), headers=headers)
        clock.now += timedelta(hours=2)
        login(client)
        # Expired keys are forgotten, so the same key may carry a different body.
        assert (
            client.post(
                "/api/tickets", json=ticket_body(valid_until="2026-09-18T15:00"), headers=headers
            ).status_code
            == 201
        )


def test_a_refused_create_can_be_retried_under_the_same_key(admin):
    headers = {"Idempotency-Key": "abc"}
    bad = ticket_body(valid_until="2020-01-01T00:00")
    assert admin.post("/api/tickets", json=bad, headers=headers).status_code == 422
    assert admin.post("/api/tickets", json=ticket_body(), headers=headers).status_code == 201


def test_batch_partial_success_reports_each_item(admin):
    items = [ticket_body(), ticket_body(visitor_name=" "), ticket_body(external_code="B")]
    response = admin.post("/api/tickets/batch", json={"items": items})
    body = response.json()
    assert response.status_code == 200
    assert [r["status"] for r in body["results"]] == ["created", "error", "created"]
    assert (body["created"], body["failed"], body["committed"]) == (2, 1, True)
    assert body["results"][1]["code"] == "invalid"
    assert body["results"][0]["ticket_id"] == body["results"][0]["ticket"]["id"]
    assert admin.get("/api/tickets").json()["total"] == 2


def test_batch_all_or_nothing_undoes_the_created_items(admin, registrar):
    items = [ticket_body(), ticket_body(visitor_name=" "), ticket_body(external_code="C")]
    body = admin.post("/api/tickets/batch", json={"items": items, "atomic": True}).json()
    assert [r["status"] for r in body["results"]] == ["rolled_back", "error", "skipped"]
    assert (body["committed"], body["created"]) == (False, 0)
    states = {t["state"] for t in admin.get("/api/tickets").json()["items"]}
    assert states == {"revoked"}
    assert len(registrar.deactivated) == 1


def test_batch_atomic_success_commits_and_remembers_the_keys(admin):
    items = [
        ticket_body(idempotency_key="one"),
        ticket_body(external_code="X", idempotency_key="two"),
    ]
    first = admin.post("/api/tickets/batch", json={"items": items, "atomic": True}).json()
    again = admin.post("/api/tickets/batch", json={"items": items, "atomic": True}).json()
    assert first["committed"] is True
    assert [r["status"] for r in again["results"]] == ["replayed", "replayed"]
    assert [r["ticket_id"] for r in again["results"]] == [r["ticket_id"] for r in first["results"]]
    assert admin.get("/api/tickets").json()["total"] == 2


def test_batch_items_follow_the_idempotency_rules(admin):
    items = [
        ticket_body(idempotency_key="k"),
        ticket_body(visitor_name="Other", idempotency_key="k"),
    ]
    body = admin.post("/api/tickets/batch", json={"items": items}).json()
    assert [r["status"] for r in body["results"]] == ["created", "error"]
    assert body["results"][1]["code"] == "idempotency_mismatch"
    changed = [ticket_body(visitor_name="Changed", idempotency_key="k")]
    again = admin.post("/api/tickets/batch", json={"items": changed}).json()
    assert again["results"][0]["code"] == "idempotency_mismatch"


def test_batch_header_key_derives_item_keys(admin):
    headers = {"Idempotency-Key": "run-1"}
    items = [ticket_body(), ticket_body(external_code="Y")]
    admin.post("/api/tickets/batch", json={"items": items}, headers=headers)
    body = admin.post("/api/tickets/batch", json={"items": items}, headers=headers).json()
    assert [r["status"] for r in body["results"]] == ["replayed", "replayed"]


def test_batch_size_is_limited(make_client):
    with make_client(batch_max_size=2) as client:
        login(client)
        response = client.post("/api/tickets/batch", json={"items": [ticket_body()] * 3})
        assert response.status_code == 422
        assert response.json()["code"] == "batch_too_large"
        assert client.post("/api/tickets/batch", json={"items": []}).status_code == 422


def test_a_service_key_works_without_a_session_or_csrf(admin, machine):
    created = new_key(admin, "tickets:read", "tickets:write", "tickets:revoke")
    service_client = machine(created["secret"])
    assert "secret" not in admin.get("/api/service-keys").text
    response = service_client.post("/api/tickets", json=ticket_body())
    assert response.status_code == 201
    ticket = response.json()
    assert service_client.get(f"/api/tickets/{ticket['id']}").status_code == 200
    assert service_client.post(f"/api/tickets/{ticket['id']}/revoke").status_code == 200
    audit = admin.get(f"/api/tickets/{ticket['id']}/audit").json()
    assert {row["actor"] for row in audit} == {"api_key:pos (as manager)"}


def test_the_x_api_key_header_is_accepted_too(admin, make_client):
    secret = new_key(admin, "tickets:read")["secret"]
    with make_client() as client:
        assert client.get("/api/tickets", headers={"X-API-Key": secret}).status_code == 200


def test_scopes_are_enforced(admin, machine):
    reader = machine(new_key(admin, "tickets:read")["secret"])
    assert reader.get("/api/tickets").status_code == 200
    denied = reader.post("/api/tickets", json=ticket_body())
    assert denied.status_code == 403
    assert denied.json()["code"] == "scope"
    ticket = create_ticket(admin)
    assert reader.post(f"/api/tickets/{ticket['id']}/revoke").status_code == 403
    assert reader.post(f"/api/tickets/{ticket['id']}/reissue", json={}).status_code == 403
    # Key management itself is for a signed-in admin only.
    assert reader.get("/api/service-keys").status_code == 401


def test_bad_revoked_or_expired_keys_are_refused(admin, machine, clock):
    created = new_key(admin, "tickets:read")
    assert machine("tqk_wrong").get("/api/tickets").status_code == 401
    assert admin.delete(f"/api/service-keys/{created['id']}").status_code == 200
    assert admin.delete(f"/api/service-keys/{created['id']}").status_code == 200
    assert machine(created["secret"]).get("/api/tickets").status_code == 401
    short = new_key(admin, "tickets:read", expires_at="2026-09-17T09:00:00+00:00")
    clock.now += timedelta(hours=2)
    assert machine(short["secret"]).get("/api/tickets").status_code == 401


def test_a_wrong_key_does_not_fall_back_to_the_cookie(admin):
    response = admin.get("/api/tickets", headers={"Authorization": "Bearer tqk_wrong"})
    assert response.status_code == 401


def test_rotation_keeps_the_old_key_for_the_grace_period(admin, machine, clock):
    created = new_key(admin, "tickets:read")
    rotated = admin.post(f"/api/service-keys/{created['id']}/rotate", json={"grace_minutes": 10})
    assert rotated.status_code == 201
    assert machine(created["secret"]).get("/api/tickets").status_code == 200
    assert machine(rotated.json()["secret"]).get("/api/tickets").status_code == 200
    clock.now += timedelta(minutes=11)
    assert machine(created["secret"]).get("/api/tickets").status_code == 401
    assert machine(rotated.json()["secret"]).get("/api/tickets").status_code == 200
    assert admin.post(f"/api/service-keys/{created['id']}/rotate", json={}).status_code == 409


def test_browser_writes_still_need_the_csrf_token(client):
    login(client)
    del client.headers["X-CSRF-Token"]
    assert client.post("/api/tickets", json=ticket_body()).status_code == 403


def test_reissue_brings_the_same_ticket_back_and_replays_on_retry(admin, registrar):
    old = create_ticket(admin)
    headers = {"Idempotency-Key": "re-1"}
    viable = admin.post(f"/api/tickets/{old['id']}/reissue", json={})
    assert viable.status_code == 200
    assert admin.post(f"/api/tickets/{old['id']}/revoke").status_code == 200
    first = admin.post(f"/api/tickets/{old['id']}/reissue", json={}, headers=headers)
    assert first.status_code == 200
    assert (first.json()["id"], first.json()["state"]) == (old["id"], "issued")
    again = admin.post(f"/api/tickets/{old['id']}/reissue", json={}, headers=headers)
    assert again.json() == first.json()
    assert admin.get("/api/tickets").json()["total"] == 1


def test_reissue_with_a_biostar_failure_leaves_the_ticket_revoked(admin, registrar):
    old = create_ticket(admin)
    admin.post(f"/api/tickets/{old['id']}/revoke")
    registrar.failing.add("activate")
    response = admin.post(f"/api/tickets/{old['id']}/reissue", json={})
    assert response.status_code == 502
    registrar.failing.clear()
    assert admin.get(f"/api/tickets/{old['id']}").json()["state"] == "revoked"


def test_transfer_moves_the_ticket_to_another_session(admin):
    ticket = create_ticket(admin, event_session="Evening")
    response = admin.post(
        f"/api/tickets/{ticket['id']}/transfer",
        json={"event_session": "Matinee", "valid_until": "2026-09-17T16:00"},
    )
    assert response.status_code == 200
    moved = response.json()
    assert (moved["id"], moved["state"], moved["event_session"]) == (
        ticket["id"],
        "issued",
        "Matinee",
    )
    audit = admin.get(f"/api/tickets/{ticket['id']}/audit").json()
    assert [row["action"] for row in audit] == ["ticket.create", "ticket.transfer"]
    revoked = admin.post(f"/api/tickets/{ticket['id']}/revoke")
    assert revoked.status_code == 200
    again = admin.post(f"/api/tickets/{ticket['id']}/transfer", json={"event_session": "Late"})
    assert again.status_code == 409
