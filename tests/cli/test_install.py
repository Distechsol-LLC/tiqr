import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tiqr.cli import commands, installer
from tiqr.cli.commands import app
from tiqr.core import settings
from tiqr.core.license import parse_request_code
from tiqr.core.settings import BRANDING_FILE

BRANDING = (
    '{"app_name": "TiQR", "logo_path": null, "theme": "default",'
    ' "languages": ["en-US", "ru-RU", "az-AZ"]}'
)
# The install steps that touch the host are switched off unless a test turns them on.
QUIET = ["--no-service", "--no-firewall"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Every test writes into its own home, never the checkout's real .env.local or database.
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "Asia/Baku")
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path / "home")
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(commands, "_interactive", lambda: False)
    return tmp_path / "home"


@pytest.fixture
def release(tmp_path):
    origin = tmp_path / "release"
    origin.mkdir()
    (origin / BRANDING_FILE).write_text(BRANDING.replace("TiQR", "Clinic"))
    return origin


def test_install_copies_branding_into_tiqr_home(home, release):
    result = CliRunner().invoke(app, ["install", "--source", str(release), *QUIET])

    assert result.exit_code == 0, result.output
    assert (home / BRANDING_FILE).read_text() == (release / BRANDING_FILE).read_text()
    assert "Copied" in result.output


def test_install_ends_with_the_license_request_code(home, release):
    result = CliRunner().invoke(
        app, ["install", "--source", str(release), "--host", "10.0.0.5", "--port", "7200", *QUIET]
    )

    assert result.exit_code == 0, result.output
    assert "activate a license" in result.output
    assert "tiqr license activate" in result.output
    code = next(line.strip() for line in result.output.splitlines() if line.startswith("  ey"))
    assert parse_request_code(code).request_type == "trial"


def test_install_rejects_a_broken_file_and_keeps_the_existing_one(home, tmp_path):
    origin = tmp_path / "broken"
    origin.mkdir()
    (origin / BRANDING_FILE).write_text('{"app_name": "TiQR"}')
    (home / BRANDING_FILE).write_text(BRANDING)

    result = CliRunner().invoke(app, ["install", "--source", str(origin), *QUIET])

    assert result.exit_code == 1
    assert "missing" in result.output
    assert (home / BRANDING_FILE).read_text() == BRANDING


def test_install_reports_a_file_already_in_place(home):
    (home / BRANDING_FILE).write_text(BRANDING)

    result = CliRunner().invoke(app, ["install", "--source", str(home), *QUIET])

    assert result.exit_code == 0, result.output
    assert "already in place" in result.output


def test_install_writes_address_and_initializes_the_database(home, release):
    result = CliRunner().invoke(
        app, ["install", "--source", str(release), "--host", "10.0.0.5", "--port", "7200", *QUIET]
    )

    assert result.exit_code == 0, result.output
    local = (home / settings.LOCAL_ENV_FILE).read_text()
    assert "TIQR_HOST=10.0.0.5" in local
    assert "TIQR_PORT=7200" in local
    assert "TIQR_SECRET_KEY=" in local
    assert (home / "tiqr.db").exists()
    assert "No users yet" in result.output


def test_install_asks_for_the_first_admin_at_a_terminal(home, release, monkeypatch):
    prompted = []
    monkeypatch.setattr(commands, "_interactive", lambda: True)
    monkeypatch.setattr(commands, "create_first_admin", lambda: prompted.append(True))

    result = CliRunner().invoke(
        app, ["install", "--source", str(release), "--host", "10.0.0.5", "--port", "7200", *QUIET]
    )

    assert result.exit_code == 0, result.output
    assert prompted == [True]


def test_service_needs_the_packaged_executable(home, release, monkeypatch):
    monkeypatch.setattr(commands, "is_administrator", lambda: True)

    result = CliRunner().invoke(app, ["install", "--source", str(release), "--no-firewall"])

    assert result.exit_code == 1
    assert "packaged executable" in result.output


def test_service_and_firewall_need_administrator_rights(home, release, monkeypatch):
    monkeypatch.setattr(commands, "is_administrator", lambda: False)

    result = CliRunner().invoke(app, ["install", "--source", str(release)])

    assert result.exit_code == 1
    assert "administrator" in result.output


def test_windows_service_needs_winsw_beside_the_release(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")

    with pytest.raises(RuntimeError, match="WinSW"):
        installer.register_service(Path("tiqr.exe"), tmp_path, tmp_path)


def test_winsw_config_names_the_executable_home_and_logs(tmp_path):
    config = installer.winsw_config(Path("C:/TiQR & Co/tiqr.exe"), Path("C:/TiQR"))

    assert "<executable>C:/TiQR &amp; Co/tiqr.exe</executable>" in config
    assert '<env name="TIQR_HOME" value="C:/TiQR"/>' in config
    assert "<logpath>C:/TiQR/logs</logpath>" in config


def test_systemd_unit_runs_serve_as_the_service_user(tmp_path):
    unit = installer.systemd_unit(Path("/srv/tiqr/tiqr"), Path("/srv/tiqr"))

    assert 'ExecStart="/srv/tiqr/tiqr" serve' in unit
    assert 'Environment="TIQR_HOME=/srv/tiqr"' in unit
    assert "User=tiqr" in unit
    assert "ReadWritePaths=/srv/tiqr" in unit


def test_health_wait_fails_when_nothing_answers():
    with pytest.raises(RuntimeError, match="did not report healthy"):
        installer.wait_until_healthy("127.0.0.1", 1, timeout=0)


def test_ufw_is_used_when_it_is_active(monkeypatch):
    commands_run = []
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "_output", lambda argv: "Status: active\n")
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")

    assert installer.open_firewall(7102) == "ufw allows TCP 7102"
    assert commands_run == [["ufw", "allow", "7102/tcp"]]


def test_no_firewall_means_nothing_is_opened(monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "_output", lambda argv: "")

    assert installer.open_firewall(7102) == "No active firewall found; nothing to open"
