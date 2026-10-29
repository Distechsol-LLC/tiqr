"""Request dependencies: the server's open state, and the signed-in caller behind a cookie."""

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from tiqr.api.config import ServerConfig
from tiqr.api.errors import ApiError
from tiqr.api.maintenance import Maintenance
from tiqr.api.runtime import Runtime
from tiqr.api.security import CSRF_HEADER, SAFE_METHODS, LoginThrottle, cookie_name
from tiqr.core.auth import SIGNED_OUT, AuthenticationError
from tiqr.core.models import ApiKey, User, WebSession
from tiqr.core.service import SCOPE_READ, SCOPE_REVOKE, SCOPE_WRITE, TicketService


@dataclass(frozen=True, slots=True)
class AppState:
    """Everything the lifespan opens, set on `app.state.tiqr` until shutdown."""

    config: ServerConfig
    runtime: Runtime
    throttle: LoginThrottle
    maintenance: Maintenance

    @property
    def service(self) -> TicketService:
        return self.runtime.service

    @property
    def timezone(self) -> str:
        return self.runtime.settings.default_tz


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    session: WebSession
    token: str


@dataclass(frozen=True, slots=True)
class Caller:
    """Whoever is behind a request: a browser session or a service key. Both act as a user."""

    user: User
    key: ApiKey | None = None

    @property
    def label(self) -> str | None:
        """What the audit log credits besides the account; None for a browser session."""
        return None if self.key is None else f"api_key:{self.key.name}"


def _server(request: Request) -> AppState:
    state: AppState = request.app.state.tiqr
    return state


Server = Annotated[AppState, Depends(_server)]


def _principal(request: Request, server: Server) -> Principal:
    token = request.cookies.get(cookie_name(server.config), "")
    if not token:
        raise AuthenticationError(SIGNED_OUT)
    user, session = server.service.resume_web_session(token)
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise ApiError(403, "csrf", f"Missing or wrong {CSRF_HEADER} header")
    return Principal(user, session, token)


# A signed-in caller; write requests must also carry the session's CSRF token.
Signed = Annotated[Principal, Depends(_principal)]


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer":
        return value.strip()
    return request.headers.get("x-api-key", "").strip()


def _caller(request: Request, server: Server) -> Caller:
    """A service key when one is presented, else the session cookie (with its CSRF check).

    A presented key is never second-guessed by the cookie: a wrong key is a 401. Keys need no
    CSRF token, since a browser never attaches them by itself.
    """
    secret = _bearer(request)
    if secret:
        user, key = server.service.authenticate_api_key(secret)
        return Caller(user, key)
    return Caller(_principal(request, server).user)


def scoped(scope: str, *more: str) -> Callable[..., Caller]:
    """A dependency: the caller, who if a key must hold every given scope.

    Browser sessions are limited by role instead, which the service checks.
    """
    needed = (scope, *more)

    def dependency(caller: Annotated[Caller, Depends(_caller)]) -> Caller:
        if caller.key is not None:
            missing = [name for name in needed if name not in caller.key.scopes]
            if missing:
                raise ApiError(403, "scope", f"The API key lacks the scope {', '.join(missing)}")
        return caller

    return dependency


READER = Annotated[Caller, Depends(scoped(SCOPE_READ))]
WRITER = Annotated[Caller, Depends(scoped(SCOPE_WRITE))]
REVOKER = Annotated[Caller, Depends(scoped(SCOPE_REVOKE))]
IdempotencyKey = Annotated[
    str | None,
    Header(
        max_length=255,
        description="Repeat a create safely: the same key and body replays the first answer",
    ),
]


# Everything else behind the router is refused without a valid license, so a route added later
# is protected until someone lists it here. Names are the handlers', as the OpenAPI IDs are.
LICENSE_EXEMPT = frozenset(
    {
        "health",
        "branding",
        "logo",
        "login",
        "logout",
        "session",
        "license_status",
        "license_request_code",
        "activate_license",
    }
)


def require_license(request: Request, server: Server) -> None:
    route = request.scope.get("route")
    if getattr(route, "name", None) in LICENSE_EXEMPT:
        return
    server.service.require_license()
