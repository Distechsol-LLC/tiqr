import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
MEMBERS = ("core", "cli", "api")
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


def _version(pyproject):
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


@pytest.fixture(scope="module")
def built_wheels(tmp_path_factory):
    output = tmp_path_factory.mktemp("wheels")
    candidates = [
        shutil.which("uv"),
        os.environ.get("UV"),
        PROJECT / ".tools" / "uv",
        Path.home() / ".local" / "bin" / "uv",
    ]
    uv = next((str(c) for c in candidates if c and Path(c).is_file()), None)
    assert uv is not None, "uv is required: install uv, set UV, or provide project .tools/uv"
    result = subprocess.run(
        [uv, "build", "--all-packages", "--wheel", "--out-dir", str(output)],
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = {}
    for member in MEMBERS:
        (wheel,) = output.glob(f"tiqr_{member}-*.whl")
        wheels[member] = wheel
    assert len(list(output.glob("*.whl"))) == len(MEMBERS)
    return wheels


def _metadata(archive):
    name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
    return BytesParser().parsebytes(archive.read(name))


def _dependencies(archive):
    return {
        re.split(r"[\s(;\[<>=!~]", value, maxsplit=1)[0].lower().replace("_", "-")
        for value in _metadata(archive).get_all("Requires-Dist", [])
    }


def _imports(archive, package):
    imports = set()
    for name in archive.namelist():
        if name.startswith(f"tiqr/{package}/") and name.endswith(".py"):
            tree = ast.parse(archive.read(name).decode("utf-8"), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
    return imports


def test_every_member_carries_the_product_version():
    version = _version(PROJECT / "pyproject.toml")
    for member in MEMBERS:
        assert _version(PROJECT / "apps" / member / "pyproject.toml") == version, member


def test_each_wheel_holds_only_its_own_namespace_package(built_wheels):
    for member, wheel in built_wheels.items():
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        # tiqr is a shared namespace; a tiqr/__init__.py would shadow the other members.
        assert "tiqr/__init__.py" not in names, member
        assert f"tiqr/{member}/__init__.py" in names, member
        for name in names:
            parts = Path(name).parts
            # Directory entries such as tiqr/ list no files of their own.
            if name.endswith("/"):
                continue
            assert parts[:2] == ("tiqr", member) or parts[0].endswith(".dist-info"), name


def test_core_wheel_contains_assets_and_only_library_scope(built_wheels):
    with zipfile.ZipFile(built_wheels["core"]) as archive:
        assert archive.read("tiqr/core/assets/images/distechsol.webp")[8:12] == b"WEBP"
        assert archive.read("tiqr/core/assets/images/suprema.webp")[8:12] == b"WEBP"
        assert archive.read("tiqr/core/assets/images/tiqr.png").startswith(b"\x89PNG")
        assert archive.read("tiqr/core/assets/fonts/Geist.ttf").startswith(b"\x00\x01\x00\x00")
        for name in archive.namelist():
            for part in Path(name).parts[2:]:
                assert Path(part).stem.lower() not in FORBIDDEN, name
        assert {"httpx2", "qrcode", "reportlab", "tzdata"} <= _dependencies(archive)


def test_core_and_cli_have_no_web_framework_dependencies_or_imports(built_wheels):
    for member in ("core", "cli"):
        with zipfile.ZipFile(built_wheels[member]) as archive:
            assert not _dependencies(archive) & WEB_FRAMEWORKS, member
            roots = {module.split(".")[0] for module in _imports(archive, member)}
            assert not roots & (WEB_FRAMEWORKS | {"app", "printer_agent"}), member


def test_core_never_imports_the_layers_above_it(built_wheels):
    with zipfile.ZipFile(built_wheels["core"]) as archive:
        imports = _imports(archive, "core")
    assert not {m for m in imports if m.startswith(("tiqr.cli", "tiqr.api"))}


def test_cli_wheel_provides_the_tiqr_command(built_wheels):
    with zipfile.ZipFile(built_wheels["cli"]) as archive:
        names = archive.namelist()
        entrypoints = next(name for name in names if name.endswith("/entry_points.txt"))
        assert "tiqr = tiqr.cli.commands:app" in archive.read(entrypoints).decode()
        assert "tiqr/cli/__main__.py" in names
        assert {"tiqr-core", "tiqr-api", "typer"} <= _dependencies(archive)


def test_api_wheel_holds_the_web_stack_and_never_imports_the_cli(built_wheels):
    with zipfile.ZipFile(built_wheels["api"]) as archive:
        assert {"tiqr-core", "fastapi", "uvicorn"} <= _dependencies(archive)
        assert "typer" not in _dependencies(archive)
        imports = _imports(archive, "api")
        assert "tiqr/api/app.py" in archive.namelist()
    assert not {m for m in imports if m.startswith("tiqr.cli") or m.split(".")[0] == "typer"}


def test_installed_wheels_isolated_smoke(built_wheels, tmp_path):
    installation = tmp_path / "installed"
    for member in MEMBERS:
        with zipfile.ZipFile(built_wheels[member]) as archive:
            archive.extractall(installation)
    script = r"""
import importlib
import json
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from importlib.resources import files

root = pathlib.Path(sys.argv[1]).resolve()
source = pathlib.Path(sys.argv[2]).resolve()
sources = {source, *(source / "apps" / member / "src" for member in ("core", "cli", "api"))}
sys.path[:] = [entry for entry in sys.path
    if entry and pathlib.Path(entry).resolve() not in sources]
sys.path.insert(0, str(root))
import tiqr.core
from tiqr.core.models import Mode, Role, UsageType
from tiqr.core.pdf import render_pdf
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService
from typer.testing import CliRunner
from tiqr.cli.commands import app

assert pathlib.Path(tiqr.core.__file__).resolve().is_relative_to(root)
for module in ("tiqr.cli.commands", "tiqr.core.pdf", "tiqr.core.service", "tiqr.core.settings",
        "tiqr.core.repository", "tiqr.api.app"):
    imported = importlib.import_module(module)
    assert pathlib.Path(imported.__file__).resolve().is_relative_to(root)
assets = files("tiqr.core").joinpath("assets", "images")
assert assets.joinpath("distechsol.webp").read_bytes()[8:12] == b"WEBP"
assert assets.joinpath("suprema.webp").read_bytes()[8:12] == b"WEBP"
assert CliRunner().invoke(app, ["--help"]).exit_code == 0
repository = SQLiteRepository(":memory:")
repository.initialize()
repository.save_active_hours(None)
try:
    now = datetime(2030, 1, 1, 8, tzinfo=UTC)
    service = TicketService(
        repository, "installed-wheel-signing-key", clock=lambda: now, mode=Mode.BADGE
    )
    actor = service.add_user("admin", "wheel-password", Role.ADMIN)
    service.create_visitor_type(actor, "Visitor")
    ticket = service.create_ticket(actor, visitor_name="Əli Иванов", visitor_type="Visitor",
        valid_from=now, valid_until=now + timedelta(hours=1), usage_type=UsageType.MULTI_USE)
    path = service.print_ticket(actor, ticket.id, root / "smoke-output", renderer=render_pdf)
    assert ticket.readable_serial.encode() in path.read_bytes()
    assert repository.get_ticket(ticket.id).print_count == 1
finally:
    repository.close()
# An installed service keeps its config and data under TIQR_HOME, wherever the code lives.
from fastapi.testclient import TestClient
from tiqr.api.app import create_app
from tiqr.api.config import ServerConfig
from tiqr.api.maintenance import Maintenance
from tiqr.core import settings
home = pathlib.Path(os.environ["TIQR_HOME"]).resolve()
assert settings.PROJECT_ROOT == home
config = ServerConfig(dev=True)
scheduler = lambda service: Maintenance(service, sync_interval=0, cleanup_interval=0)
with TestClient(create_app(config, scheduler=scheduler)) as client:
    assert client.get("/api/health").json()["status"] == "ok"
assert (home / "tiqr_ticket.db").is_file()
for name, module in tuple(sys.modules.items()):
    if name.startswith("tiqr.") and getattr(module, "__file__", None):
        assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name
print(json.dumps({"package": str(pathlib.Path(tiqr.core.__file__).resolve()),
    "files": sorted(path.relative_to(root).as_posix()
        for path in (root / "tiqr").rglob("*") if path.is_file())}))
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("TIQR_")}
    environment.pop("PYTHONPATH", None)
    environment["TIQR_HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir()
    shutil.copy(PROJECT / "tiqr_brand.jsonc", tmp_path / "home")
    environment["TIQR_SECRET_KEY"] = "installed-wheel-signing-key"
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
    assert "tiqr/core/assets/images/distechsol.webp" in installed["files"]
    assert "tiqr/core/assets/images/suprema.webp" in installed["files"]
    assert "tiqr/core/assets/fonts/Geist.ttf" in installed["files"]
    assert all(not set(Path(name).parts[2:]) & FORBIDDEN for name in installed["files"])
