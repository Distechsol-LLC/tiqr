import os
import subprocess
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


def test_reinstall_replaces_the_branding_and_keeps_a_backup(home, release):
    (home / BRANDING_FILE).write_text(BRANDING.replace("TiQR", "Previous"))

    result = CliRunner().invoke(app, ["install", "--source", str(release), *QUIET])

    assert result.exit_code == 0, result.output
    assert (home / BRANDING_FILE).read_text() == (release / BRANDING_FILE).read_text()
    assert '"Previous"' in (home / (BRANDING_FILE + ".bak")).read_text()
    assert "Replaced" in result.output


def test_install_ends_with_the_license_request_code(home, release):
    result = CliRunner().invoke(
        app, ["install", "--source", str(release), "--host", "10.0.0.5", "--port", "7200", *QUIET]
    )

    assert result.exit_code == 0, result.output
    assert "activate a license" in result.output
    assert "tiqr license activate" in result.output
    code = next(line.strip() for line in result.output.splitlines() if line.startswith("  ey"))
    assert parse_request_code(code).request_type == "standard"


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
    assert (home / "tiqr_ticket.db").exists()
    assert "No users yet" in result.output


def test_install_asks_for_the_first_admin_at_a_terminal(home, release, monkeypatch):
    prompted = []
    monkeypatch.setattr(commands, "_interactive", lambda: True)
    monkeypatch.setattr(commands, "create_first_admin", lambda: prompted.append(True))

    result = CliRunner().invoke(
        app,
        [
            "install",
            "--source",
            str(release),
            "--host",
            "10.0.0.5",
            "--port",
            "7200",
            "--pass-webhook-url",
            "",
            *QUIET,
        ],
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
    executable = Path("C:/TiQR & Co/tiqr.exe")
    home = Path("C:/TiQR")

    config = installer.winsw_config(executable, home)

    assert f"<executable>{str(executable).replace('&', '&amp;')}</executable>" in config
    assert f'<env name="TIQR_HOME" value="{home}"/>' in config
    assert f"<logpath>{home / 'logs'}</logpath>" in config


def test_winsw_config_waits_for_the_network_stack():
    config = installer.winsw_config(Path("C:/TiQR/tiqr.exe"), Path("C:/TiQR"))

    assert "<depend>Tcpip</depend>" in config


def test_windows_service_grants_only_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    program = tmp_path / "program"
    data = tmp_path / "data"
    program.mkdir()
    data.mkdir()
    wrapper = program / installer.WINSW_NAME
    wrapper.write_bytes(b"winsw")
    (program / "tiqr.exe").write_bytes(b"")
    (program / installer.HEALTH_SCRIPT_WINDOWS).write_text("")
    (data / "tiqr.db").write_bytes(b"")
    (data / installer.BRANDING_FILE).write_text("{}")
    commands_run = []
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")
    monkeypatch.setattr(
        installer.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1)
    )

    installer._install_windows_service(program / "tiqr.exe", data, wrapper)

    assert wrapper.read_bytes() == b"winsw"
    assert [str(wrapper), "install"] in commands_run
    grant = f"NT SERVICE\\{installer.SERVICE_NAME}:(OI)(CI)M"
    granted = [argv[1] for argv in commands_run if argv[0] == "icacls"]
    assert ["icacls", str(data / "tiqr.db"), "/grant", grant] in commands_run
    assert str(data) in granted
    assert str(program) not in granted
    assert str(data / installer.BRANDING_FILE) not in granted
    probe = next(
        i
        for i, argv in enumerate(commands_run)
        if argv[0] == "powershell" and argv[-2:] == ["-DataFolder", str(data)]
    )
    assert commands_run.index([str(wrapper), "start"]) < probe


