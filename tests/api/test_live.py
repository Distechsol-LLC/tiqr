"""The live listener asks for a sync when BioStar pushes a scan, and ignores device heartbeats."""

import threading
from types import SimpleNamespace
from typing import Any

from websockets.sync.server import ServerConnection, serve

from tiqr.api.live import SYNC_DELAYS, LiveEvents

ALERT = '{"Alert": {"event_id": {"id": "1"}}, "id": "2"}'
HEARTBEAT = '{"Device": {"id": "538159342", "status": "0"}, "id": "3"}'


def _run(messages: list[str], expected_calls: int) -> tuple[list[str], list[tuple[float, ...]]]:
    received: list[str] = []
    calls: list[tuple[float, ...]] = []
    done = threading.Event()
    requested = threading.Event()

    def handler(connection: ServerConnection) -> None:
        received.append(str(connection.recv(timeout=5)))
        for message in messages:
            connection.send(message)
        done.wait(5)

    def notify(*delays: float) -> None:
        calls.append(delays)
        if len(calls) >= expected_calls:
            requested.set()

    with serve(handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        settings = SimpleNamespace(
            base_url=f"http://127.0.0.1:{port}/api", verify_tls=False, timeout=5
        )
        client = SimpleNamespace(settings=settings, login=lambda: "session-1")
        service: Any = SimpleNamespace(biostar_link=SimpleNamespace(client=client))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        live = LiveEvents(service, notify, retry_delay=0.1)
        live.start()
        try:
            requested.wait(2)
        finally:
            done.set()
            live.stop()
            server.shutdown()
    return received, calls


def test_pushed_scan_requests_sync() -> None:
    received, calls = _run([ALERT], expected_calls=1)
    assert received == ["bs-session-id=session-1"]
    assert calls[0] == SYNC_DELAYS


def test_device_heartbeat_does_not_request_sync() -> None:
    _, calls = _run([HEARTBEAT], expected_calls=1)
    assert calls == []


def test_no_biostar_connection_is_idle() -> None:
    service: Any = SimpleNamespace(biostar_link=None)
    live = LiveEvents(service, lambda *_: None, retry_delay=0.05)
    live.start()
    live.stop()
