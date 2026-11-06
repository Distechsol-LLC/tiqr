"""Entry point for the packaged executable: set up on first use, then run the CLI.

Double-clicked, it opens a terminal window in its own folder and runs the CLI there.
"""

import ctypes
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from tiqr.cli.commands import app, create_first_admin
from tiqr.cli.installer import restore_service_ownership
from tiqr.core.repository import SQLiteRepository
from tiqr.core.settings import Settings, database_path

# Commands that must not create the signing key or database as a side effect.
_SETUP_SKIPPED = frozenset({"setup", "reset", "selftest", "-h", "--help"})
# Linux terminals in preference order, with the arguments before the command.
_LINUX_TERMINALS = (
    ("x-terminal-emulator", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xfce4-terminal", ("-x",)),
    ("alacritty", ("-e",)),
    ("kitty", ()),
    ("xterm", ("-e",)),
)
_KEEP_SHELL_OPEN = 'exec "${SHELL:-/bin/sh}"'
# Set in the terminal we open, so the CLI waits for Enter before that window closes.
_PAUSE_ENV = "TIQR_PAUSE_ON_EXIT"


def _interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def _launched_from_file_manager() -> bool:
    if sys.platform == "win32":
        # A console created by a double-click has no other process attached.
        attached = (ctypes.c_uint * 2)()
        return ctypes.windll.kernel32.GetConsoleProcessList(attached, 2) == 1
    return not _interactive()


def _skips_setup(arguments: Sequence[str]) -> bool:
    return bool(arguments) and arguments[0] in _SETUP_SKIPPED


def _needs_setup(arguments: Sequence[str]) -> bool:
    if _skips_setup(arguments):
        return False
    try:
        settings = Settings.from_env()
    except ValueError, LookupError:
        # Bad key, partial BioStar block or unknown timezone; setup reports which.
        return True
    # A database of an earlier release still needs setup to rename it.
    return not settings.database_path.exists()


def _needs_admin(arguments: Sequence[str]) -> bool:
    # Only a person at a terminal can answer the prompt.
    if _skips_setup(arguments) or not _interactive():
        return False
    with SQLiteRepository(Settings.from_env().database_path) as repository:
        repository.initialize()
        return not repository.list_users()


def _open_terminal(executable: Path) -> bool:
    """Open a terminal in the executable's folder that runs the CLI and stays open."""
    folder = executable.parent
    environment = {**os.environ, _PAUSE_ENV: "1"}
    if sys.platform == "win32":
        subprocess.Popen(  # noqa: S603 - fixed shell; the only argument is this executable's name
            ["cmd.exe", "/k", executable.name],  # noqa: S607 - cmd.exe is always on Windows
            cwd=folder,
            env=environment,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    command = (
        f"cd {shlex.quote(str(folder))} && ./{shlex.quote(executable.name)}; {_KEEP_SHELL_OPEN}"
    )
    for terminal, flags in _LINUX_TERMINALS:
        if shutil.which(terminal):
            subprocess.Popen(  # noqa: S603 - the terminal is picked from a fixed list
                [terminal, *flags, "sh", "-c", command], env=environment
            )
            return True
    return False


def _pause() -> None:
    if _interactive():
        input("Press Enter to close this window...")


def _run(arguments: Sequence[str]) -> None:
    if _needs_setup(arguments):
        # Non-standalone, so a failed setup returns its exit code instead of exiting.
        code = app(args=["setup"], standalone_mode=False)
        if code:
            raise SystemExit(code)
    if _needs_admin(arguments):
        try:
            create_first_admin()
        except typer.Abort:
            typer.echo("Cancelled before an admin account was created.", err=True)
            raise SystemExit(1) from None
    app(args=arguments)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and _launched_from_file_manager():
        executable = Path(sys.executable)
        if not _open_terminal(executable):
            typer.echo(f"No terminal window could be opened. Run {executable.name} from a terminal")
            _pause()
            raise SystemExit(1)
        return
    try:
        _run(arguments)
    finally:
        # A root run may have created database files the service cannot write; hand them back.
        restore_service_ownership(database_path().parent)
        # Runs on success, failure and the CLI's own exit, so the output stays readable.
        if os.environ.get(_PAUSE_ENV):
            _pause()
