"""Post each new passage to the configured URL, signed with the shared secret.

The feed stays the source of truth: a delivery that never succeeds is logged.
"""

import hashlib
import hmac
import logging
import queue
import threading
import time
from collections.abc import Callable

import httpx2

from tiqr.api.schemas import PassageOut

logger = logging.getLogger("tiqr.api.webhook")

SIGNATURE_HEADER = "X-Tiqr-Signature"
TIMESTAMP_HEADER = "X-Tiqr-Timestamp"
ATTEMPTS = 5
BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 5.0


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: int, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(signature.encode(), sign(secret, timestamp, body).encode())


class PassWebhook:
    def __init__(
        self,
        url: str,
        secret: str,
        *,
        client: httpx2.Client | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.url = url
        self.secret = secret
        self._client = client or httpx2.Client(timeout=TIMEOUT_SECONDS)
        self._clock = clock
        self._sleep = sleep
        self._queue: queue.Queue[PassageOut | None] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="tiqr-webhook", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout)

    def publish(self, record: PassageOut) -> None:
        self._queue.put(record)

    def deliver(self, record: PassageOut) -> bool:
        body = record.model_dump_json().encode()
        for attempt in range(ATTEMPTS):
            timestamp = int(self._clock())
            headers = {
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sign(self.secret, timestamp, body),
                TIMESTAMP_HEADER: str(timestamp),
            }
            try:
                response = self._client.post(self.url, content=body, headers=headers)
                if response.is_success:
                    return True
                reason = f"HTTP {response.status_code}"
            except httpx2.HTTPError as exc:
                reason = type(exc).__name__
            logger.warning(
                "Pass %s delivery attempt %d failed: %s", record.event_id, attempt + 1, reason
            )
            if attempt + 1 < ATTEMPTS:
                self._sleep(BACKOFF_SECONDS * 2**attempt)
        logger.error("Pass %s was not delivered; the feed still has it", record.event_id)
        return False

    def _loop(self) -> None:
        while (record := self._queue.get()) is not None:
            self.deliver(record)
