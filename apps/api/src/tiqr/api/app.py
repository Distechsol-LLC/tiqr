"""Build the ASGI application. The service opens with the server and closes when it stops."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from tiqr.api import __version__
from tiqr.api.config import ServerConfig
from tiqr.api.deps import AppState
from tiqr.api.endpoints import passage_record, router
from tiqr.api.errors import install_error_handlers
from tiqr.api.integration import router as biostar_router
from tiqr.api.live import LiveEvents
from tiqr.api.maintenance import Maintenance
from tiqr.api.runtime import Runtime, open_runtime
from tiqr.api.security import DOCS_PREFIX, LoginThrottle, install_guard, install_request_id
from tiqr.api.web import WEB_ROOT, install_web
from tiqr.api.webhook import PassWebhook
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
            webhook = None
            if config.pass_webhook_url and config.pass_webhook_secret:
                webhook = PassWebhook(config.pass_webhook_url, config.pass_webhook_secret)
                webhook.start()
                opened.service.on_passage = lambda event: webhook.publish(
                    passage_record(opened.service, event)
                )
            maintenance = scheduler(opened.service)
            app.state.tiqr = AppState(config, opened, LoginThrottle(), maintenance)
            maintenance.start()
            live = LiveEvents(opened.service, maintenance.sync_soon)
            live.start()
            try:
                yield
            finally:
                await run_in_threadpool(live.stop)
                # Waits for a run in progress, off the event loop, before the database closes.
                await run_in_threadpool(maintenance.stop)
                if webhook is not None:
                    await run_in_threadpool(webhook.stop)

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
    install_request_id(app)
    app.include_router(router)
    app.include_router(biostar_router)
    # Last, so its catch-all path matches only what no API route does.
    install_web(app, web_root)
    return app
