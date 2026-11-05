"""Live subscription to BioStar's event WebSocket, so a scan is applied within seconds.

The scheduled sync reads BioStar's database once a minute, which leaves a one-time ticket usable
until the next run. This listener only notices that something happened and asks for a sync; the
sync itself stays the one place that applies events, so nothing is counted twice.
"""

import json
import logging
import os
import ssl
import threading
from collections.abc import Callable
from urllib.parse import urlsplit

from websockets.sync.client import connect

from tiqr.core.biostar import SESSION_HEADER, BioStarClient
from tiqr.core.service import TicketService

logger = logging.getLogger("tiqr.api")

# BioStar saves an event to its database 3 to 10 seconds after announcing it.
SYNC_DELAYS = (4.0, 11.0)
RETRY_DELAY = 5.0
WS_PATH = "/wsapi"
# Set to 1 to log raw pushed messages, to learn their shape. They may hold personal data.
LOG_ENV = "TIQR_LOG_LIVE_EVENTS"
LOG_LIMIT = 2000


def _url(client: BioStarClient) -> str:
    parts = urlsplit(client.settings.base_url)
    scheme = "ws" if parts.scheme == "http" else "wss"
    return f"{scheme}://{parts.netloc}{WS_PATH}"


def _handshake(session_id: str) -> str:
    """The first message BioStar expects on the socket; kept apart so it is easy to adjust."""
    return f"{SESSION_HEADER}={session_id}"


def _is_scan(message: str | bytes) -> bool:
    """Only an Alert carries an access event; device status heartbeats would just add reads."""
    try:
        payload = json.loads(message)
    except ValueError:
        return True
    return not isinstance(payload, dict) or "Alert" in payload


class LiveEvents:
    """Holds a WebSocket open to BioStar and calls `notify` for every message it pushes."""

    def __init__(
        self,
        service: TicketService,
        notify: Callable[..., None],
        *,
        retry_delay: float = RETRY_DELAY,
    ) -> None:
        self._service = service
        self._notify = notify
        self._retry_delay = retry_delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _client(self) -> BioStarClient | None:
        link = self._service.biostar_link
        return link.client if link is not None else None

    def _listen(self, client: BioStarClient) -> None:
        session_id = client.login()
        context = None
        if _url(client).startswith("wss"):
            context = ssl.create_default_context()
            if not client.settings.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
        with connect(_url(client), ssl=context, open_timeout=client.settings.timeout) as socket:
            socket.send(_handshake(session_id))
            logger.info("Subscribed to live BioStar events")
            while not self._stop.is_set():
                try:
                    message = socket.recv(timeout=1)
                except TimeoutError:
                    # Wakes up to notice a stop request, or a swapped connection.
                    if self._client() is not client:
                        return
                    continue
                if os.environ.get(LOG_ENV) == "1":
                    logger.info("Live BioStar message: %s", str(message)[:LOG_LIMIT])
                if _is_scan(message):
                    self._notify(*SYNC_DELAYS)

    def _loop(self) -> None:
        while not self._stop.is_set():
            client = self._client()
            if client is not None:
                try:
                    self._listen(client)
                except Exception as exc:  # noqa: BLE001 - reconnect; polling covers the gap
                    logger.warning("Live BioStar subscription lost: %s", exc)
            self._stop.wait(self._retry_delay)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="tiqr-live-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
