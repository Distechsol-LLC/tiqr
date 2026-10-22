"""The JSON API: one endpoint per CLI command, all deciding through `TicketService`.

Handlers are plain functions, so FastAPI runs them on its thread pool: the core is synchronous,
and its repository and BioStar client serialize their own access.
"""

from dataclasses import dataclass
from datetime import date
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from tiqr.api import __version__
from tiqr.api.deps import AppState, Server, Signed
from tiqr.api.errors import ApiError
from tiqr.api.schemas import (
    AssignIn,
    BrandingOut,
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
    TicketPage,
    TicketTypeIn,
    TicketTypeOut,
    TicketTypePage,
    TicketTypePatch,
    UserIn,
    UserOut,
    UserPage,
    UserPatch,
    VisitorTypeIn,
    VisitorTypeOut,
    VisitorTypePage,
    VisitorTypePatch,
)
from tiqr.api.security import clear_session_cookie, cookie_name, set_session_cookie
from tiqr.core.auth import WEB_SESSION_IDLE, AuthenticationError
from tiqr.core.localtime import parse_input_datetime
from tiqr.core.models import Currency, Ticket, TicketState

router = APIRouter(
    prefix="/api",
    # Any handler can fail unexpectedly, and the error handler answers 500 for all of them.
    responses={500: {"model": ErrorOut, "description": "Unexpected server error"}},
)

