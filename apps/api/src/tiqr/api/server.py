"""Run the app under Uvicorn: one process, TLS terminated in-process, no reverse proxy."""

import copy
from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from tiqr.api.app import create_app
from tiqr.api.config import ServerConfig


def _log_config() -> dict[str, Any]:
    # Uvicorn's own format, extended to the scheduler's and error handlers' tiqr.api logger.
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"]["tiqr"] = {"handlers": ["default"], "level": "INFO", "propagate": False}
    return config


def run(config: ServerConfig) -> None:
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        ssl_certfile=config.tls_cert,
        ssl_keyfile=config.tls_key,
        # Clients connect directly, so forwarded headers would only let them spoof addresses.
        proxy_headers=False,
        server_header=False,
        log_config=_log_config(),
    )
