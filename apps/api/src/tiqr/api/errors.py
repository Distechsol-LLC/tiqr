"""Core exceptions as HTTP responses: `{"detail": message, "code": slug}`, never a traceback."""

import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tiqr.core.auth import AuthenticationError
from tiqr.core.biostar import BioStarError
from tiqr.core.printer import PrinterError
from tiqr.core.service import NotFoundError, PermissionDeniedError, StateError

logger = logging.getLogger("tiqr.api")

type _Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


class ApiError(Exception):
    """A refusal decided by the HTTP layer itself, such as a missing CSRF token."""

    def __init__(
        self, status: int, code: str, detail: str, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = dict(headers or {})


def error_response(
    status: int, code: str, detail: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": code}, status_code=status, headers=headers)


def biostar_detail(exc: BioStarError) -> str:
    """The message, plus the BioStar code and HTTP status when present."""
    details = [f"BioStar code {exc.code}"] if exc.code is not None else []
    if exc.http_status is not None:
        details.append(f"HTTP {exc.http_status}")
    return f"{exc} ({', '.join(details)})" if details else str(exc)


# Starlette picks the handler for the nearest class in the exception's MRO, so StateError and
# AuthenticationError (ValueErrors) and PermissionDeniedError (an OSError) get their own.
_STATUSES: tuple[tuple[type[Exception], int, str], ...] = (
    (AuthenticationError, 401, "unauthenticated"),
    (PermissionDeniedError, 403, "forbidden"),
    (NotFoundError, 404, "not_found"),
    (StateError, 409, "conflict"),
    (ValueError, 422, "invalid"),
    # The server's printer; BioStar's errors are handled below, with their codes.
    (PrinterError, 502, "printer"),
)


def _domain_handler(status: int, code: str) -> _Handler:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return error_response(status, code, str(exc))

    return handler


def install_error_handlers(app: FastAPI) -> None:
    for exception, status, code in _STATUSES:
        app.add_exception_handler(exception, _domain_handler(status, code))

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.detail, exc.headers)

    @app.exception_handler(BioStarError)
    async def biostar_error(_: Request, exc: BioStarError) -> JSONResponse:
        logger.warning("BioStar request failed: %s", biostar_detail(exc))
        return error_response(502, "biostar", biostar_detail(exc))

    # Anything else, OSError and sqlite3.Error included. Starlette logs the traceback after this
    # answers, so storage paths and SQL stay in the server log and out of the response.
    @app.exception_handler(Exception)
    async def internal_error(_: Request, __: Exception) -> JSONResponse:
        return error_response(500, "internal", "Internal server error")
