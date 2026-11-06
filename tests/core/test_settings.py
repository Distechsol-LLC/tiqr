import os
import stat
import sys
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest

from tiqr.core import settings
from tiqr.core.settings import (
    Settings,
    discard_access_group_id,
    discard_secret,
    provision_secret,
    validate_secret,
)


def _key(text):
    return next(
        line.split("=", 1)[1] for line in text.splitlines() if line.startswith("TIQR_SECRET_KEY=")
    )


def test_creates_local_file_with_key_and_private_mode(tmp_path):
    path = tmp_path / ".env.local"

    assert provision_secret(path) is True

    text = path.read_text(encoding="utf-8")
    validate_secret(_key(text))
    if os.name != "nt":  # Windows has no POSIX file modes; chmod only toggles read-only
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_keeps_existing_valid_key_and_other_lines(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text(
        "TIQR_SECRET_KEY=" + "ab" * 32 + "\nTIQR_DEFAULT_TZ=Asia/Baku\n", encoding="utf-8"
    )

    assert provision_secret(path) is False

    assert path.read_text(encoding="utf-8").endswith("TIQR_DEFAULT_TZ=Asia/Baku\n")


@pytest.mark.parametrize("current", ["", "change-me", "replace-me"])
def test_replaces_placeholder_key_in_place(tmp_path, current):
    path = tmp_path / ".env.local"
    path.write_text(
        f"# keep\nTIQR_SECRET_KEY={current}\nTIQR_DEFAULT_TZ=Asia/Baku\n", encoding="utf-8"
    )

    assert provision_secret(path) is True

    text = path.read_text(encoding="utf-8")
    assert text.startswith("# keep\n")
    assert text.count("TIQR_SECRET_KEY=") == 1
    assert "TIQR_DEFAULT_TZ=Asia/Baku" in text
    validate_secret(_key(text))


def test_config_is_read_from_project_root_not_working_directory(
    monkeypatch, tmp_path, project_root
):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    (project_root / ".env").write_text("TIQR_SECRET_KEY=root-file-key-0123456789abcdef\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_text("TIQR_DEFAULT_TZ=Asia/Baku\n")
    (elsewhere / ".env.local").write_text("TIQR_SECRET_KEY=wrong-file-key-0123456789abcdef\n")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr("tiqr.core.settings._detected_timezone", lambda: None)

    settings = Settings.from_env()

    assert settings.secret_key == "root-file-key-0123456789abcdef"
    assert settings.default_tz == "UTC"
    assert settings.database_path == project_root / "tiqr_ticket.db"


def _zone_file(root, name):
    path = root / "usr" / "share" / "zoneinfo" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_detected_timezone_prefers_tz_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", ":Asia/Baku")

    assert settings._detected_timezone(tmp_path / "missing", tmp_path / "missing") == "Asia/Baku"


def test_detected_timezone_reads_localtime_link(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", "Mars/Olympus")
    localtime = tmp_path / "localtime"
    localtime.symlink_to(_zone_file(tmp_path, "Europe/Paris"))

    assert settings._detected_timezone(localtime, tmp_path / "missing") == "Europe/Paris"


def test_detected_timezone_reads_timezone_file(monkeypatch, tmp_path):
    monkeypatch.delenv("TZ", raising=False)
    timezone_file = tmp_path / "timezone"
    timezone_file.write_text("Asia/Almaty\n", encoding="utf-8")

    assert settings._detected_timezone(tmp_path / "missing", timezone_file) == "Asia/Almaty"


def test_detected_timezone_is_none_when_unreadable_or_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", "<+04>-4")
    timezone_file = tmp_path / "timezone"
    timezone_file.write_text("Not/AZone\n", encoding="utf-8")

    assert settings._detected_timezone(tmp_path / "missing", timezone_file) is None


def test_blank_default_tz_uses_detected_zone(monkeypatch, project_root):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "ab" * 32)
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "")
    monkeypatch.setattr(settings, "_detected_timezone", lambda: "Asia/Almaty")

    assert Settings.from_env().default_tz == "Asia/Almaty"


def test_explicit_default_tz_wins_over_detection(monkeypatch, project_root):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "ab" * 32)
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "Asia/Baku")
    monkeypatch.setattr(settings, "_detected_timezone", lambda: "Asia/Almaty")

    assert Settings.from_env().default_tz == "Asia/Baku"


def test_invalid_explicit_default_tz_fails_loudly(monkeypatch, project_root):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "ab" * 32)
    monkeypatch.setenv("TIQR_DEFAULT_TZ", "Mars/Olympus")

    with pytest.raises(ZoneInfoNotFoundError):
        Settings.from_env()


@pytest.mark.parametrize(
    ("value", "prefix"),
    [(None, "TQR"), ("", "TQR"), ("TQR", "TQR"), ("NMK", "NMK"), ("DTS", "DTS")],
)
def test_ticket_prefix_comes_from_env_and_defaults_to_tqr(monkeypatch, project_root, value, prefix):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "ab" * 32)
    if value is not None:
        monkeypatch.setenv("TIQR_PREFIX", value)

    assert Settings.from_env().prefix == prefix


def test_unknown_ticket_prefix_fails_loudly(monkeypatch, project_root):
    for name in tuple(os.environ):
        if name.startswith("TIQR_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TIQR_SECRET_KEY", "ab" * 32)
    monkeypatch.setenv("TIQR_PREFIX", "TiQR")

    with pytest.raises(ValueError, match="Ticket prefix"):
        Settings.from_env()


def test_discard_secret_removes_only_the_key(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text("# keep\nTIQR_SECRET_KEY=" + "ab" * 32 + "\nTIQR_DEFAULT_TZ=Asia/Baku\n")

    assert discard_secret(path) is True

    assert path.read_text() == "# keep\nTIQR_DEFAULT_TZ=Asia/Baku\n"
    assert discard_secret(path) is False
    assert discard_secret(tmp_path / "missing") is False


def test_discard_access_group_id_blanks_only_the_pinned_value(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text(
        "# TIQR_BIOSTAR_ACCESS_GROUP_ID=9\nTIQR_BIOSTAR_ACCESS_GROUP_ID=3\nTIQR_DEFAULT_TZ=UTC\n"
    )

    assert discard_access_group_id(path) is True

    assert path.read_text() == (
        "# TIQR_BIOSTAR_ACCESS_GROUP_ID=9\nTIQR_BIOSTAR_ACCESS_GROUP_ID=\nTIQR_DEFAULT_TZ=UTC\n"
    )
    assert discard_access_group_id(path) is False
    assert discard_access_group_id(tmp_path / "missing") is False


def test_frozen_build_keeps_config_beside_executable(tmp_path, monkeypatch):
    monkeypatch.delenv("TIQR_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "tiqr"))
    assert settings._project_root() == tmp_path.resolve()


def test_installed_windows_program_keeps_data_in_programdata(tmp_path, monkeypatch):
    monkeypatch.delenv("TIQR_HOME", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Program Files" / "TiQR" / "tiqr.exe"))
    assert settings._project_root() == tmp_path / "ProgramData" / "TiQR"


def test_installed_linux_program_keeps_data_in_var_lib(tmp_path, monkeypatch):
    monkeypatch.delenv("TIQR_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "opt" / "tiqr" / "tiqr"))
    assert settings._project_root() == Path("/var/lib/tiqr")
