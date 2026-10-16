import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import typer

from tiqr.cli import launcher
from tiqr.core.repository import SQLiteRepository
from tiqr.core.settings import database_path, provision_secret


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TIQR_"):
            monkeypatch.delenv(key)


def test_setup_is_needed_until_key_and_database_exist(tmp_path):
    assert launcher._needs_setup(["user", "list"])
    provision_secret()
    assert launcher._needs_setup(["user", "list"])
    with SQLiteRepository(database_path()) as repository:
        repository.initialize()
    assert not launcher._needs_setup(["user", "list"])


@pytest.mark.parametrize("arguments", [["setup"], ["reset"], ["--help"], ["-h"]])
def test_setup_and_help_never_trigger_setup(tmp_path, arguments):
    assert not launcher._needs_setup(arguments)


def test_unknown_timezone_asks_for_setup_instead_of_crashing(tmp_path, monkeypatch):
    provision_secret()
    with SQLiteRepository(database_path()) as repository:
        repository.initialize()
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "Mars/Olympus")
    assert launcher._needs_setup(["user", "list"])


def test_first_run_sets_up_then_runs_the_command(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["user", "list"])
    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "Wrote TIQR_SECRET_KEY" in output
    assert "Database initialized" in output
    assert output.rstrip().endswith("[]")
    assert (tmp_path / ".env.local").exists()
    assert database_path().exists()


def test_double_click_opens_terminal_and_leaves_setup_to_it(tmp_path, monkeypatch):
    opened: list[Path] = []

    def open_terminal(executable: Path) -> bool:
        opened.append(executable)
        return True

    monkeypatch.setattr(launcher, "_launched_from_file_manager", lambda: True)
    monkeypatch.setattr(launcher, "_open_terminal", open_terminal)
    launcher.main([])
    assert opened == [Path(sys.executable)]
    assert not (tmp_path / ".env.local").exists()


def test_linux_terminal_runs_cli_then_keeps_a_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: name == "xterm" or None)
    started: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **_: started.append(argv))
    assert launcher._open_terminal(tmp_path / "tiqr")
    command = f'cd {shlex.quote(str(tmp_path))} && ./tiqr; exec "${{SHELL:-/bin/sh}}"'
    assert started == [["xterm", "-e", "sh", "-c", command]]


def test_linux_prefers_earlier_terminal_with_its_own_argument_form(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    installed = {"gnome-terminal", "xterm"}
    monkeypatch.setattr(launcher.shutil, "which", lambda name: name in installed or None)
    started: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **_: started.append(argv))
    assert launcher._open_terminal(tmp_path / "tiqr")
    assert [argv[:2] for argv in started] == [["gnome-terminal", "--"]]


def test_linux_without_any_terminal_reports_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    assert not launcher._open_terminal(tmp_path / "tiqr")


def test_windows_console_runs_executable_from_its_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)))
    assert launcher._open_terminal(tmp_path / "tiqr.exe")
    assert calls == [(["cmd.exe", "/k", "tiqr.exe"], {"cwd": tmp_path, "creationflags": 0x10})]


def _answers(*values: str):
    remaining = iter(values)
    return lambda text, **_: next(remaining)


def test_interactive_first_run_creates_the_admin_before_the_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_interactive", lambda: True)
    monkeypatch.setattr(typer, "prompt", _answers("root", "root-password"))
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["user", "list"])
    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "No users yet" in output
    assert '"role": "admin"' in output
    assert '"username": "root"' in output


def test_rejected_admin_attempt_asks_for_the_username_again(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_interactive", lambda: True)
    # The first password is blank, so the attempt fails and the username is asked again.
    monkeypatch.setattr(typer, "prompt", _answers("root", "", "root", "root-password"))
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["user", "list"])
    captured = capsys.readouterr()
    assert exit_info.value.code == 0
    assert "Error: Password must not be empty" in captured.err
    assert '"username": "root"' in captured.out


def test_cancelling_the_admin_prompt_exits_without_creating_one(tmp_path, monkeypatch):
    def cancel(text, **_):
        raise typer.Abort

    monkeypatch.setattr(launcher, "_interactive", lambda: True)
    monkeypatch.setattr(typer, "prompt", cancel)
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["user", "list"])
    assert exit_info.value.code == 1


def test_scripted_runs_never_prompt_for_an_admin(tmp_path, monkeypatch, capsys):
    def unexpected(text, **_):
        raise AssertionError(f"unexpected prompt: {text}")

    monkeypatch.setattr(launcher, "_interactive", lambda: False)
    monkeypatch.setattr(typer, "prompt", unexpected)
    with pytest.raises(SystemExit) as exit_info:
        launcher.main(["user", "list"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.rstrip().endswith("[]")


@pytest.mark.parametrize("arguments", [["setup"], ["reset"], ["--help"]])
def test_setup_and_help_never_ask_for_an_admin(tmp_path, monkeypatch, arguments):
    monkeypatch.setattr(launcher, "_interactive", lambda: True)
    assert not launcher._needs_admin(arguments)
