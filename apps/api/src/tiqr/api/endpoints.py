"""The JSON API: one endpoint per CLI command, all deciding through `TicketService`.

Handlers are plain functions, so FastAPI runs them on its thread pool: the core is synchronous,
and its repository and BioStar client serialize their own access.
"""

from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from tiqr.api import __version__
from tiqr.api.deps import AppState, Server, Signed
from tiqr.api.errors import ApiError
from tiqr.api.schemas import (
    AssignIn,
    ConfigOut,
    CountOut,
    ErrorOut,
    FieldErrorsOut,
    HealthOut,
    LoginIn,
    SessionOut,
    StatsOut,
    TicketIn,
    TicketOut,
    UserIn,
    UserOut,
    UserPatch,
)
from tiqr.api.security import clear_session_cookie, cookie_name, set_session_cookie
from tiqr.core.auth import WEB_SESSION_IDLE, AuthenticationError
from tiqr.core.localtime import parse_input_datetime
from tiqr.core.models import Ticket, TicketState

router = APIRouter(
    prefix="/api",
    # Any handler can fail unexpectedly, and the error handler answers 500 for all of them.
    responses={500: {"model": ErrorOut, "description": "Unexpected server error"}},
)

_PDF: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "The badge, one A4 page"}
}
_IDLE_SECONDS = int(WEB_SESSION_IDLE.total_seconds())
_REFUSALS: dict[int, str] = {
    401: "Not signed in, or sign-in was refused",
    403: "Not allowed: the role may not do this, or the CSRF token or Origin is wrong",
    404: "Ticket or user not found",
    409: "The ticket or account is not in a state that allows this",
    422: "Invalid input: a malformed request, or a value the server refuses",
    429: "Too many failed logins; wait the Retry-After seconds",
    502: "BioStar or the server's printer failed",
}


def _refusals(*statuses: int) -> dict[int | str, dict[str, Any]]:
    # A 422 is either a refused value or a malformed request, so it takes either body.
    return {
        status: {
            "model": (ErrorOut | FieldErrorsOut)
            if status == HTTPStatus.UNPROCESSABLE_ENTITY
            else ErrorOut,
            "description": _REFUSALS[status],
        }
        for status in statuses
    }


def _ticket(server: AppState, ticket: Ticket) -> TicketOut:
    return TicketOut.of(ticket, server.timezone)


@router.get(
    "/health",
    tags=["meta"],
    responses={
        HTTPStatus.SERVICE_UNAVAILABLE: {
            "model": HealthOut,
            "description": "The database does not answer, or the scheduler has stopped",
        }
    },
)
def health(server: Server, response: Response) -> HealthOut:
    """Readiness and version, without signing in; installs, upgrades and probes poll it."""
    ready = server.service.ping() and server.maintenance.running
    if not ready:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return HealthOut(status="ok" if ready else "unavailable", version=__version__)


@router.get("/config", tags=["meta"], responses=_refusals(401))
def config(_: Signed, server: Server) -> ConfigOut:
    return ConfigOut(timezone=server.timezone, server_printing=server.config.server_printing)


@router.post("/auth/login", tags=["auth"], responses=_refusals(401, 403, 422, 429))
def login(body: LoginIn, request: Request, response: Response, server: Server) -> SessionOut:
    """Sign in with a TiQR account; sets the session cookie and returns the CSRF token."""
    address = request.client.host if request.client else ""
    wait = server.throttle.retry_after(address, body.username)
    if wait is not None:
        raise ApiError(
            429,
            "rate_limited",
            "Too many failed logins; try again later",
            {"Retry-After": str(wait)},
        )
    try:
        user = server.service.authenticate(body.username, body.password)
    except AuthenticationError:
        server.throttle.failed(address, body.username)
        raise
    server.throttle.succeeded(address, body.username)
    # A login replaces the browser's previous session rather than leaving it open.
    previous = request.cookies.get(cookie_name(server.config))
    if previous:
        server.service.close_web_session(previous)
    token, session = server.service.open_web_session(user)
    set_session_cookie(response, server.config, token)
    return SessionOut.of(user, session, _IDLE_SECONDS)


@router.post("/auth/logout", tags=["auth"], status_code=204, responses=_refusals(401, 403))
def logout(me: Signed, response: Response, server: Server) -> None:
    server.service.close_web_session(me.token)
    clear_session_cookie(response, server.config)


@router.get("/auth/session", tags=["auth"], responses=_refusals(401))
def session(me: Signed) -> SessionOut:
    """The signed-in user and CSRF token; the web app calls it on load."""
    return SessionOut.of(me.user, me.session, _IDLE_SECONDS)


@router.get("/users", tags=["users"], responses=_refusals(401, 403))
def list_users(me: Signed, server: Server) -> list[UserOut]:
    return [UserOut.of(user) for user in server.service.list_accounts(me.user)]


@router.post("/users", tags=["users"], status_code=201, responses=_refusals(401, 403, 422))
def create_user(body: UserIn, me: Signed, server: Server) -> UserOut:
    """Admins create any role; managers create operators only."""
    return UserOut.of(server.service.create_user(me.user, body.username, body.password, body.role))


