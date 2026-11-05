from datetime import UTC, datetime

PASSWORD = "correct-password"
# Valid from 19:00 to 21:00 in Baku, so the ticket is still live when the clock moves in the tests
BODY = {
    "visitor_name": "Əli",
    "visitor_type": "Visitor",
    "valid_from": "2026-09-17T19:00",
    "valid_until": "2026-09-17T21:00",
    "usage_type": "one_time",
}


def login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def test_active_hours_are_read_by_everyone_and_set_by_staff(client, service, clock):
    # The app builds its service with the server's zone; the test fixture does not, so set it
    service.timezone = "Asia/Baku"
    login(client, "operator")
    assert client.get("/api/active-hours").json() == {
        "start": None,
        "end": None,
        "timezone": "Asia/Baku",
    }
    denied = client.put("/api/active-hours", json={"start": "09:00", "end": "17:00"})
    assert denied.status_code == 403

    login(client, "manager")
    # 08:00 UTC is 12:00 in Baku, inside 09:00 to 17:00
    clock.now = datetime(2026, 9, 17, 8, tzinfo=UTC)
    saved = client.put("/api/active-hours", json={"start": "09:00", "end": "17:00"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"start": "09:00", "end": "17:00", "timezone": "Asia/Baku"}

    login(client, "operator")
    assert client.get("/api/active-hours").json()["start"] == "09:00"


def test_active_hours_must_be_whole_clock_times_given_in_pairs(client, service):
    service.timezone = "Asia/Baku"
    login(client, "admin")

    for body in (
        {"start": "09:00"},
        {"end": "17:00"},
        {"start": "9:00", "end": "17:00"},
        {"start": "24:00", "end": "17:00"},
        {"start": "09:00", "end": "09:00"},
    ):
        assert client.put("/api/active-hours", json=body).status_code == 422, body


def test_tickets_outside_the_hours_are_refused_with_a_code(client, service, clock):
    service.timezone = "Asia/Baku"
    login(client, "manager")
    client.put("/api/active-hours", json={"start": "09:00", "end": "17:00"})

    # 08:00 UTC is 12:00 Baku: inside
    clock.now = datetime(2026, 9, 17, 8, tzinfo=UTC)
    assert client.post("/api/tickets", json=BODY).status_code == 201

    # 14:00 UTC is 18:00 Baku: outside. Six hours on, the idle session has ended, so sign in again
    clock.now = datetime(2026, 9, 17, 14, tzinfo=UTC)
    login(client, "manager")
    refused = client.post("/api/tickets", json=BODY)
    assert refused.status_code == 409
    assert refused.json()["code"] == "outside_active_hours"
    assert "from 09:00 to 17:00 (Asia/Baku)" in refused.json()["detail"]


def test_lifting_the_limit_lets_tickets_be_made_again(client, service, clock):
    service.timezone = "Asia/Baku"
    login(client, "admin")
    client.put("/api/active-hours", json={"start": "09:00", "end": "17:00"})
    clock.now = datetime(2026, 9, 17, 14, tzinfo=UTC)
    login(client, "admin")
    assert client.post("/api/tickets", json=BODY).status_code == 409

    cleared = client.put("/api/active-hours", json={"start": None, "end": None})
    assert cleared.status_code == 200
    assert cleared.json() == {"start": None, "end": None, "timezone": "Asia/Baku"}
    assert client.post("/api/tickets", json=BODY).status_code == 201
