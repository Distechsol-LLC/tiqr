import json
import logging
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from tiqr.api import openapi
from tiqr.api.config import ServerConfig
from tiqr.api.maintenance import Maintenance
from tiqr.api.security import LoginThrottle
from tiqr.core.models import RawEvent, UsageType

PROJECT = Path(__file__).resolve().parents[2]
TLS = {"TIQR_TLS_CERT": "tls/cert.pem", "TIQR_TLS_KEY": "tls/key.pem"}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_config_reads_the_environment_and_resolves_tls_paths(project_root):
    config = ServerConfig.from_env(
        TLS
        | {
            "TIQR_HOST": "10.0.0.5",
            "TIQR_PORT": "443",
            "TIQR_SERVER_PRINTING": "true",
            "TIQR_SYNC_INTERVAL": "30",
            "TIQR_CLEANUP_INTERVAL": "0",
        }
    )
    assert (config.host, config.port) == ("10.0.0.5", 443)
    assert config.tls_cert == project_root / "tls" / "cert.pem"
    assert config.tls_key == project_root / "tls" / "key.pem"
    assert config.server_printing
    assert (config.sync_interval, config.cleanup_interval) == (30, 0)


def test_blank_variables_use_defaults_and_arguments_win():
    blank = dict.fromkeys(("TIQR_HOST", "TIQR_PORT", "TIQR_SYNC_INTERVAL"), " ")
    config = ServerConfig.from_env(blank, dev=True)
    assert (config.host, config.port, config.sync_interval) == ("127.0.0.1", 7102, 60)
    assert not config.server_printing
    assert not ServerConfig.from_env({}).secure
    config = ServerConfig.from_env(
        {"TIQR_HOST": "10.0.0.5"}, host="::1", port=9000, tls_cert=Path("c"), tls_key=Path("k")
    )
    assert (config.host, config.port, config.tls_cert) == ("::1", 9000, Path("c"))


@pytest.mark.parametrize(
    ("environment", "options", "message"),
    [
        ({"TIQR_TLS_CERT": "cert.pem"}, {}, "both"),
        ({"TIQR_HOST": "0.0.0.0"}, {"dev": True}, "loopback"),
        (TLS | {"TIQR_PORT": "70000"}, {}, "between 1 and 65535"),
        (TLS | {"TIQR_PORT": "https"}, {}, "whole number"),
        (TLS | {"TIQR_SERVER_PRINTING": "yes"}, {}, "true or false"),
        (TLS | {"TIQR_SYNC_INTERVAL": "-1"}, {}, "must not be negative"),
    ],
)
def test_config_refuses_unsafe_or_malformed_settings(environment, options, message):
    with pytest.raises(ValueError, match=message):
        ServerConfig.from_env(environment, **options)


def test_dev_accepts_loopback_names():
    for host in ("localhost", "127.0.0.1", "::1"):
        assert ServerConfig(host=host, dev=True).dev


def test_throttle_window_and_limits():
    clock = Clock()
    throttle = LoginThrottle(pair_limit=2, address_limit=3, window=60, clock=clock)
    throttle.failed("10.0.0.1", "admin")
    assert throttle.retry_after("10.0.0.1", "admin") is None
    clock.now += 10
    throttle.failed("10.0.0.1", " ADMIN ")
    # Usernames match the way people mistype them; the first failure ages out first.
    assert throttle.retry_after("10.0.0.1", "admin") == 50
    assert throttle.retry_after("10.0.0.2", "admin") is None
    throttle.failed("10.0.0.1", "manager")
    assert throttle.retry_after("10.0.0.1", "operator") == 50
    clock.now += 49
    assert throttle.retry_after("10.0.0.1", "admin") == 1
    clock.now += 1
    assert throttle.retry_after("10.0.0.1", "admin") is None
    assert throttle.retry_after("10.0.0.1", "operator") is None


def test_throttle_success_clears_only_that_pair():
    throttle = LoginThrottle(pair_limit=1, address_limit=3, clock=Clock())
    throttle.failed("10.0.0.1", "admin")
    throttle.failed("10.0.0.1", "manager")
    throttle.succeeded("10.0.0.1", "admin")
    assert throttle.retry_after("10.0.0.1", "admin") is None
    assert throttle.retry_after("10.0.0.1", "manager") is not None


def test_throttle_memory_is_bounded():
    clock = Clock()
    throttle = LoginThrottle(window=1, clock=clock)
    for address in range(5000):
        throttle.failed(f"10.0.{address}", "admin")
        clock.now += 0.001
    assert len(throttle._failures) <= 4098


class Service:
    def __init__(self):
        self.calls = []
        self.failing = set()

    def _run(self, name):
        self.calls.append(name)
        if name in self.failing:
            raise RuntimeError(f"{name} unavailable")
        return 2

    def scheduled_sync(self):
        return self._run("sync")

    def scheduled_cleanup(self):
        return self._run("cleanup")