def test_windows_service_runs_as_its_virtual_account(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    program = tmp_path / "program"
    data = tmp_path / "data"
    program.mkdir()
    data.mkdir()
    wrapper = program / installer.WINSW_NAME
    wrapper.write_bytes(b"winsw")
    (program / installer.HEALTH_SCRIPT_WINDOWS).write_text("")
    commands_run = []
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")
    monkeypatch.setattr(
        installer.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1)
    )

    installer._install_windows_service(program / "tiqr.exe", data, wrapper)

    account = [
        "sc.exe",
        "config",
        installer.SERVICE_NAME,
        "obj=",
        f"NT SERVICE\\{installer.SERVICE_NAME}",
    ]
    assert account in commands_run
    assert commands_run.index([str(wrapper), "install"]) < commands_run.index(account)
    assert commands_run.index(account) < commands_run.index([str(wrapper), "start"])


def test_windows_reinstall_clears_a_service_its_uninstall_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    program = tmp_path / "program"
    data = tmp_path / "data"
    program.mkdir()
    data.mkdir()
    wrapper = program / installer.WINSW_NAME
    wrapper.write_bytes(b"winsw")
    (program / installer.HEALTH_SCRIPT_WINDOWS).write_text("")
    registered = {installer.SERVICE_NAME}

    def service_manager(argv, **kwargs):
        if argv[0] == "sc.exe" and argv[1] == "query":
            code = 0 if installer.SERVICE_NAME in registered else 1060
            return subprocess.CompletedProcess(argv, code)
        if argv[0] == "sc.exe" and argv[1] == "delete":
            registered.discard(installer.SERVICE_NAME)
        if argv[0] == str(wrapper) and argv[1] == "uninstall":
            return subprocess.CompletedProcess(argv, 1)
        if argv[0] == str(wrapper) and argv[1] == "install":
            if installer.SERVICE_NAME in registered:
                return subprocess.CompletedProcess(
                    argv, 1, "", "A service with ID 'TiQR' already exists."
                )
            registered.add(installer.SERVICE_NAME)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(installer.subprocess, "run", service_manager)
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)

    installer._install_windows_service(program / "tiqr.exe", data, wrapper)

    assert installer.SERVICE_NAME in registered


def test_health_unit_reads_the_install_settings(tmp_path):
    unit = installer.health_unit(Path("/opt/tiqr"), Path("/var/lib/tiqr"))

    assert "EnvironmentFile=-/var/lib/tiqr/.env.local" in unit
    assert 'ExecStart="/opt/tiqr/tiqr-health.sh"' in unit
    assert "User=tiqr" in unit


def test_linux_service_chowns_only_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    program = tmp_path / "opt"
    data = tmp_path / "var"
    program.mkdir()
    data.mkdir()
    executable = program / "tiqr"
    executable.write_bytes(b"")
    (program / installer.HEALTH_SCRIPT_LINUX).write_text("")
    (data / "tiqr.db").write_bytes(b"")
    (data / installer.BRANDING_FILE).write_text("{}")
    monkeypatch.setattr(installer, "UNIT_PATH", tmp_path / "tiqr.service")
    monkeypatch.setattr(installer, "HEALTH_UNIT_PATH", tmp_path / "tiqr-health.service")
    monkeypatch.setattr(installer, "HEALTH_TIMER_PATH", tmp_path / "tiqr-health.timer")
    commands_run = []
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")
    monkeypatch.setattr(installer, "_succeeds", lambda argv: True)

    installer._install_linux_service(executable, data)

    chowned = [argv[-1] for argv in commands_run if argv[0] == "chown"]
    assert str(data) in chowned
    assert str(data / "tiqr.db") in chowned
    assert str(data / installer.BRANDING_FILE) not in chowned
    assert str(program) not in chowned
    assert str(program / "tiqr") not in chowned
    health = (tmp_path / "tiqr-health.service").read_text()
    assert f'ExecStart="{(program / installer.HEALTH_SCRIPT_LINUX).as_posix()}"' in health


def test_restore_gives_root_written_data_back_only_with_a_service(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)
    data = tmp_path / "var"
    data.mkdir()
    (data / "tiqr.db-wal").write_bytes(b"")
    (data / installer.BRANDING_FILE).write_text("{}")
    commands_run = []
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")
    monkeypatch.setattr(installer, "UNIT_PATH", tmp_path / "tiqr.service")

    installer.restore_service_ownership(data)
    assert commands_run == []

    (tmp_path / "tiqr.service").write_text("")
    installer.restore_service_ownership(data)
    chowned = [argv[-1] for argv in commands_run if argv[0] == "chown"]
    assert str(data / "tiqr.db-wal") in chowned
    assert str(data / installer.BRANDING_FILE) not in chowned


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


