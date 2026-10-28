"""Build the ASGI application. The service opens with the server and closes when it stops."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from tiqr.api import __version__
from tiqr.api.config import ServerConfig
from tiqr.api.deps import AppState
from tiqr.api.endpoints import router
from tiqr.api.errors import install_error_handlers
from tiqr.api.maintenance import Maintenance
from tiqr.api.runtime import Runtime, open_runtime
from tiqr.api.security import DOCS_PREFIX, LoginThrottle, install_guard
from tiqr.api.web import WEB_ROOT, install_web
from tiqr.core.service import TicketService


def create_app(
    config: ServerConfig,
    *,
    runtime: Callable[[], AbstractContextManager[Runtime]] = open_runtime,
    web_root: Path = WEB_ROOT,
    scheduler: Callable[[TicketService], Maintenance] = Maintenance,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        with runtime() as opened:
            maintenance = scheduler(opened.service)
            app.state.tiqr = AppState(config, opened, LoginThrottle(), maintenance)
            maintenance.start()
            try:
                yield
            finally:
                # Waits for a run in progress, off the event loop, before the database closes.
                await run_in_threadpool(maintenance.stop)

    # The interactive docs are for development; production exposes no schema.
    app = FastAPI(
        title="TiQR",
        version=__version__,
        lifespan=lifespan,
        docs_url=DOCS_PREFIX if config.dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.dev else None,
        # Operation IDs become the generated web client's method names, so keep them short.
        generate_unique_id_function=lambda route: route.name,
    )
    install_error_handlers(app)
    install_guard(app, config)
    app.include_router(router)
    # Last, so its catch-all path matches only what no API route does.
    install_web(app, web_root)
    return app