def test_maintenance_runs_each_job_on_its_own_interval(caplog):
    clock, service = Clock(), Service()
    maintenance = Maintenance(service, 60, 3600, clock=clock)
    with caplog.at_level(logging.INFO, "tiqr.api"):
        assert maintenance.run_due() == 60
    assert service.calls == ["sync", "cleanup"]
    assert "Scheduled sync processed 2" in caplog.text
    clock.now += 59
    assert maintenance.run_due() == 1
    clock.now += 1
    maintenance.run_due()
    assert service.calls == ["sync", "cleanup", "sync"]


def test_maintenance_failures_are_logged_and_retried(caplog):
    clock, service = Clock(), Service()
    service.failing.add("sync")
    maintenance = Maintenance(service, 60, 0, clock=clock)
    with caplog.at_level(logging.ERROR, "tiqr.api"):
        assert maintenance.run_due() == 60
    assert "Scheduled sync failed" in caplog.text
    assert "sync unavailable" in caplog.text
    service.failing.clear()
    clock.now += 60
    maintenance.run_due()
    assert service.calls == ["sync", "sync"]


def test_maintenance_with_no_jobs_starts_no_thread():
    maintenance = Maintenance(Service(), 0, 0)
    assert maintenance.run_due() is None
    maintenance.start()
    assert maintenance._thread is None
    maintenance.stop()


def test_maintenance_thread_stops_after_the_run_in_progress():
    started, release = threading.Event(), threading.Event()

    class Slow(Service):
        def scheduled_sync(self):
            started.set()
            release.wait(5)
            return super().scheduled_sync()

    service = Slow()
    maintenance = Maintenance(service, 3600, 0)
    maintenance.start()
    assert started.wait(5)
    stopper = threading.Thread(target=maintenance.stop)
    stopper.start()
    # stop() waits for the sync instead of closing the database underneath it.
    stopper.join(0.2)
    assert stopper.is_alive()
    release.set()
    stopper.join(5)
    assert not stopper.is_alive()
    assert service.calls == ["sync"]


def test_the_server_schedules_sync_from_startup(make_client, service, accounts, clock):
    ticket = service.create_ticket(
        accounts["operator"],
        visitor_name="Name",
        visitor_type="Guest",
        valid_from=clock.now,
        valid_until=clock.now + timedelta(hours=1),
        usage_type=UsageType.MULTI_USE,
    )
    service.event_source.events.append(RawEvent("scan-1", ticket.external_id, clock.now, True))
    with make_client(sync_interval=3600):
        # Shutdown waits for the startup run, so it has finished once the client closes.
        pass
    assert service.repository.get_ticket(ticket.id).use_count == 1


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    (root / "_app" / "immutable").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>TiQR</title>", encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (root / "_app" / "immutable" / "start.abc123.js").write_text("export {}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the build", encoding="utf-8")
    return root


def test_web_build_is_served_with_an_spa_fallback(make_client, web_root):
    with make_client(web_root=web_root) as client:
        for path in ("/", "/tickets/123", "/users"):
            response = client.get(path)
            assert response.status_code == 200
            assert "<title>TiQR</title>" in response.text
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-frame-options"] == "DENY"
        robots = client.get("/robots.txt")
        assert robots.text.startswith("User-agent")
        assert robots.headers["cache-control"] == "no-cache"
        asset = client.get("/_app/immutable/start.abc123.js")
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        # API paths never fall back to the page, and still get the API's headers.
        missing = client.get("/api/unknown")
        assert missing.status_code == 404
        assert missing.json()["code"] == "not_found"
        assert missing.headers["cache-control"] == "no-store"
        assert client.get("/api/health").json()["status"] == "ok"


@pytest.mark.parametrize(
    "path", ["/..%2fsecret.txt", "/%2e%2e/secret.txt", "/_app/..%2f..%2fsecret.txt"]
)
def test_web_paths_cannot_leave_the_build(make_client, web_root, path):
    with make_client(web_root=web_root) as client:
        response = client.get(path)
    assert "outside the build" not in response.text


def test_without_a_web_build_only_the_api_is_served(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_committed_openapi_schema_is_current():
    # The version changes every release; everything else must match exactly.
    committed = json.loads((PROJECT / "apps" / "web" / "openapi.json").read_text(encoding="utf-8"))
    current = json.loads(openapi.render())
    committed["info"].pop("version")
    current["info"].pop("version")
    assert committed == current, "Run: uv run poe openapi"


def test_openapi_export_writes_the_schema(tmp_path):
    output = tmp_path / "openapi.json"
    openapi.main([str(output)])
    schema = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/tickets/{ticket_id}/pdf" in schema["paths"]
    with pytest.raises(SystemExit, match="usage"):
        openapi.main([])
