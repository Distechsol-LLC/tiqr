"""Browser-facing protection: the session cookie, CSRF and origin checks, headers, login limits."""

import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from tiqr.api.config import ServerConfig
from tiqr.api.errors import error_response

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DOCS_PREFIX = "/api/docs"
logger = logging.getLogger("tiqr.api")
# A caller's id is reused only if it is short and safe to write to the log.
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_API_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def cookie_name(config: ServerConfig) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, Path=/ and
    # host-only, so nothing on another subdomain or over plain HTTP can plant or read it.
    return "__Host-tiqr-session" if config.secure else "tiqr-session"


def set_session_cookie(response: Response, config: ServerConfig, token: str) -> None:
    # No Max-Age: the browser drops it on exit, and the server ends it on its own schedule.
    response.set_cookie(
        cookie_name(config), token, path="/", secure=config.secure, httponly=True, samesite="strict"
    )


def clear_session_cookie(response: Response, config: ServerConfig) -> None:
    response.delete_cookie(
        cookie_name(config), path="/", secure=config.secure, httponly=True, samesite="strict"
    )


def install_guard(app: FastAPI, config: ServerConfig) -> None:
    """Refuse cross-origin writes, and add the security headers to every response."""

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        # Browsers send Origin on every cross-origin write; other clients hold no victim's cookie.
        if request.method not in SAFE_METHODS and origin is not None and origin != expected:
            response: Response = error_response(403, "cross_origin", "Cross-origin request refused")
        else:
            response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        if config.secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        path = request.url.path
        if path.startswith("/api/") and not path.startswith(DOCS_PREFIX):
            for name, value in _API_HEADERS.items():
                response.headers.setdefault(name, value)
        return response


def install_request_id(app: FastAPI) -> None:
    """Echo the caller's X-Request-Id, or mint one, so an incident can be traced in the log."""

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        logger.info("%s %s request_id=%s", request.method, request.url.path, request_id)
        return response


class LoginThrottle:
    """Failed logins in a sliding window, per client address and per address and username.

    Never per username alone, so nobody can lock an account out from another machine. One
    server process holds the counts, which is all a single-site deployment runs.
    """

    def __init__(
        self,
        *,
        pair_limit: int = 5,
        address_limit: int = 20,
        window: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = (pair_limit, address_limit)
        self._window = window
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(address: str, username: str) -> tuple[str, str]:
        return f"{address}\0{username.strip().casefold()}", address

    def _recent(self, key: str, now: float) -> deque[float]:
        times = self._failures.get(key, deque[float]())
        while times and times[0] <= now - self._window:
            times.popleft()
        return times

    def retry_after(self, address: str, username: str) -> int | None:
        """Seconds until this login may be tried, or None when it may be tried now."""
        with self._lock:
            now = self._clock()
            waits = [
                times[-limit] + self._window - now
                for key, limit in zip(self._keys(address, username), self._limits, strict=True)
                if len(times := self._recent(key, now)) >= limit
            ]
        return math.ceil(max(waits)) if waits else None

    def failed(self, address: str, username: str) -> None:
        with self._lock:
            now = self._clock()
            for key in self._keys(address, username):
                self._failures[key] = self._recent(key, now)
                self._failures[key].append(now)
            # Bounds memory against many addresses; expired entries go first.
            if len(self._failures) > 4096:  # noqa: PLR2004 - a soft cap, not a limit
                self._failures = {
                    key: times for key in self._failures if (times := self._recent(key, now))
                }

    def succeeded(self, address: str, username: str) -> None:
        with self._lock:
            self._failures.pop(self._keys(address, username)[0], None)
