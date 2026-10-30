import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2
import pytest

from tests.api.test_api import create_ticket, login
from tiqr.api.config import ServerConfig
from tiqr.api.endpoints import passage_record
from tiqr.api.schemas import PassageOut
from tiqr.api.webhook import ATTEMPTS, SIGNATURE_HEADER, TIMESTAMP_HEADER, PassWebhook, sign, verify
from tiqr.core.models import RawEvent

SECRET = "webhook-secret"
NOW = 1_800_000_000


def passage(event_id="scan-1"):
    return PassageOut(
        event_id=event_id,
        ticket_id=None,
        external_code=None,
        event_time=datetime(2026, 9, 17, 12, tzinfo=UTC),
        point_id="7",
        point_name="Gate A",
        direction="entry",
        granted=True,
        outcome="applied",
    )


def make_webhook(handler, sleeps=None):
    return PassWebhook(
        "https://example.test/hook",
        SECRET,
        client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        clock=lambda: NOW,
        sleep=sleeps.append if sleeps is not None else lambda seconds: None,
    )


def test_signature_is_hmac_sha256_over_timestamp_and_body():
    body = b'{"event_id":"scan-1"}'
    expected = hmac.new(SECRET.encode(), b"1800000000." + body, hashlib.sha256).hexdigest()
    assert sign(SECRET, NOW, body) == f"sha256={expected}"


def test_signature_verifies_only_with_the_secret_timestamp_and_body():
    body = b'{"event_id":"scan-1"}'
    signature = sign(SECRET, NOW, body)
    assert verify(SECRET, NOW, body, signature)
    assert not verify("other-secret", NOW, body, signature)
    assert not verify(SECRET, NOW + 1, body, signature)
    assert not verify(SECRET, NOW, b'{"event_id":"scan-2"}', signature)
    assert not verify(SECRET, NOW, body, "sha256=00")


def test_delivery_posts_the_signed_body_and_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(200)

    assert make_webhook(handler).deliver(passage())
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://example.test/hook"
    assert request.headers[TIMESTAMP_HEADER] == str(NOW)
    assert verify(
        SECRET,
        int(request.headers[TIMESTAMP_HEADER]),
        request.content,
        request.headers[SIGNATURE_HEADER],
    )
    assert json.loads(request.content) == json.loads(passage().model_dump_json())


def test_failed_deliveries_retry_with_backoff_then_give_up():
    attempts = []
    sleeps = []

    def handler(request):
        attempts.append(request)
        return httpx2.Response(503)

    assert not make_webhook(handler, sleeps).deliver(passage())
    assert len(attempts) == ATTEMPTS
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


def test_a_retry_after_a_failure_delivers():
    responses = iter([httpx2.Response(500), httpx2.Response(200)])

    def handler(request):
        return next(responses)

    assert make_webhook(handler).deliver(passage())


def test_webhook_needs_a_secret_when_a_url_is_set():
    assert ServerConfig().pass_webhook_url is None
    with pytest.raises(ValueError):
        ServerConfig(pass_webhook_url="https://example.test/hook")


def test_webhook_stays_off_without_a_url(make_client, service):
    with make_client():
        assert service.on_passage is None
    assert ServerConfig().pass_webhook_url is None


def test_webhook_body_is_the_feed_record(client, service):
    login(client, "admin")
    ticket = create_ticket(client, valid_from="2026-09-17T12:00", external_code="004821930057")
    external_id = service.repository.get_ticket(UUID(ticket["id"])).external_id
    records = []
    service.on_passage = lambda event: records.append(passage_record(service, event))
    service.event_source.events.append(
        RawEvent(
            "scan-1",
            external_id,
            service._now(),
            True,
            point_id="7",
            point_name="Gate A",
            direction="entry",
        )
    )
    assert client.post("/api/sync").json() == {"count": 1}
    feed = client.get("/api/passes").json()["items"]
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx2.Response(200)

    hook = make_webhook(handler)
    for record in records:
        assert hook.deliver(record)
    assert sent == feed
