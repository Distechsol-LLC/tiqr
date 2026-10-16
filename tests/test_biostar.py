"""Adapter tests against recorded Postman responses and mock rows."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tiqr.biostar import (
    SESSION_HEADER,
    BioStarClient,
    BioStarError,
    BioStarXEventSource,
    BioStarXProvisioner,
    BioStarXRegistrar,
    to_biostar_datetime,
)
from tiqr.models import Registration, Role, SyncCursor, Ticket, TicketState, UsageType, User
from tiqr.repository import SQLiteRepository
from tiqr.settings import BioStarSettings

SUCCESS = {"Response": {"code": "0", "message": "Success"}}
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def recording(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


def collection(name, rows):
    return httpx.Response(200, json={name: {"total": str(len(rows)), "rows": rows}, **SUCCESS})


@pytest.fixture
def config():
    return BioStarSettings(
        "https://biostar.test", "admin", "private-password", ("540598970",), "3", user_id_base=401
    )


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.db")
    repo.initialize()
    yield repo
    repo.close()


@pytest.fixture
def ticket():
    operator = uuid4()
    return Ticket(
        uuid4(),
        None,
        "A" * 32,
        "T-001",
        "Visitor",
        "adult",
        NOW - timedelta(hours=1),
        NOW + timedelta(hours=1),
        UsageType.ONE_TIME,
        TicketState.ISSUED,
        operator,
        operator,
        NOW - timedelta(hours=2),
    )


def persist_ticket(repo, ticket):
    repo.add_user(User(ticket.created_by, "operator", "hash", Role.OPERATOR))
    repo.save_ticket(ticket)


class Server:
    def __init__(self):
        self.requests = []
        self.users = {}
        self.cards = {}
        self.overrides = {}
        self.logins = 0

    def __call__(self, request):
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == "/api/login":
            self.logins += 1
            assert SESSION_HEADER not in request.headers
            return httpx.Response(
                200, json=SUCCESS, headers={SESSION_HEADER: f"session-{self.logins}"}
            )
        assert request.headers[SESSION_HEADER] == f"session-{self.logins}"
        if (method, path) in self.overrides:
            return self.overrides[method, path](request)
        if (method, path) == ("POST", "/api/users"):
            user = json.loads(request.content)["User"]
            self.users[user["user_id"]] = user
            if user["user_id"] == "401":
                return httpx.Response(200, json=recording("user_created"))
            return collection("UserCollection", [{"user_id": user["user_id"]}])
        if (method, path) == ("POST", "/api/cards"):
            card = json.loads(request.content)["CardCollection"]["rows"][0]
            card = {**card, "id": "30"}
            self.cards["30"] = card
            return collection("CardCollection", [card])
        if method == "PUT" and path.startswith("/api/users/"):
            self.users[path.rsplit("/", 1)[1]].update(json.loads(request.content)["User"])
            return httpx.Response(200, json=SUCCESS)
        if (method, path) == ("POST", "/api/v2/users/search"):
            assert json.loads(request.content) == {
                "limit": 0,
                "search_text": None,
                "order_by": "user_id:false",
            }
            rows = recording("user_collection")["UserCollection"]["rows"]
            return collection("UserCollection", rows + list(self.users.values()))
        if (method, path) == ("GET", "/api/cards"):
            offset = int(request.url.params["offset"])
            limit = int(request.url.params["limit"])
            return collection("CardCollection", list(self.cards.values())[offset : offset + limit])
        if method == "DELETE" and path in ("/api/users", "/api/cards"):
            records = self.users if path.endswith("users") else self.cards
            records.pop(request.url.params["id"], None)
            return httpx.Response(200, json=SUCCESS)
        if (method, path) == ("GET", "/api/v2/cards/registered"):
            rows = [c for c in self.cards.values() if c["card_id"] == request.url.params["card_id"]]
            return collection("CardCollection", rows)
        raise AssertionError(f"Unexpected endpoint: {method} {path}")


def client(config, handler):
    return BioStarClient(config, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "base",
    [
        "https://biostar.test",
        "https://biostar.test/",
        "https://biostar.test/api",
        "https://biostar.test/api/",
    ],
)
def test_root_and_api_base_session_and_context_close(config, base, caplog):
    server = Server()
    with client(replace(config, base_url=base), server) as api:
        api.request(
            "POST",
            "/api/v2/users/search/",
            json={"limit": 0, "search_text": None, "order_by": "user_id:false"},
        )
        assert api.session_id == "session-1"
    assert [r.url.path for r in server.requests] == ["/api/login", "/api/v2/users/search"]
    assert json.loads(server.requests[0].content) == {
        "User": {"login_id": "admin", "password": config.password}
    }
    assert config.password not in caplog.text
    assert "session-1" not in caplog.text
    with pytest.raises(RuntimeError, match="closed"):
        api.search_users()


def test_login_error_envelope_precedes_missing_header(config):
    with (
        client(config, lambda r: httpx.Response(400, json=recording("login_failed"))) as api,
        pytest.raises(BioStarError) as failure,
    ):
        api.login()
    assert failure.value.code == "101"
    assert failure.value.http_status == 400
    assert "invalid username or password" in str(failure.value)
    assert SESSION_HEADER not in str(failure.value)


def test_login_missing_header(config):
    with (
        client(config, lambda r: httpx.Response(200, json=SUCCESS)) as api,
        pytest.raises(BioStarError, match=SESSION_HEADER),
    ):
        api.login()


def test_recorded_error_and_user_collection(config):
    server = Server()
    with client(config, server) as api:
        assert [row["user_id"] for row in api.search_users()] == ["2", "3", "61000"]
        server.overrides["POST", "/api/v2/users/search"] = lambda r: httpx.Response(
            400, json=recording("error_parse_json")
        )
        with pytest.raises(BioStarError) as failure:
            api.search_users()
    assert failure.value.code == "700"
    assert failure.value.http_status == 400
    assert "Failed to parse json data." in str(failure.value)


@pytest.mark.parametrize("always_expired", [False, True])
def test_401_retries_exactly_once(config, always_expired):
    server = Server()
    calls = []

    def expires(request):
        calls.append(request)
        if len(calls) == 1 or always_expired:
            return httpx.Response(401, text="expired")
        return httpx.Response(200, json=recording("user_collection"))

    server.overrides["POST", "/api/v2/users/search"] = expires
    with client(config, server) as api:
        if always_expired:
            with pytest.raises(BioStarError) as failure:
                api.search_users()
            assert failure.value.http_status == 401
        else:
            assert len(api.search_users()) == 3
    assert server.logins == 2
    assert len(calls) == 2
    assert calls[0].headers[SESSION_HEADER] == "session-1"
    assert calls[1].headers[SESSION_HEADER] == "session-2"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"Response": []},
        {"Response": {}},
        {"Response": {"code": True}},
        {"Response": {"code": "0"}},
        {"Response": {"code": "oops", "message": "bad"}},
    ],
)
def test_malformed_envelope_fails_closed(config, payload):
    with (
        client(config, lambda r: httpx.Response(200, json=payload)) as api,
        pytest.raises(BioStarError),
    ):
        api.login()


@pytest.mark.parametrize("status", [302, 400, 500])
def test_http_failure_with_success_envelope_fails_closed(config, status):
    with (
        client(
            config,
            lambda r: httpx.Response(status, json=SUCCESS, headers={SESSION_HEADER: "session"}),
        ) as api,
        pytest.raises(BioStarError) as failure,
    ):
        api.login()
    assert failure.value.http_status == status


def test_non_json_and_transport_failure(config):
    with client(config, lambda r: httpx.Response(502, text="<html>Bad Gateway</html>")) as api:
        with pytest.raises(BioStarError, match="JSON") as failure:
            api.login()
        assert failure.value.http_status == 502

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with client(config, timeout) as api, pytest.raises(BioStarError, match="transport"):
        api.login()


@pytest.mark.parametrize(
    "payload",
    [
        SUCCESS,
        {"UserCollection": {"rows": None}, **SUCCESS},
        {"UserCollection": {"rows": [1]}, **SUCCESS},
    ],
)
def test_malformed_collection_is_not_absence(config, payload):
    server = Server()
    server.overrides["POST", "/api/v2/users/search"] = lambda r: httpx.Response(200, json=payload)
    with client(config, server) as api, pytest.raises(BioStarError, match="collection"):
        api.search_users()


def test_registration_window_group_card_assignment_and_no_operator_permission(
    config, repository, ticket
):
    server = Server()
    persist_ticket(repository, ticket)
    shifted = replace(ticket, valid_from=ticket.valid_from.astimezone(timezone(timedelta(hours=4))))
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        assert registrar.register(shifted) == "401"
    assert server.users["401"] == {
        "user_id": "401",
        "name": "Visitor",
        "user_group_id": {"id": "1"},
        "disabled": "false",
        "start_datetime": "2026-09-17T11:00:00.00Z",
        "expiry_datetime": "2026-09-17T13:00:00.00Z",
        "access_groups": [{"id": "3"}],
        "cards": [{"id": "30"}],
    }
    card_request = next(
        r for r in server.requests if r.method == "POST" and r.url.path == "/api/cards"
    )
    assert json.loads(card_request.content) == {
        "CardCollection": {
            "rows": [{"card_id": ticket.qr_payload, "card_type": {"id": "6", "type": "6"}}]
        }
    }
    assert repository.get_registration("401") == Registration("401", "30")
    assert repository.get_ticket(ticket.id) == ticket


@pytest.mark.parametrize("length", [0, 31, 33])
def test_register_rejects_non_32_payload_before_http(config, repository, ticket, length):
    server = Server()
    with client(config, server) as api, pytest.raises(ValueError, match="exactly 32"):
        BioStarXRegistrar(api, repository).register(replace(ticket, qr_payload="A" * length))
    assert server.requests == []


def test_window_and_disable_use_verified_fields(config, repository, ticket):
    server = Server()
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        external_id = registrar.register(ticket)
        registrar.set_window(external_id, NOW, NOW + timedelta(days=1))
        registrar.deactivate(external_id)
        assert server.users[external_id]["disabled"] == "true"
        assert server.users[external_id]["start_datetime"] == "2026-09-17T12:00:00.00Z"
        assert server.users[external_id]["expiry_datetime"] == "2026-09-18T12:00:00.00Z"
        with pytest.raises(ValueError):
            registrar.set_window(external_id, NOW.replace(tzinfo=None), NOW)
        with pytest.raises(ValueError):
            registrar.set_window(external_id, NOW, NOW - timedelta(seconds=1))
    assert json.loads(server.requests[-1].content) == {"User": {"disabled": "true"}}


def test_assignment_failure_rolls_back_user_before_card_and_preserves_primary(
    config, repository, ticket
):
    server = Server()
    server.overrides["PUT", "/api/users/401"] = lambda r: httpx.Response(
        400, json=recording("error_parse_json")
    )
    with client(config, server) as api, pytest.raises(BioStarError) as failure:
        BioStarXRegistrar(api, repository).register(ticket)
    assert failure.value.code == "700"
    assert [r.url.path for r in server.requests if r.method == "DELETE"] == [
        "/api/users",
        "/api/cards",
    ]
    assert repository.get_registration("401") == Registration("401", "30", True, True)
    assert not server.users
    assert not server.cards


def test_rollback_failure_is_reported_and_can_resume_after_restart(config, repository, ticket):
    server = Server()
    for path in ("/api/users/401", "/api/cards"):
        method = "PUT" if path.endswith("401") else "DELETE"
        server.overrides[method, path] = lambda r: httpx.Response(
            400, json=recording("error_parse_json")
        )
    with client(config, server) as api, pytest.raises(BioStarError) as failure:
        BioStarXRegistrar(api, repository).register(ticket)
    assert failure.value.code == "700"
    assert "rollback failed" in failure.value.__notes__[0]
    assert repository.get_registration("401") == Registration("401", "30", True, False)
    del server.overrides["DELETE", "/api/cards"]
    before = len(server.requests)
    with client(config, server) as api:
        BioStarXRegistrar(api, repository).remove("401")
        BioStarXRegistrar(api, repository).remove("401")
    assert [r.url.path for r in server.requests[before:] if r.method == "DELETE"] == ["/api/cards"]
    assert repository.get_registration("401") == Registration("401", "30", True, True)


def test_cleanup_survives_database_reopen_and_never_reuses_ids(config, tmp_path, ticket):
    path = tmp_path / "restart.db"
    server = Server()
    first = SQLiteRepository(path)
    first.initialize()
    with client(config, server) as api:
        assert BioStarXRegistrar(api, first).register(ticket) == "401"
    first.close()
    second = SQLiteRepository(path)
    second.initialize()
    try:
        with client(config, server) as api:
            registrar = BioStarXRegistrar(api, second)
            registrar.remove("401")
            assert registrar.register(ticket) == "402"
        assert second.get_registration("401") == Registration("401", "30", True, True)
    finally:
        second.close()


def test_failed_user_creation_consumes_id_without_deleting_other_users(config, repository, ticket):
    server = Server()
    server.overrides["POST", "/api/users"] = lambda r: httpx.Response(
        400, json=recording("error_parse_json")
    )
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        with pytest.raises(BioStarError):
            registrar.register(ticket)
        del server.overrides["POST", "/api/users"]
        assert registrar.register(ticket) == "402"
    assert not any(r.method == "DELETE" for r in server.requests)


@pytest.mark.parametrize("resource", ["users", "cards"])
def test_silent_delete_does_not_mark_cleanup_complete(config, repository, ticket, resource):
    server = Server()
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        registrar.register(ticket)
        server.overrides["DELETE", f"/api/{resource}"] = lambda r: httpx.Response(200, json=SUCCESS)
        with pytest.raises(BioStarError, match="still exists"):
            registrar.remove("401")
        progress = repository.get_registration("401")
        assert progress.user_removed == (resource == "cards")
        assert not progress.card_removed
        del server.overrides["DELETE", f"/api/{resource}"]
        registrar.remove("401")
    assert repository.get_registration("401") == Registration("401", "30", True, True)


def test_cleanup_missing_records_and_unknown_mapping(config, repository):
    repository.save_registration(Registration("401", "30"))
    server = Server()
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        registrar.remove("401")
        count = len(server.requests)
        registrar.remove("401")
        assert len(server.requests) == count
        with pytest.raises(BioStarError, match="persisted"):
            registrar.remove("999")
    assert not any(r.method == "DELETE" for r in server.requests)
    assert repository.get_registration("401") == Registration("401", "30", True, True)


def test_delete_error_is_only_accepted_after_verified_absence(config, repository, ticket):
    server = Server()

    def racing_delete(request):
        server.users.pop("401")
        return httpx.Response(
            400, json={"Response": {"code": "201", "message": "User can not be found with id"}}
        )

    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, repository)
        registrar.register(ticket)
        server.overrides["DELETE", "/api/users"] = racing_delete
        registrar.remove("401")
    assert repository.get_registration("401") == Registration("401", "30", True, True)


def test_card_internal_id_lookup_fallback(config, repository, ticket):
    server = Server()

    def created_without_id(request):
        server.cards["30"] = {"id": "30", "card_id": ticket.qr_payload}
        return httpx.Response(200, json=SUCCESS)

    server.overrides["POST", "/api/cards"] = created_without_id
    with client(config, server) as api:
        assert BioStarXRegistrar(api, repository).register(ticket) == "401"
    assert repository.get_registration("401").card_id == "30"
    assert server.users["401"]["cards"] == [{"id": "30"}]


def test_card_creation_failure_rolls_back_user_and_checks_card_absence(config, repository, ticket):
    server = Server()
    server.overrides["POST", "/api/cards"] = lambda r: httpx.Response(
        400, json=recording("error_parse_json")
    )
    with client(config, server) as api, pytest.raises(BioStarError) as failure:
        BioStarXRegistrar(api, repository).register(ticket)
    assert failure.value.code == "700"
    assert repository.get_registration("401") == Registration("401", "", True, True)
    assert [r.url.path for r in server.requests if r.method == "DELETE"] == ["/api/users"]


def test_card_cleanup_searches_beyond_first_page(config, repository):
    server = Server()
    server.cards = {str(i): {"id": str(i)} for i in range(501)}
    repository.save_registration(Registration("401", "500", user_removed=True))
    with client(config, server) as api:
        BioStarXRegistrar(api, repository).remove("401")
    assert "500" not in server.cards
    assert any(r.url.params.get("offset") == "500" for r in server.requests)


def scan(event_id="scan-1", when=NOW - timedelta(seconds=3), code="4133", user_id="401"):
    return {
        "id": event_id,
        "datetime": to_biostar_datetime(when),
        "server_datetime": to_biostar_datetime(when + timedelta(hours=4, seconds=3)),
        "device_id": {"id": "540598970", "name": "XPass Q2"},
        "event_type_id": {"code": code},
        "user_id": {"user_id": user_id, "name": "Visitor"},
    }


class EventServer(Server):
    def __init__(self, rows=None, types=None):
        super().__init__()
        self.rows = rows or []
        self.types = types or [
            {"code": "4133", "name": "VERIFY_SUCCESS_QR"},
            {"code": "6402", "name": "ACCESS_DENIED_DISABLED"},
            {"code": "8192", "name": "ENROLL_SUCCESS"},
        ]
        self.queries = []

    def __call__(self, request):
        if request.url.path == "/api/event_types":
            self.requests.append(request)
            return collection("EventTypeCollection", self.types)
        if request.url.path == "/api/events/search":
            self.requests.append(request)
            query = json.loads(request.content)["Query"]
            self.queries.append(query)
            assert set(query) == {"limit", "conditions", "orders"}
            assert query["orders"] == [{"column": "datetime", "descending": False}]
            device = query["conditions"][1]
            assert device["column"] == "device_id"
            assert device["operator"] == 0
            assert len(device["values"]) == 1
            assert query["conditions"][0]["operator"] == 3
            start, end = map(datetime.fromisoformat, query["conditions"][0]["values"])
            rows = []
            for row in self.rows:
                if row.get("device_id", {}).get("id") != device["values"][0]:
                    continue
                try:
                    timestamp = datetime.fromisoformat(row["datetime"])
                except KeyError, ValueError, TypeError:
                    rows.append(row)
                    continue
                if timestamp.tzinfo is None or start <= timestamp <= end:
                    rows.append(row)
            rows.sort(key=lambda row: row.get("datetime", ""))
            return collection("EventCollection", rows[: query["limit"]])
        return super().__call__(request)


def test_nested_scan_fields_types_system_filter_device_filter_and_server_datetime(config):
    rows = [scan(), scan("denied", code="6402", user_id=""), scan("enrolled", code="8192")]
    rows.append({**scan("wrong-device"), "device_id": {"id": "other"}})
    server = EventServer(rows)
    with client(config, server) as api:
        events, cursor = BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)
    assert len(events) == 2
    assert {event.event_id for event in events} == {"scan-1", "denied"}
    granted = next(event for event in events if event.granted)
    assert granted.external_id == "401"
    assert granted.occurred_at == NOW - timedelta(seconds=3)
    denied = next(event for event in events if not event.granted)
    assert denied.external_id is None
    assert json.loads(cursor.token) == {"until": NOW.isoformat()}
    assert server.queries[0]["conditions"][0]["values"] == [
        "2026-09-17T11:45:00.00Z",
        "2026-09-17T12:00:00.00Z",
    ]


@pytest.mark.parametrize(
    ("name", "granted"),
    [
        ("VERIFY_SUCCESS_QR", True),
        ("IDENTIFY_SUCCESS_CARD", True),
        ("ACCESS_GRANTED", True),
        ("DUAL_AUTH_SUCCESS", True),
        ("VERIFY_FAIL_QR", False),
        ("IDENTIFY_FAIL", False),
        ("ACCESS_DENIED_DISABLED", False),
        ("AUTH_FAILED", False),
        ("DUAL_AUTH_FAIL", False),
        ("ENROLL_SUCCESS", None),
        ("PARTIAL_UPDATE_SUCCESS", None),
    ],
)
def test_reference_authentication_prefixes(config, name, granted):
    server = EventServer([scan(code="123")], [{"code": 123, "name": name.lower()}])
    with client(config, server) as api:
        events, _ = BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)
    assert [event.granted for event in events] == ([] if granted is None else [granted])


@pytest.mark.parametrize("missing", ["id", "datetime"])
def test_missing_scan_identity_or_date_fails_whole_batch(config, missing):
    invalid = scan("invalid")
    del invalid[missing]
    server = EventServer([scan(), invalid])
    with client(config, server) as api, pytest.raises(BioStarError):
        BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)


def test_naive_timestamps_are_rejected(config):
    with pytest.raises(ValueError):
        to_biostar_datetime(NOW.replace(tzinfo=None))
    server = EventServer([{**scan(), "datetime": "2026-09-17T11:59:57"}])
    with client(config, server) as api, pytest.raises(BioStarError, match="timezone-aware"):
        BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)


def test_initial_cursor_uses_earliest_ticket_and_later_cursor_keeps_downtime_backlog(
    config, repository, ticket
):
    ticket = replace(ticket, created_at=NOW - timedelta(days=3))
    persist_ticket(repository, ticket)
    server = EventServer([scan("old", when=NOW - timedelta(days=2))])
    with client(config, server) as api:
        source = BioStarXEventSource(api, repository, clock=lambda: NOW)
        events, cursor = source.fetch_events(None)
        assert [event.event_id for event in events] == ["old"]
        assert server.queries[0]["conditions"][0]["values"][0] == to_biostar_datetime(
            ticket.created_at
        )
        repository.save_cursor(cursor)
        source = BioStarXEventSource(api, repository, clock=lambda: NOW + timedelta(days=4))
        source.fetch_events(repository.get_cursor())
    assert server.queries[-1]["conditions"][0]["values"] == [
        to_biostar_datetime(NOW - timedelta(minutes=15)),
        to_biostar_datetime(NOW + timedelta(days=4)),
    ]
    assert repository.get_cursor() == cursor
    assert repository.get_ticket(ticket.id) == ticket


def test_delayed_scans_reappear_in_overlap(config):
    server = EventServer()
    with client(config, server) as api:
        source = BioStarXEventSource(api, clock=lambda: NOW)
        _, cursor = source.fetch_events(None)
        server.rows = [scan("delayed", when=NOW - timedelta(minutes=14))]
        source.clock = lambda: NOW + timedelta(minutes=1)
        events, _ = source.fetch_events(cursor)
    assert [event.event_id for event in events] == ["delayed"]
    assert len([r for r in server.requests if r.url.path == "/api/event_types"]) == 1


def test_adaptive_ranges_are_complete_sorted_and_deduplicated(config):
    rows = [scan(str(i), when=NOW - timedelta(seconds=i * 3)) for i in range(6)]
    server = EventServer(rows)
    with client(config, server) as api:
        source = BioStarXEventSource(api, clock=lambda: NOW)
        source.BATCH_LIMIT = 3
        events, cursor = source.fetch_events(None)
    assert len(server.queries) > 1
    assert [event.event_id for event in events] == ["5", "4", "3", "2", "1", "0"]
    assert len({event.event_id for event in events}) == 6
    assert json.loads(cursor.token)["until"] == NOW.isoformat()


def test_one_second_saturation_fails_without_advancing_persisted_cursor(config, repository):
    previous = SyncCursor(json.dumps({"until": (NOW - timedelta(hours=1)).isoformat()}))
    repository.save_cursor(previous)
    server = EventServer([scan(str(i)) for i in range(100)])
    with client(config, server) as api, pytest.raises(BioStarError, match="saturated"):
        BioStarXEventSource(api, repository, clock=lambda: NOW).fetch_events(previous)
    assert repository.get_cursor() == previous
    assert all("offset" not in query for query in server.queries)


@pytest.mark.parametrize(
    "token",
    [
        "bad",
        "[]",
        "{}",
        '{"until": "bad"}',
        '{"until": "2026-09-17T12:00:00"}',
        '{"until": "2026-09-18T12:00:00Z"}',
    ],
)
def test_invalid_or_future_cursor_fails_closed(config, token):
    server = EventServer()
    with client(config, server) as api, pytest.raises(BioStarError):
        BioStarXEventSource(api, clock=lambda: NOW).fetch_events(SyncCursor(token))
    assert server.requests == []


def test_event_reference_failure_does_not_return_empty_success(config):
    server = EventServer()
    server.types = [{"code": "4133"}]
    with client(config, server) as api, pytest.raises(BioStarError, match="event type"):
        BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)
    assert not server.queries


def test_reauthentication_failure_preserves_recorded_login_error(config):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(200, json=SUCCESS, headers={SESSION_HEADER: "session"})
        if request.url.path == "/api/login":
            return httpx.Response(400, json=recording("login_failed"))
        return httpx.Response(401, text="expired")

    with client(config, handler) as api:
        with pytest.raises(BioStarError) as failure:
            api.search_users()
        assert api.session_id is None
    assert failure.value.code == "101"
    assert calls == ["/api/login", "/api/v2/users/search", "/api/login"]


def test_cleanup_progress_persists_after_database_reopen(config, tmp_path, ticket):
    path = tmp_path / "progress.db"
    server = Server()
    server.overrides["DELETE", "/api/cards"] = lambda r: httpx.Response(
        400, json=recording("error_parse_json")
    )
    first = SQLiteRepository(path)
    first.initialize()
    with client(config, server) as api:
        registrar = BioStarXRegistrar(api, first)
        registrar.register(ticket)
        with pytest.raises(BioStarError):
            registrar.remove("401")
    first.close()
    second = SQLiteRepository(path)
    second.initialize()
    try:
        assert second.get_registration("401") == Registration("401", "30", True, False)
        del server.overrides["DELETE", "/api/cards"]
        before = len(server.requests)
        with client(config, server) as api:
            BioStarXRegistrar(api, second).remove("401")
        assert [r.url.path for r in server.requests[before:] if r.method == "DELETE"] == [
            "/api/cards"
        ]
        assert second.get_registration("401") == Registration("401", "30", True, True)
    finally:
        second.close()


def test_registration_persistence_failure_attempts_cleanup_and_keeps_primary(
    config, repository, ticket, monkeypatch
):
    server = Server()
    saved_save = repository.save_registration
    calls = []
    primary = RuntimeError("Registration persistence failed")

    def failing_once(registration):
        calls.append(registration)
        if len(calls) == 1:
            raise primary
        saved_save(registration)

    monkeypatch.setattr(repository, "save_registration", failing_once)
    with client(config, server) as api, pytest.raises(RuntimeError) as failure:
        BioStarXRegistrar(api, repository).register(ticket)
    assert failure.value is primary
    assert not server.users
    assert not server.cards
    assert repository.get_registration("401") == Registration("401", "", True, True)


def test_allocation_is_not_wrapped_in_registration_transaction(
    config, repository, ticket, monkeypatch
):
    saved_allocate = repository.allocate

    def allocate(name, start):
        assert not repository._connection.in_transaction
        assert name == "biostar_user_id"
        assert start == config.user_id_base
        return saved_allocate(name, start)

    monkeypatch.setattr(repository, "allocate", allocate)
    with client(config, Server()) as api:
        assert BioStarXRegistrar(api, repository).register(ticket) == "401"


def test_user_rollback_failure_never_deletes_assigned_card(config, repository, ticket):
    server = Server()
    for method, path in (("PUT", "/api/users/401"), ("DELETE", "/api/users")):
        server.overrides[method, path] = lambda r: httpx.Response(
            400, json=recording("error_parse_json")
        )
    with client(config, server) as api, pytest.raises(BioStarError) as failure:
        BioStarXRegistrar(api, repository).register(ticket)
    assert "rollback failed" in failure.value.__notes__[0]
    assert repository.get_registration("401") == Registration("401", "30")
    assert [r.url.path for r in server.requests if r.method == "DELETE"] == ["/api/users"]


def test_card_pagination_that_does_not_advance_fails_closed(config, repository):
    server = Server()
    server.overrides["GET", "/api/cards"] = lambda r: collection(
        "CardCollection", [{"id": str(i)} for i in range(500)]
    )
    repository.save_registration(Registration("401", "999", user_removed=True))
    with client(config, server) as api, pytest.raises(BioStarError, match="pagination"):
        BioStarXRegistrar(api, repository).remove("401")
    assert not repository.get_registration("401").card_removed
    assert not any(r.method == "DELETE" for r in server.requests)


def test_event_batch_http_failure_does_not_advance_cursor(config, repository):
    previous = SyncCursor(json.dumps({"until": NOW.isoformat()}))
    repository.save_cursor(previous)
    server = EventServer([scan(str(i), when=NOW - timedelta(seconds=i * 3)) for i in range(6)])
    searches = []

    def handler(request):
        if request.url.path == "/api/events/search":
            searches.append(request)
            if len(searches) == 3:
                return httpx.Response(500, json=recording("error_parse_json"))
        return server(request)

    with client(config, handler) as api:
        source = BioStarXEventSource(api, repository, clock=lambda: NOW)
        source.BATCH_LIMIT = 3
        with pytest.raises(BioStarError) as failure:
            source.fetch_events(previous)
    assert failure.value.code == "700"
    assert repository.get_cursor() == previous


def test_conflicting_duplicate_scan_ids_fail_batch(config):
    server = EventServer([scan("duplicate"), scan("duplicate", code="6402")])
    with client(config, server) as api, pytest.raises(BioStarError, match="Conflicting duplicate"):
        BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)


class AccessServer(Server):
    """Stateful stand-in for the BioStar X door, access level and access group endpoints."""

    def __init__(self, groups=None):
        super().__init__()
        self.doors, self.levels, self.groups = {}, {}, dict(groups or {})
        self.writes = []

    def __call__(self, request):
        method, path = request.method, request.url.path
        owned = ("/api/doors", "/api/access_levels", "/api/access_groups", "/api/v2/doors")
        if not path.startswith((*owned, "/api/v2/access_groups")):
            return super().__call__(request)
        self.requests.append(request)
        body = json.loads(request.content) if request.content else {}
        if method != "GET" and not path.endswith("/search"):
            self.writes.append((method, path, body))
        if (method, path) == ("POST", "/api/v2/doors/search"):
            rows = [d for d in self.doors.values() if body["search_text"] in d["name"]]
            return collection("DoorCollection", rows)
        if (method, path) == ("POST", "/api/doors"):
            door = {**body["Door"], "id": str(10 + len(self.doors))}
            self.doors[door["id"]] = door
            return httpx.Response(200, json={"Door": {"id": door["id"]}, **SUCCESS})
        if (method, path) == ("GET", "/api/access_levels"):
            return collection("AccessLevelCollection", list(self.levels.values()))
        if (method, path) == ("POST", "/api/access_levels"):
            level = {**body["AccessLevel"], "id": "20"}
            level["access_level_items"] = [
                {"id": "70", **item} for item in level["access_level_items"]
            ]
            self.levels["20"] = level
            return httpx.Response(200, json={"AccessLevel": {"id": "20"}, **SUCCESS})
        if method == "PUT" and path.startswith("/api/access_levels/"):
            self.levels[path.rsplit("/", 1)[1]].update(body["AccessLevel"])
            return httpx.Response(200, json=SUCCESS)
        if (method, path) == ("POST", "/api/v2/access_groups/search"):
            return collection("AccessGroupCollection", list(self.groups.values()))
        if (method, path) == ("POST", "/api/access_groups"):
            group = {**body["AccessGroup"], "id": "30"}
            self.groups["30"] = group
            return httpx.Response(200, json={"AccessGroup": {"id": "30"}, **SUCCESS})
        if method == "PUT" and path.startswith("/api/access_groups/"):
            self.groups[path.rsplit("/", 1)[1]].update(body["AccessGroup"])
            return httpx.Response(200, json=SUCCESS)
        if method == "GET" and path.startswith("/api/access_groups/"):
            known = path.rsplit("/", 1)[1] in self.groups
            code = "0" if known else "601"
            return httpx.Response(200, json={"Response": {"code": code, "message": "x"}})
        raise AssertionError(f"Unexpected endpoint: {method} {path}")


@pytest.fixture
def managed(config):
    return replace(config, device_ids=("540598970", "540598971"), access_group_id="")


def test_provisioning_builds_one_group_one_level_and_a_door_per_reader(managed):
    server = AccessServer()
    with client(managed, server) as api:
        assert BioStarXProvisioner(api).ensure_access() == "30"
    assert sorted(door["name"] for door in server.doors.values()) == [
        "TiQR 540598970",
        "TiQR 540598971",
    ]
    assert {door["entry_device_id"]["id"] for door in server.doors.values()} == {
        540598970,
        540598971,
    }
    assert {(door["open_duration"], door["open_timeout"]) for door in server.doors.values()} == {
        (3, 10)
    }
    (level,) = server.levels.values()
    assert level["name"] == "TiQR AL"
    (item,) = level["access_level_items"]
    assert item["schedule_id"] == {"id": "1"}
    assert {door["id"] for door in item["doors"]} == set(server.doors)
    (group,) = server.groups.values()
    assert (group["name"], group["access_levels"]) == ("TiQR AG", [{"id": "20"}])


def test_provisioning_twice_creates_nothing_new(managed):
    server = AccessServer()
    with client(managed, server) as api:
        BioStarXProvisioner(api).ensure_access()
        server.writes.clear()
        assert BioStarXProvisioner(api).ensure_access() == "30"
    assert server.writes == []


def test_provisioning_adds_a_new_reader_to_the_existing_level(managed):
    server = AccessServer()
    with client(replace(managed, device_ids=("540598970",)), server) as api:
        BioStarXProvisioner(api).ensure_access()
    server.writes.clear()
    with client(managed, server) as api:
        assert BioStarXProvisioner(api).ensure_access() == "30"
    assert [(method, path) for method, path, _ in server.writes] == [
        ("POST", "/api/doors"),
        ("PUT", "/api/access_levels/20"),
    ]
    (item,) = server.levels["20"]["access_level_items"]
    assert item["id"] == "70"
    assert {door["id"] for door in item["doors"]} == set(server.doors) == {"10", "11"}
    assert len(server.groups) == 1


def test_provisioning_reattaches_a_level_missing_from_the_group(managed):
    server = AccessServer({"30": {"id": "30", "name": "TiQR AG", "access_levels": []}})
    with client(managed, server) as api:
        assert BioStarXProvisioner(api).ensure_access() == "30"
    assert server.groups["30"]["access_levels"] == [{"id": "20"}]


def test_configured_access_group_is_verified_and_left_alone(managed):
    server = AccessServer({"3": {"id": "3", "name": "Staff"}})
    with client(replace(managed, access_group_id="3"), server) as api:
        assert BioStarXProvisioner(api).ensure_access() == "3"
    assert server.writes == []
    assert not server.doors
    assert not server.levels


def test_unknown_configured_access_group_fails(managed):
    with (
        client(replace(managed, access_group_id="9"), AccessServer()) as api,
        pytest.raises(BioStarError),
    ):
        BioStarXProvisioner(api).ensure_access()


def test_registration_uses_the_tiqr_group_found_by_name(managed, repository, ticket):
    server = AccessServer({"30": {"id": "30", "name": "TiQR AG", "access_levels": []}})
    persist_ticket(repository, ticket)
    with client(managed, server) as api:
        assert BioStarXRegistrar(api, repository).register(ticket) == "401"
    assert server.users["401"]["access_groups"] == [{"id": "30"}]


def test_registration_without_a_provisioned_group_points_to_setup(managed, repository, ticket):
    persist_ticket(repository, ticket)
    with client(managed, AccessServer()) as api, pytest.raises(BioStarError, match="tiqr setup"):
        BioStarXRegistrar(api, repository).register(ticket)
    assert not repository.get_registration("401")


def test_polling_queries_every_reader_and_ignores_others(managed):
    rows = [
        scan("one"),
        {**scan("two"), "device_id": {"id": "540598971"}},
        {**scan("other"), "device_id": {"id": "999"}},
    ]
    server = EventServer(rows)
    with client(managed, server) as api:
        events, _ = BioStarXEventSource(api, clock=lambda: NOW).fetch_events(None)
    assert {event.event_id for event in events} == {"one", "two"}
    assert [q["conditions"][1]["values"] for q in server.queries] == [["540598970"], ["540598971"]]
