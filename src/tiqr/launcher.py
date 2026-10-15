"""Entry point for the packaged executable: set up on first use, then run the CLI.

A double-clicked executable has no terminal to print into, so it opens a new terminal window in
its own folder and runs the CLI there. Run from a terminal, it works like the `tiqr` command.
"""

import ctypes
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from tiqr.cli import app
from tiqr.repository import SQLiteRepository
from tiqr.settings import Settings, database_path

# Commands that must not create the signing key or database as a side effect.
_SETUP_SKIPPED = frozenset({"setup", "reset", "-h", "--help"})
# Linux terminal emulators in preference order, each with the arguments before the command.
_LINUX_TERMINALS = (
    ("x-terminal-emulator", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xfce4-terminal", ("-x",)),
    ("alacritty", ("-e",)),
    ("kitty", ()),
    ("xterm", ("-e",)),
)
# Shell the new window keeps open after the CLI prints, so the user can keep typing commands.
_KEEP_SHELL_OPEN = 'exec "${SHELL:-/bin/sh}"'


def _interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()


def _launched_from_file_manager() -> bool:
    if sys.platform == "win32":
        # A console that a double-click created has no other process attached to it.
        attached = (ctypes.c_uint * 2)()
        return ctypes.windll.kernel32.GetConsoleProcessList(attached, 2) == 1
    return not _interactive()


def _skips_setup(arguments: Sequence[str]) -> bool:
    return bool(arguments) and arguments[0] in _SETUP_SKIPPED


def _needs_setup(arguments: Sequence[str]) -> bool:
    if _skips_setup(arguments):
        return False
    try:
        Settings.from_env()
    except ValueError, LookupError:
        # Missing or placeholder key, a partial BioStar block, or an unknown timezone (a
        # LookupError); setup reports which.
        return True
    return not database_path().exists()


def _needs_admin(arguments: Sequence[str]) -> bool:
    # Only a person at a terminal can answer the prompt; scripts keep their own accounts.
    if _skips_setup(arguments) or not _interactive():
        return False
    with SQLiteRepository(Settings.from_env().database_path) as repository:
        repository.initialize()
        return not repository.list_users()


def _create_first_admin() -> None:
    typer.echo("No users yet. Create the first admin account.")
    while True:
        username = typer.prompt("Admin username")
        # A rejected attempt, such as an empty password, has printed its error; ask again.
        if not app(args=["user", "add", username, "--role", "admin"], standalone_mode=False):
            return


def _open_terminal(executable: Path) -> bool:
    """Open a terminal window in the executable's folder that runs the CLI and stays open."""
    folder = executable.parent
    if sys.platform == "win32":
        # cmd.exe finds the executable in its current folder, so the bare name needs no quoting.
        subprocess.Popen(  # noqa: S603 - fixed shell; the only argument is this executable's name
            ["cmd.exe", "/k", executable.name],  # noqa: S607 - cmd.exe is always on Windows
            cwd=folder,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    command = (
        f"cd {shlex.quote(str(folder))} && ./{shlex.quote(executable.name)}; {_KEEP_SHELL_OPEN}"
    )
    if sys.platform == "darwin":
        # AppleScript strings escape backslashes and double quotes the same way as C strings.
        script = command.replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.run(  # noqa: S603 - fixed AppleScript runner; the script is built here
                [
                    "/usr/bin/osascript",
                    "-e",
                    f'tell application "Terminal" to do script "{script}"',
                    "-e",
                    'tell application "Terminal" to activate',
                ],
                check=True,
            )
        except OSError, subprocess.CalledProcessError:
            return False
        return True
    for terminal, flags in _LINUX_TERMINALS:
        if shutil.which(terminal):
            subprocess.Popen(  # noqa: S603 - the terminal is picked from a fixed list
                [terminal, *flags, "sh", "-c", command]
            )
            return True
    return False


def _pause() -> None:
    if _interactive():
        input("Press Enter to close this window...")


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and _launched_from_file_manager():
        executable = Path(sys.executable)
        if not _open_terminal(executable):
            typer.echo(f"No terminal window could be opened. Run {executable.name} from a terminal")
            _pause()
            raise SystemExit(1)
        return
    if _needs_setup(arguments):
        # Standalone mode is off so a failed setup returns its exit code instead of exiting here.
        code = app(args=["setup"], standalone_mode=False)
        if code:
            raise SystemExit(code)
    if _needs_admin(arguments):
        try:
            _create_first_admin()
        except typer.Abort:
            typer.echo("Cancelled before an admin account was created.", err=True)
            raise SystemExit(1) from None
    app(args=arguments)
