"""Request dependencies: the server's open state, and the signed-in caller behind a cookie."""

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from tiqr.api.config import ServerConfig
from tiqr.api.errors import ApiError
from tiqr.api.maintenance import Maintenance
from tiqr.api.runtime import Runtime
from tiqr.api.security import CSRF_HEADER, SAFE_METHODS, LoginThrottle, cookie_name
from tiqr.core.auth import SIGNED_OUT, AuthenticationError
from tiqr.core.license import LicenseError
from tiqr.core.models import User, WebSession
from tiqr.core.service import TicketService


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
    status = server.service.license_status()
    if not status.is_valid:
        raise LicenseError(403, "license_required", f"A valid license is required ({status.state})")
