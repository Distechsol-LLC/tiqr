import ast
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "app",
    "static",
    "routes",
    "server",
    "printqueue",
    "print_queue",
    "printer_agent",
    "printeragent",
    "scripts",
    "deploy",
}
WEB_FRAMEWORKS = {"fastapi", "starlette", "uvicorn", "flask", "django", "quart", "sanic"}


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    output = tmp_path_factory.mktemp("wheel")
    uv = shutil.which("uv")
    if uv is None:
        local = PROJECT / ".tools" / "uv"
        assert local.is_file(), "uv is required: install uv or provide project .tools/uv"
        uv = str(local)
    result = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(output)],
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_built_wheel_contains_logos_and_only_library_scope(built_wheel):
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
        assert archive.read("tiqr/assets/images/distechsol.webp")[8:12] == b"WEBP"
        assert archive.read("tiqr/assets/images/suprema.webp")[8:12] == b"WEBP"
        assert archive.read("tiqr/assets/fonts/Geist.ttf").startswith(b"\x00\x01\x00\x00")
        for name in names:
            parts = Path(name).parts
            assert parts[0] == "tiqr" or parts[0].endswith(".dist-info"), name
            for part in parts:
                assert Path(part).stem.lower() not in FORBIDDEN, name
        entrypoints = next(name for name in names if name.endswith("/entry_points.txt"))
        assert "tiqr = tiqr.cli:app" in archive.read(entrypoints).decode()
        assert "tiqr/__main__.py" in names


def test_built_wheel_has_no_web_framework_dependencies_or_imports(built_wheel):
    with zipfile.ZipFile(built_wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        dependencies = {
            re.split(r"[\s(;\[<>=!~]", value, maxsplit=1)[0].lower().replace("_", "-")
            for value in metadata.get_all("Requires-Dist", [])
        }
        assert not dependencies & WEB_FRAMEWORKS
        assert {"typer", "qrcode", "reportlab", "tzdata"} <= dependencies
        for name in archive.namelist():
            if name.startswith("tiqr/") and name.endswith(".py"):
                tree = ast.parse(archive.read(name).decode("utf-8"), filename=name)
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".")[0])
                assert not imports & (WEB_FRAMEWORKS | {"app", "printer_agent"}), name


def test_installed_wheel_isolated_smoke(built_wheel, tmp_path):
    installation = tmp_path / "installed"
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(installation)
    script = r"""
import importlib
import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from importlib.resources import files

root = pathlib.Path(sys.argv[1]).resolve()
source = pathlib.Path(sys.argv[2]).resolve()
sys.path[:] = [entry for entry in sys.path
    if entry and pathlib.Path(entry).resolve() not in (source, source / "src")]
sys.path.insert(0, str(root))
import tiqr
from tiqr.models import Role, UsageType
from tiqr.pdf import render_pdf
from tiqr.repository import SQLiteRepository
from tiqr.service import TicketService
from typer.testing import CliRunner
from tiqr.cli import app

assert pathlib.Path(tiqr.__file__).resolve().is_relative_to(root)
for module in ("tiqr.cli", "tiqr.pdf", "tiqr.service", "tiqr.settings", "tiqr.repository"):
    imported = importlib.import_module(module)
    assert pathlib.Path(imported.__file__).resolve().is_relative_to(root)
assert files("tiqr").joinpath("assets", "images", "distechsol.webp").read_bytes()[8:12] == b"WEBP"
assert files("tiqr").joinpath("assets", "images", "suprema.webp").read_bytes()[8:12] == b"WEBP"
assert CliRunner().invoke(app, ["--help"]).exit_code == 0
repository = SQLiteRepository(":memory:")
repository.initialize()
try:
    now = datetime(2030, 1, 1, 8, tzinfo=UTC)
    service = TicketService(repository, "installed-wheel-signing-key", clock=lambda: now)
    actor = service.add_user("admin", "wheel-password", Role.ADMIN)
    ticket = service.create_ticket(actor, visitor_name="Əli Иванов", visitor_type="Visitor",
        valid_from=now, valid_until=now + timedelta(hours=1), usage_type=UsageType.MULTI_USE)
    path = service.print_ticket(actor, ticket.id, root / "smoke-output", renderer=render_pdf)
    assert ticket.readable_serial.encode() in path.read_bytes()
    assert repository.get_ticket(ticket.id).print_count == 1
finally:
    repository.close()
for name, module in tuple(sys.modules.items()):
    if name == "tiqr" or name.startswith("tiqr."):
        assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name
print(json.dumps({"package": str(pathlib.Path(tiqr.__file__).resolve()),
    "files": sorted(path.relative_to(root).as_posix()
        for path in (root / "tiqr").rglob("*") if path.is_file())}))
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("TIQR_")}
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(installation), str(PROJECT)],
        cwd=tmp_path,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = json.loads(result.stdout)
    assert Path(installed["package"]).is_relative_to(installation)
    assert "tiqr/assets/images/distechsol.webp" in installed["files"]
    assert "tiqr/assets/images/suprema.webp" in installed["files"]
    assert "tiqr/assets/fonts/Geist.ttf" in installed["files"]
    assert all(not set(Path(name).parts) & FORBIDDEN for name in installed["files"])