_PDF: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/pdf": {}}, "description": "The badge, one A4 page"}
}
_DEFAULT_SIZE = 20
_MAX_SIZE = 100
_IDLE_SECONDS = int(WEB_SESSION_IDLE.total_seconds())
_REFUSALS: dict[int, str] = {
    401: "Not signed in, or sign-in was refused",
    403: "Not allowed: the role may not do this, or the CSRF token or Origin is wrong",
    404: "Ticket, user, ticket type or visitor type not found",
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


@dataclass(frozen=True)
class _Paging:
    page: Annotated[int, Query(ge=1, description="The page to return, from 1")] = 1
    size: Annotated[int, Query(ge=1, le=_MAX_SIZE, description="Most items on a page")] = (
        _DEFAULT_SIZE
    )

    def slice[T](self, items: list[T]) -> list[T]:
        start = (self.page - 1) * self.size
        return items[start : start + self.size]


Paging = Annotated[_Paging, Depends()]


def _ticket(server: AppState, ticket: Ticket) -> TicketOut:
    return TicketOut.of(ticket, server.timezone)


def _require_offered(server: AppState, currency: Currency) -> None:
    if currency not in server.runtime.settings.currencies:
        offered = ", ".join(server.runtime.settings.currencies)
        raise ApiError(422, "invalid", f"Currency {currency} is not offered; use {offered}")


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


@router.get("/branding", tags=["meta"])
def branding(server: Server) -> BrandingOut:
    """Name, theme, languages and currencies, without signing in: the login page needs them."""
    settings = server.runtime.settings
    return BrandingOut(
        app_name=settings.app_name,
        theme=settings.theme,
        languages=list(settings.languages),
        currencies=list(settings.currencies),
        has_logo=settings.logo_path is not None,
    )


@router.get(
    "/logo",
    tags=["meta"],
    response_class=FileResponse,
    responses={
        200: {"content": {"image/*": {}}, "description": "logo_path, as it is on disk"},
        404: {"model": ErrorOut, "description": "No logo is configured"},
    },
)
def logo(server: Server) -> FileResponse:
    """The configured logo; without one the app uses its built-in logo."""
    path = server.runtime.settings.logo_path
    if path is None:
        raise ApiError(404, "not_found", "No logo is configured")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


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


@router.get("/users", tags=["users"], responses=_refusals(401, 403, 422))
def list_users(me: Signed, server: Server, paging: Paging) -> UserPage:
    """One page of accounts, by username."""
    users = server.service.list_accounts(me.user)
    return UserPage(
        items=[UserOut.of(user) for user in paging.slice(users)],
        total=len(users),
        page=paging.page,
        size=paging.size,
    )


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


@router.get("/ticket-types", tags=["catalog"], responses=_refusals(401, 422))
def list_ticket_types(me: Signed, server: Server, paging: Paging) -> TicketTypePage:
    """One page of ticket types, by name. Every signed-in role may read them."""
    types = server.service.list_ticket_types(me.user)
    return TicketTypePage(
        items=[TicketTypeOut.of(item) for item in paging.slice(types)],
        total=len(types),
        page=paging.page,
        size=paging.size,
    )


@router.post("/ticket-types", tags=["catalog"], status_code=201, responses=_refusals(401, 403, 422))
def create_ticket_type(body: TicketTypeIn, me: Signed, server: Server) -> TicketTypeOut:
    """Add a ticket type, its price and the currency it is in. Admins and managers.

    The currency must be one of the languages' regions' (languages in tiqr_branding.jsonc).
    """
    _require_offered(server, body.currency)
    return TicketTypeOut.of(
        server.service.create_ticket_type(me.user, body.name, body.price_minor, body.currency)
    )


@router.patch("/ticket-types/{type_id}", tags=["catalog"], responses=_refusals(401, 403, 404, 422))
def update_ticket_type(
    type_id: UUID, body: TicketTypePatch, me: Signed, server: Server
) -> TicketTypeOut:
    """Rename a ticket type, or change its price or currency. Issued tickets keep theirs."""
    if body.currency is not None:
        current = next(
            (
                item.currency
                for item in server.service.list_ticket_types(me.user)
                if item.id == type_id
            ),
            None,
        )
        # A type may keep a currency that is no longer offered, but not move to one.
        if body.currency != current:
            _require_offered(server, body.currency)
    return TicketTypeOut.of(
        server.service.edit_ticket_type(
            me.user, type_id, name=body.name, price=body.price_minor, currency=body.currency
        )
    )


@router.delete(
    "/ticket-types/{type_id}",
    tags=["catalog"],
    status_code=204,
    responses=_refusals(401, 403, 404, 422),
)
def delete_ticket_type(type_id: UUID, me: Signed, server: Server) -> None:
    """Remove a ticket type. Tickets already issued keep their name and price."""
    server.service.delete_ticket_type(me.user, type_id)


@router.get("/visitor-types", tags=["catalog"], responses=_refusals(401, 422))
def list_visitor_types(me: Signed, server: Server, paging: Paging) -> VisitorTypePage:
    """One page of visitor types, by name. Every signed-in role may read them."""
    types = server.service.list_visitor_types(me.user)
    return VisitorTypePage(
        items=[VisitorTypeOut.of(item) for item in paging.slice(types)],
        total=len(types),
        page=paging.page,
        size=paging.size,
    )


@router.post(
    "/visitor-types", tags=["catalog"], status_code=201, responses=_refusals(401, 403, 422)
)
def create_visitor_type(body: VisitorTypeIn, me: Signed, server: Server) -> VisitorTypeOut:
    """Add a visitor type and the discount its tickets get. Admins and managers."""
    return VisitorTypeOut.of(
        server.service.create_visitor_type(me.user, body.name, body.discount_percent)
    )


@router.patch("/visitor-types/{type_id}", tags=["catalog"], responses=_refusals(401, 403, 404, 422))
def update_visitor_type(
    type_id: UUID, body: VisitorTypePatch, me: Signed, server: Server
) -> VisitorTypeOut:
    """Rename a visitor type or change its discount. Tickets already issued keep theirs."""
    return VisitorTypeOut.of(
        server.service.edit_visitor_type(
            me.user, type_id, name=body.name, discount_percent=body.discount_percent
        )
    )


@router.delete(
    "/visitor-types/{type_id}",
    tags=["catalog"],
    status_code=204,
    responses=_refusals(401, 403, 404, 422),
)
def delete_visitor_type(type_id: UUID, me: Signed, server: Server) -> None:
    """Remove a visitor type. Tickets already issued keep their name and discount."""
    server.service.delete_visitor_type(me.user, type_id)


@router.get("/tickets", tags=["tickets"], responses=_refusals(401, 422))
def list_tickets(
    me: Signed, server: Server, paging: Paging, state: Annotated[TicketState | None, Query()] = None
) -> TicketPage:
    """One page of tickets, newest first."""
    tickets = server.service.list_tickets(me.user, state=state)
    tickets.sort(key=lambda ticket: (ticket.readable_serial, str(ticket.id)), reverse=True)
    return TicketPage(
        items=[_ticket(server, ticket) for ticket in paging.slice(tickets)],
        total=len(tickets),
        page=paging.page,
        size=paging.size,
    )


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
        ticket_type=body.ticket_type,
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
    from tiqr.core.pdf import render_pdf  # noqa: PLC0415 - ReportLab is slow to import

    settings = server.runtime.settings
    path = server.service.print_ticket(
        me.user,
        ticket_id,
        output_dir=settings.output_dir,
        timezone=settings.default_tz,
        renderer=partial(render_pdf, title=settings.app_name),
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

    settings = server.runtime.settings

    def render_and_print(ticket: Ticket, output_dir: Path, timezone: str) -> Path:
        path = render_pdf(ticket, output_dir, timezone, title=settings.app_name)
        server.runtime.printer(path)
        return path

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