@router.patch("/users/{user_id}", tags=["users"], responses=_refusals(401, 403, 404, 409, 422))
def update_user(user_id: UUID, body: UserPatch, me: Signed, server: Server) -> UserOut:
    """Change a role, deactivate or reactivate, or reset a password.

    Admins do all of it; managers only deactivate and reactivate operators. Admins cannot change
    their own role or deactivate themselves, and the last active admin cannot be demoted.
    Deactivating or resetting a password ends that user's sessions.
    """
    user = server.service.manage_user(
        me.user, user_id, role=body.role, active=body.active, password=body.password
    )
    return UserOut.of(user)


@router.delete(
    "/users/{user_id}",
    tags=["users"],
    status_code=204,
    responses=_refusals(401, 403, 404, 409, 422),
)
def delete_user(user_id: UUID, me: Signed, server: Server) -> None:
    """Delete a deactivated account. Admins only; accounts with tickets stay, deactivated."""
    server.service.delete_user(me.user, user_id)


@router.get("/tickets", tags=["tickets"], responses=_refusals(401, 422))
def list_tickets(
    me: Signed, server: Server, state: Annotated[TicketState | None, Query()] = None
) -> list[TicketOut]:
    tickets = server.service.list_tickets(me.user, state=state)
    tickets.sort(key=lambda ticket: (ticket.readable_serial, str(ticket.id)))
    return [_ticket(server, ticket) for ticket in tickets]


@router.post("/tickets", tags=["tickets"], status_code=201, responses=_refusals(401, 403, 422, 502))
def create_ticket(body: TicketIn, me: Signed, server: Server) -> TicketOut:
    timezone = body.timezone or server.timezone
    ticket = server.service.create_ticket(
        me.user,
        visitor_name=body.visitor_name,
        visitor_type=body.visitor_type,
        valid_from=parse_input_datetime(body.valid_from, timezone),
        valid_until=parse_input_datetime(body.valid_until, timezone),
        usage_type=body.usage_type,
    )
    return _ticket(server, ticket)


@router.get("/tickets/{ticket_id}", tags=["tickets"], responses=_refusals(401, 403, 404, 422))
def get_ticket(ticket_id: UUID, me: Signed, server: Server) -> TicketOut:
    return _ticket(server, server.service.get_ticket(me.user, ticket_id))


@router.post(
    "/tickets/{ticket_id}/assign", tags=["tickets"], responses=_refusals(401, 403, 404, 409, 422)
)
def assign_ticket(ticket_id: UUID, body: AssignIn, me: Signed, server: Server) -> TicketOut:
    return _ticket(server, server.service.assign_ticket(me.user, ticket_id, body.assignee))


@router.post(
    "/tickets/{ticket_id}/pdf",
    tags=["tickets"],
    response_class=Response,
    responses=_refusals(401, 403, 404, 409, 422) | _PDF,
)
def ticket_pdf(ticket_id: UUID, me: Signed, server: Server) -> Response:
    """Render the badge and return it; a POST, since every render counts as a print.

    The PDF is also kept in TIQR_OUT, as `tiqr ticket save` does.
    """
    settings = server.runtime.settings
    path = server.service.print_ticket(
        me.user, ticket_id, output_dir=settings.output_dir, timezone=settings.default_tz
    )
    return Response(
        path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@router.post(
    "/tickets/{ticket_id}/print",
    tags=["tickets"],
    responses=_refusals(401, 403, 404, 409, 422, 502),
)
def ticket_print(ticket_id: UUID, me: Signed, server: Server) -> TicketOut:
    """Print on the server's default printer, when TIQR_SERVER_PRINTING is on.

    As with `tiqr ticket print`, a print the system refuses leaves the print count alone.
    """
    if not server.config.server_printing:
        raise ApiError(
            409, "server_printing_off", "Server printing is turned off; download the PDF instead"
        )
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    def render_and_print(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
        path = render_pdf(ticket, output_dir, timezone)
        server.runtime.printer(path)
        return path

    settings = server.runtime.settings
    server.service.print_ticket(
        me.user,
        ticket_id,
        output_dir=settings.output_dir,
        timezone=settings.default_tz,
        renderer=render_and_print,
    )
    return _ticket(server, server.service.get_ticket(me.user, ticket_id))


@router.post("/sync", tags=["operations"], responses=_refusals(401, 403, 502))
def sync(me: Signed, server: Server) -> CountOut:
    """Fetch and apply new access events now, besides the scheduled runs."""
    with server.maintenance.lock:
        return CountOut(count=server.service.sync(me.user))


@router.post("/cleanup", tags=["operations"], responses=_refusals(401, 403, 502))
def cleanup(me: Signed, server: Server) -> CountOut:
    """Remove finished tickets from BioStar now, besides the scheduled runs."""
    with server.maintenance.lock:
        return CountOut(count=server.service.cleanup(me.user))


@router.get("/stats", tags=["operations"], responses=_refusals(401, 403, 422))
def stats(
    me: Signed,
    server: Server,
    since: Annotated[date | None, Query(description="First day counted, inclusive")] = None,
    until: Annotated[date | None, Query(description="Last day counted, inclusive")] = None,
) -> StatsOut:
    """Ticket figures, for every ticket or those created within days of TIQR_DEFAULT_TZ."""
    return StatsOut.model_validate(
        server.service.stats(me.user, since=since, until=until, timezone=server.timezone)
    )
