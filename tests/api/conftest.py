from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tiqr.api.app import create_app
from tiqr.api.config import ServerConfig
from tiqr.api.runtime import Runtime
from tiqr.core.settings import Settings

# Plain HTTP, as installs default to, with the scheduler off so tests drive sync themselves.
PLAIN = ServerConfig(sync_interval=0, cleanup_interval=0, server_printing=False)
# The paths are never opened: TLS is the server's job, and TestClient talks ASGI directly.
TLS = {"tls_cert": Path("cert.pem"), "tls_key": Path("key.pem")}


@pytest.fixture
def service(service, accounts, issue):
    # The API refuses everything without a license, so its tests start with a paid one.
    service.activate_license(accounts["admin"], issue())
    return service


@pytest.fixture
def printed():
    return []


@pytest.fixture
def make_client(service, tmp_path, printed):
    settings = Settings(
        secret_key="api-suite-unique-signing-key",
        database_path=tmp_path / "unused.db",
        output_dir=tmp_path / "out",
        default_tz="Asia/Baku",
    )
    runtime = Runtime(settings, service, printer=printed.append)

    def make(*, web_root=tmp_path / "no-web", raise_server_exceptions=True, tls=False, **config):
        # Keyword arguments override the plain config's fields; tls adds a certificate.
        config = replace(PLAIN, **(TLS if tls else {}), **config)
        app = create_app(config, runtime=lambda: nullcontext(runtime), web_root=web_root)
        base = "https://testserver" if config.secure else "http://testserver"
        return TestClient(app, base_url=base, raise_server_exceptions=raise_server_exceptions)

    return make


@pytest.fixture
def client(make_client):
    with make_client() as client:
        yield client
