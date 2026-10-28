"""The JSON API: one endpoint per CLI command, all deciding through `TicketService`.

Handlers are plain functions, so FastAPI runs them on its thread pool: the core is synchronous,
and its repository and BioStar client serialize their own access.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tiqr.api import __version__
from tiqr.api.deps import (
    READER,
    REVOKER,
    WRITER,
    AppState,
    Caller,
    IdempotencyKey,
    Server,
    Signed,
    require_license,
)
from tiqr.api.errors import ApiError, describe
from tiqr.api.schemas import (
    ActivateIn,
    AssignIn,
    AuditOut,
    BatchIn,
    BatchItemIn,
    BatchItemOut,
    BatchOut,
    BrandingOut,
    ConfigOut,
    CountOut,
    ErrorOut,
    FieldErrorsOut,
    HealthOut,
    LicenseRecordOut,
    LicenseStatusOut,
    LoginIn,
    ReissueIn,
    RequestCodeOut,
    RevokeIn,
    ServiceKeyCreated,
    ServiceKeyIn,
    ServiceKeyOut,
    ServiceKeyRotateIn,
    SessionOut,
    StatsOut,
    TicketIn,
    TicketOut,
    TicketPage,
    TicketPatch,
    TicketTypeIn,
    TicketTypeOut,
    TicketTypePage,
    TicketTypePatch,
    TransferIn,
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
from tiqr.core.service import IdempotencyConflictError

logger = logging.getLogger("tiqr.api")

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_license)],
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
    400: "The license key is not valid, is for another machine, or has expired",
    401: "Not signed in, or sign-in was refused",
    403: "Not allowed: no valid license, the role or key scope may not do this, or bad CSRF",
    404: "Ticket, user, ticket type or visitor type not found",
    409: "Not in a state that allows this, or an external code or Idempotency-Key clashes",
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


@router.get("/license/status", tags=["license"], responses=_refusals(401))
def license_status(_: Signed, server: Server) -> LicenseStatusOut:
    """The license, verified now; the web app shows its wall unless `is_valid` is true."""
    return LicenseStatusOut.of(server.service.license_status())


@router.get("/license/request-code", tags=["license"], responses=_refusals(401, 422))
def license_request_code(me: Signed, server: Server) -> RequestCodeOut:
    """A code to send the vendor, for any signed-in role."""
    return RequestCodeOut(code=server.service.license_request_code(me.user))


@router.post("/license/activate", tags=["license"], responses=_refusals(400, 401, 403, 409, 422))
def activate_license(body: ActivateIn, me: Signed, server: Server) -> LicenseStatusOut:
    """Store a vendor key (admin). A refused key leaves the current license in place."""
    return LicenseStatusOut.of(server.service.activate_license(me.user, body.license_key))


@router.post(
    "/license/deactivate", tags=["license"], status_code=204, responses=_refusals(401, 403)
)
def deactivate_license(me: Signed, server: Server) -> None:
    """Retire the active key (admin), for swapping licenses by hand. Resets nothing else."""
    server.service.deactivate_license(me.user)


@router.get("/license/history", tags=["license"], responses=_refusals(401, 403))
def license_history(me: Signed, server: Server) -> list[LicenseRecordOut]:
    """Every stored key, newest first (admin), with most of each key hidden."""
    return [LicenseRecordOut.of(record) for record in server.service.license_history(me.user)]


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

    The currency must be one of the languages' regions' (languages in tiqr_brand.jsonc).
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


@router.get("/tickets", tags=["tickets"], responses=_refusals(401, 403, 422))
def list_tickets(
    me: READER,
    server: Server,
    paging: Paging,
    state: Annotated[TicketState | None, Query()] = None,
    # Same bound as a visitor name in apps/api/src/tiqr/api/schemas.py
    search: Annotated[str | None, Query(max_length=200)] = None,
    external_code: Annotated[
        str | None, Query(max_length=128, description="Only the ticket with exactly this code")
    ] = None,
) -> TicketPage:
    """One page of tickets, newest first, matching the search on serial, visitor or type."""
    tickets = server.service.list_tickets(
        me.user, state=state, search=search, external_code=external_code
    )
    tickets.sort(key=lambda ticket: (ticket.readable_serial, str(ticket.id)), reverse=True)
    return TicketPage(
        items=[_ticket(server, ticket) for ticket in paging.slice(tickets)],
        total=len(tickets),
        page=paging.page,
        size=paging.size,
    )


@dataclass(frozen=True)
class _Done:
    status: int
    body: str
    replayed: bool = False
    commit: Callable[[], None] | None = None


def _keyed(
    server: AppState,
    caller: Caller,
    kind: str,
    payload: dict[str, Any],
    key: str | None,
    produce: Callable[[], tuple[int, BaseModel]],
) -> _Done:
    """Run `produce`, or replay its saved answer for the same key and payload.

    The caller holds `idempotency_lock`. The answer is saved by `commit`, which the caller runs
    when it is final, so a batch that is undone leaves no key behind. Only answers that succeeded
    are kept, so a refused request can be retried under the same key.
    """
    if key is None:
        status, model = produce()
        return _Done(status, model.model_dump_json())
    # Keys are per account, so one caller can never read another's saved answer.
    scoped = f"{caller.user.id}:{key}"
    digest = hashlib.sha256(
        json.dumps([kind, payload], sort_keys=True, default=str).encode()
    ).hexdigest()
    stored = server.service.idempotency_lookup(scoped, digest)
    if stored is not None:
        return _Done(stored.status, stored.body, replayed=True)
    status, model = produce()
    body = model.model_dump_json()
    ttl = timedelta(hours=server.config.idempotency_ttl_hours)
    return _Done(
        status,
        body,
        commit=partial(server.service.idempotency_store, scoped, digest, status, body, ttl),
    )


def _json(done: _Done) -> Response:
    headers = {"Idempotent-Replayed": "true"} if done.replayed else {}
    return Response(done.body, done.status, headers, media_type="application/json")


def _when(value: str | None, timezone: str) -> datetime | None:
    return None if value is None else parse_input_datetime(value, timezone)


def _create(server: AppState, me: Caller, body: TicketIn) -> tuple[int, TicketOut]:
    timezone = body.timezone or server.timezone
    ticket = server.service.create_ticket(
        me.user,
        visitor_name=body.visitor_name,
        visitor_type=body.visitor_type,
        valid_from=parse_input_datetime(body.valid_from, timezone),
        valid_until=parse_input_datetime(body.valid_until, timezone),
        usage_type=body.usage_type,
        ticket_type=body.ticket_type,
        external_code=body.external_code,
        event_session=body.event_session,
    )
    return 201, _ticket(server, ticket)


_IDEMPOTENT: dict[int | str, dict[str, Any]] = {
    200: {"description": "A replay: the answer the same Idempotency-Key got first"}
}


@router.post(
    "/tickets", tags=["tickets"], status_code=201, responses=_refusals(401, 403, 409, 422, 502)
)
def create_ticket(
    body: TicketIn, me: WRITER, server: Server, idempotency_key: IdempotencyKey = None
) -> TicketOut:
    """Issue a ticket. With an `Idempotency-Key`, a retry of the same body gets the first answer
    back (same status and body, plus `Idempotent-Replayed: true`); the same key with another body
    is a 409. Keys are remembered for TIQR_IDEMPOTENCY_TTL_HOURS.
    """
    if idempotency_key is None:
        with server.service.attributed(me.label):
            return _create(server, me, body)[1]
    with server.service.idempotency_lock, server.service.attributed(me.label):
        done = _keyed(
            server,
            me,
            "create",
            body.model_dump(),
            idempotency_key,
            partial(_create, server, me, body),
        )
        if done.commit:
            done.commit()
    return _json(done)  # type: ignore[return-value]  # a Response passes through as it is


def _batch_item(server: AppState, me: Caller, item: BatchItemIn, key: str | None) -> _Done:
    payload = item.model_dump(exclude={"idempotency_key"})
    return _keyed(server, me, "create", payload, key, partial(_create, server, me, item))


@router.post("/tickets/batch", tags=["tickets"], responses=_refusals(401, 403, 422))
def create_tickets_batch(  # noqa: C901, PLR0912 - one pass over the items, with two modes
    body: BatchIn, me: WRITER, server: Server, idempotency_key: IdempotencyKey = None
) -> BatchOut:
    """Create many tickets, with a result for each; always 200 unless the request is malformed.

    With `atomic` false every item stands on its own. With `atomic` true the first failure
    revokes the items already created (those results read `rolled_back`) and the rest are
    `skipped`. Items follow the create rules: an item's `idempotency_key`, or the header's
    plus `:index`, replays its first answer. At most TIQR_BATCH_MAX_SIZE items.
    """
    limit = server.config.batch_max_size
    if len(body.items) > limit:
        raise ApiError(422, "batch_too_large", f"A batch carries at most {limit} tickets")
    results: list[BatchItemOut] = []
    created: list[int] = []
    pending: list[Callable[[], None]] = []
    seen: set[str] = set()
    failed = False
    with server.service.idempotency_lock, server.service.attributed(me.label):
        for index, item in enumerate(body.items):
            if failed:
                results.append(BatchItemOut(index=index, status="skipped"))
                continue
            key = item.idempotency_key or (
                f"{idempotency_key}:{index}" if idempotency_key else None
            )
            try:
                if key is not None and key in seen:
                    raise IdempotencyConflictError("Idempotency key repeated within the batch")  # noqa: TRY301
                done = _batch_item(server, me, item, key)
            except Exception as exc:
                status, code, detail = describe(exc)
                if status >= HTTPStatus.INTERNAL_SERVER_ERROR and code == "internal":
                    logger.exception("Batch item %s failed", index)
                results.append(BatchItemOut(index=index, status="error", code=code, error=detail))
                failed = body.atomic
                continue
            if key is not None:
                seen.add(key)
            out = TicketOut.model_validate_json(done.body)
            if done.commit and not done.replayed:
                if body.atomic:
                    pending.append(done.commit)
                else:
                    done.commit()
            if not done.replayed:
                created.append(index)
            results.append(
                BatchItemOut(
                    index=index,
                    status="replayed" if done.replayed else "created",
                    ticket_id=out.id,
                    ticket=out,
                )
            )
        if body.atomic and failed:
            _undo_batch(server, me, results, created)
        else:
            for commit in pending:
                commit()
    errors = sum(result.status == "error" for result in results)
    undone = body.atomic and failed
    return BatchOut(
        atomic=body.atomic,
        committed=not undone,
        created=0 if undone else sum(result.status == "created" for result in results),
        failed=errors,
        results=results,
    )


def _undo_batch(
    server: AppState, me: Caller, results: list[BatchItemOut], created: list[int]
) -> None:
    for index in created:
        result = results[index]
        try:
            assert result.ticket_id is not None  # noqa: S101 - set for every created item
            server.service.revoke_ticket(me.user, result.ticket_id, "Batch undone: an item failed")
        except Exception as exc:  # noqa: BLE001 - reported on the item, the rest still undo
            _, code, detail = describe(exc)
            results[index] = result.model_copy(
                update={"status": "error", "code": code, "error": f"Rollback failed: {detail}"}
            )
        else:
            results[index] = result.model_copy(update={"status": "rolled_back"})


@router.get("/tickets/{ticket_id}", tags=["tickets"], responses=_refusals(401, 403, 404, 422))
def get_ticket(ticket_id: UUID, me: READER, server: Server) -> TicketOut:
    return _ticket(server, server.service.get_ticket(me.user, ticket_id))


@router.patch(
    "/tickets/{ticket_id}", tags=["tickets"], responses=_refusals(401, 403, 404, 409, 422, 502)
)
def patch_ticket(ticket_id: UUID, body: TicketPatch, me: WRITER, server: Server) -> TicketOut:
    """Change the validity window, in BioStar too. Admins and managers.

    Allowed while the ticket is issued, or passed and multi-use; the end must be after the
    start. A window that is already as asked changes nothing.
    """
    timezone = body.timezone or server.timezone
    with server.service.attributed(me.label):
        ticket = server.service.update_validity(
            me.user,
            ticket_id,
            valid_from=_when(body.valid_from, timezone),
            valid_until=_when(body.valid_until, timezone),
        )
    return _ticket(server, ticket)


@router.post(
    "/tickets/{ticket_id}/revoke",
    tags=["tickets"],
    responses=_refusals(401, 403, 404, 409, 422, 502),
)
def revoke_ticket(
    ticket_id: UUID, me: REVOKER, server: Server, body: RevokeIn | None = None
) -> TicketOut:
    """Cancel a ticket and remove its access in BioStar. Admins and managers.

    Revoking a revoked ticket returns it unchanged. An expired ticket is a 409. If BioStar
    refuses, the ticket stays as it was (a 502), and the attempt is audited.
    """
    with server.service.attributed(me.label):
        ticket = server.service.revoke_ticket(me.user, ticket_id, body.reason if body else None)
    return _ticket(server, ticket)


@router.post(
    "/tickets/{ticket_id}/transfer",
    tags=["tickets"],
    responses=_refusals(401, 403, 404, 409, 422, 502),
)
def transfer_ticket(ticket_id: UUID, body: TransferIn, me: WRITER, server: Server) -> TicketOut:
    """Move a ticket to another session or event, keeping its state, id and audit history."""
    timezone = body.timezone or server.timezone
    with server.service.attributed(me.label):
        ticket = server.service.transfer_ticket(
            me.user,
            ticket_id,
            body.event_session,
            valid_from=_when(body.valid_from, timezone),
            valid_until=_when(body.valid_until, timezone),
        )
    return _ticket(server, ticket)


@router.post(
    "/tickets/{ticket_id}/reissue",
    tags=["tickets"],
    responses=_refusals(401, 403, 404, 409, 422, 502),
)
def reissue_ticket(
    ticket_id: UUID,
    body: ReissueIn,
    me: WRITER,
    server: Server,
    idempotency_key: IdempotencyKey = None,
) -> TicketOut:
    """Reissue a ticket in any state, as the same ticket; this is also how it is edited.

    The ticket returns to issued. The window may be moved; it must end in the future. Send an
    `Idempotency-Key` so a retry is answered from the first attempt.
    """
    timezone = body.timezone or server.timezone

    def produce() -> tuple[int, BaseModel]:
        ticket = server.service.reissue_ticket(
            me.user,
            ticket_id,
            valid_from=_when(body.valid_from, timezone),
            valid_until=_when(body.valid_until, timezone),
        )
        return 200, _ticket(server, ticket)

    with server.service.idempotency_lock, server.service.attributed(me.label):
        done = _keyed(
            server, me, f"reissue:{ticket_id}", body.model_dump(), idempotency_key, produce
        )
        if done.commit:
            done.commit()
    return _json(done)  # type: ignore[return-value]  # a Response passes through as it is


@router.get("/tickets/{ticket_id}/audit", tags=["tickets"], responses=_refusals(401, 403, 404, 422))
def ticket_audit(ticket_id: UUID, me: READER, server: Server) -> list[AuditOut]:
    """Every recorded change to a ticket, oldest first. Admins and managers."""
    server.service.get_ticket(me.user, ticket_id)
    return [
        AuditOut.model_validate(entry, from_attributes=True)
        for entry in server.service.audit_trail(me.user, ticket_id)
    ]


@router.post(
    "/service-keys", tags=["service-keys"], status_code=201, responses=_refusals(401, 403, 404, 422)
)
def create_service_key(body: ServiceKeyIn, me: Signed, server: Server) -> ServiceKeyCreated:
    """Issue an API key for service-to-service calls (admin, signed in). Shown once."""
    key, secret = server.service.create_api_key(
        me.user, body.name, body.scopes, acts_as=body.acts_as, expires_at=body.expires_at
    )
    return ServiceKeyCreated(**ServiceKeyOut.of(key).model_dump(), secret=secret)


@router.get("/service-keys", tags=["service-keys"], responses=_refusals(401, 403))
def list_service_keys(me: Signed, server: Server) -> list[ServiceKeyOut]:
    """Every key, without secrets (admin)."""
    return [ServiceKeyOut.of(key) for key in server.service.list_api_keys(me.user)]


@router.post(
    "/service-keys/{key_id}/rotate",
    tags=["service-keys"],
    status_code=201,
    responses=_refusals(401, 403, 404, 409, 422),
)
def rotate_service_key(
    key_id: UUID, body: ServiceKeyRotateIn, me: Signed, server: Server
) -> ServiceKeyCreated:
    """Issue a successor with the same scopes; the old key works on for the grace period."""
    key, secret = server.service.rotate_api_key(
        me.user, key_id, timedelta(minutes=body.grace_minutes)
    )
    return ServiceKeyCreated(**ServiceKeyOut.of(key).model_dump(), secret=secret)


@router.delete(
    "/service-keys/{key_id}", tags=["service-keys"], responses=_refusals(401, 403, 404, 422)
)
def revoke_service_key(key_id: UUID, me: Signed, server: Server) -> ServiceKeyOut:
    """End a key at once; revoking a revoked key returns it unchanged."""
    return ServiceKeyOut.of(server.service.revoke_api_key(me.user, key_id))


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

    The PDF is also kept in the out folder, as `tiqr ticket save` does.
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