def test_linux_uninstall_removes_the_units_and_keeps_the_data(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    data = tmp_path / "var"
    data.mkdir()
    (data / "tiqr.db").write_bytes(b"")
    units = {
        "UNIT_PATH": tmp_path / "tiqr.service",
        "HEALTH_UNIT_PATH": tmp_path / "tiqr-health.service",
        "HEALTH_TIMER_PATH": tmp_path / "tiqr-health.timer",
    }
    for name, path in units.items():
        monkeypatch.setattr(installer, name, path)
        path.write_text("")
    commands_run = []
    monkeypatch.setattr(installer, "_run", lambda argv: commands_run.append(argv) or "")
    monkeypatch.setattr(installer, "_succeeds", lambda argv: commands_run.append(argv) or True)

    assert installer.is_installed()
    installer.uninstall_service(tmp_path / "tiqr")

    assert not any(path.exists() for path in units.values())
    assert ["systemctl", "disable", "tiqr.service"] in commands_run
    assert ["systemctl", "daemon-reload"] in commands_run
    assert (data / "tiqr.db").exists()


def test_linux_is_not_installed_without_units(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "UNIT_PATH", tmp_path / "tiqr.service")
    monkeypatch.setattr(installer, "HEALTH_UNIT_PATH", tmp_path / "tiqr-health.service")
    monkeypatch.setattr(installer, "HEALTH_TIMER_PATH", tmp_path / "tiqr-health.timer")

    assert not installer.is_installed()


def test_windows_wrapper_beside_the_program_is_not_an_installed_service(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    (tmp_path / installer.WINSW_NAME).write_bytes(b"")
    monkeypatch.setattr(installer, "_succeeds", lambda argv: False)

    assert not installer.is_installed()

    monkeypatch.setattr(installer, "_succeeds", lambda argv: argv[:2] == ["sc.exe", "query"])
    assert installer.is_installed()


@pytest.fixture
def service_host(monkeypatch):
    monkeypatch.setattr(commands.sys, "frozen", True, raising=False)
    monkeypatch.setattr(commands, "is_administrator", lambda: True)
    monkeypatch.setattr(commands, "wait_until_healthy", lambda host, port: None)
    monkeypatch.setattr(commands, "create_first_admin", lambda: None)
    calls = []
    # Never launch a real browser from a test.
    monkeypatch.setattr(commands, "open_browser", lambda url: calls.append(url) or True)
    state = {"installed": True}
    monkeypatch.setattr(commands, "is_installed", lambda: state["installed"])
    monkeypatch.setattr(commands, "uninstall_service", lambda executable: calls.append("uninstall"))
    monkeypatch.setattr(
        commands,
        "register_service",
        lambda executable, home, source: calls.append("register") or "running",
    )
    return calls, state


SERVICE_INSTALL = [
    "install",
    "--host",
    "10.0.0.5",
    "--port",
    "7200",
    "--pass-webhook-url",
    "",
    "--no-firewall",
]


def test_declining_a_reinstall_cancels_before_anything_changes(
    home, release, monkeypatch, service_host
):
    calls, _ = service_host
    monkeypatch.setattr(commands, "_interactive", lambda: True)

    result = CliRunner().invoke(app, [*SERVICE_INSTALL, "--source", str(release)], input="n\n")

    assert result.exit_code == 1
    assert "Install cancelled" in result.output
    assert calls == []
    assert not (home / BRANDING_FILE).exists()


def test_accepting_a_reinstall_removes_the_service_before_registering_it(
    home, release, monkeypatch, service_host
):
    calls, _ = service_host
    monkeypatch.setattr(commands, "_interactive", lambda: True)

    result = CliRunner().invoke(app, [*SERVICE_INSTALL, "--source", str(release)], input="y\n")

    assert result.exit_code == 0, result.output
    assert calls == ["uninstall", "register", "http://10.0.0.5:7200"]
    assert "Opened http://10.0.0.5:7200 in your browser" in result.output
    assert "Removed the existing TiQR service" in result.output


def test_a_reinstall_from_a_script_goes_ahead_without_asking(home, release, service_host):
    calls, _ = service_host

    result = CliRunner().invoke(app, [*SERVICE_INSTALL, "--source", str(release)])

    assert result.exit_code == 0, result.output
    assert calls == ["uninstall", "register"]


def test_a_first_install_does_not_ask(home, release, monkeypatch, service_host):
    calls, state = service_host
    state["installed"] = False
    monkeypatch.setattr(commands, "_interactive", lambda: True)

    result = CliRunner().invoke(app, [*SERVICE_INSTALL, "--source", str(release)])

    assert result.exit_code == 0, result.output
    assert "Reinstall" not in result.output
    assert calls == ["register", "http://10.0.0.5:7200"]


def test_a_reinstall_the_script_already_confirmed_is_not_asked_again(
    home, release, monkeypatch, service_host
):
    calls, _ = service_host
    monkeypatch.setattr(commands, "_interactive", lambda: True)
    monkeypatch.setenv(commands.REINSTALL_CONFIRMED_ENV, "1")

    result = CliRunner().invoke(app, [*SERVICE_INSTALL, "--source", str(release)])

    assert result.exit_code == 0, result.output
    assert "Reinstall" not in result.output
    assert calls == ["uninstall", "register", "http://10.0.0.5:7200"]


def test_install_saves_the_pass_webhook_given_as_flags(home, release):
    result = CliRunner().invoke(
        app,
        [
            "install",
            "--source",
            str(release),
            "--pass-webhook-url",
            "https://receiver.example.test/passes",
            "--pass-webhook-secret",
            "s3cret",
            *QUIET,
        ],
    )

    assert result.exit_code == 0, result.output
    env = (home / ".env.local").read_text()
    assert "TIQR_PASS_WEBHOOK_URL=https://receiver.example.test/passes" in env
    assert "TIQR_PASS_WEBHOOK_SECRET=s3cret" in env


def test_install_rejects_a_webhook_url_without_a_secret(home, release):
    result = CliRunner().invoke(
        app,
        [
            "install",
            "--source",
            str(release),
            "--pass-webhook-url",
            "https://receiver.example.test/passes",
            *QUIET,
        ],
    )

    assert result.exit_code == 1
    assert "Set TIQR_PASS_WEBHOOK_SECRET when TIQR_PASS_WEBHOOK_URL is set" in result.output


def test_webhook_set_and_clear_round_trip(home, release):
    runner = CliRunner()
    installed = runner.invoke(app, ["install", "--source", str(release), "--no-service", *QUIET])
    assert installed.exit_code == 0, installed.output

    result = runner.invoke(
        app,
        ["webhook", "set", "--url", "https://receiver.example.test/passes", "--secret", "s3cret"],
    )
    assert result.exit_code == 0, result.output
    assert "restart the TiQR service" in result.output

    shown = runner.invoke(app, ["webhook", "show"])
    assert shown.exit_code == 0, shown.output
    assert "https://receiver.example.test/passes" in shown.output
    assert "s3cret" not in shown.output

    cleared = runner.invoke(app, ["webhook", "clear"])
    assert cleared.exit_code == 0, cleared.output
    assert "TIQR_PASS_WEBHOOK_URL" not in (home / ".env.local").read_text()


def test_webhook_set_refuses_a_url_that_is_not_http(home):
    result = CliRunner().invoke(
        app, ["webhook", "set", "--url", "ftp://receiver.example.test", "--secret", "s3cret"]
    )

    assert result.exit_code == 1
    assert "must be an http:// or https:// address" in result.output


def test_browser_url_uses_loopback_for_an_unspecified_address():
    assert installer.browser_url("0.0.0.0", 7102, secure=False) == "http://127.0.0.1:7102"
    assert installer.browser_url("::1", 443, secure=True) == "https://[::1]:443"
