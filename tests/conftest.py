import importlib.util
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tiqr.core import settings
from tiqr.core.auth import new_user
from tiqr.core.license import build_request_code, parse_request_code
from tiqr.core.models import Role
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService

REPO_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_BRANDING = (
    '{"app_name": "TiQR", "logo_path": null, "theme": "default",'
    ' "languages": ["en-US", "ru-RU", "az-AZ"]}'
)
SECRET = "development-only-64e2d7e02b9f49828c52d840565de390"


@pytest.fixture(autouse=True)
def project_root(tmp_path, monkeypatch):
    # Config lives under each test's own directory, never the real checkout's.
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    # The program does not run without its branding file, so each test gets a minimal one.
    (tmp_path / settings.BRANDING_FILE).write_text(MINIMAL_BRANDING)
    return tmp_path


@dataclass
class Clock:
    now: datetime = datetime(2026, 9, 17, 8, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture(scope="session")
def accounts():
    base = new_user("base", "correct-password", Role.OPERATOR)
    return {
        role.value: replace(
            base, id=uuid5(NAMESPACE_DNS, role.value), username=role.value, role=role
        )
        for role in Role
    } | {"other": replace(base, id=uuid5(NAMESPACE_DNS, "other"), username="other")}


@pytest.fixture
def repository(accounts):
    repo = SQLiteRepository(":memory:")
    repo.initialize()
    for user in accounts.values():
        repo.add_user(user)
    yield repo
    repo.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(scope="session")
def license_pair():
    """A throwaway RSA pair standing in for the vendor's: (private PEM bytes, public PEM text)."""
    key = rsa.generate_private_key(65537, 2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public.decode()


def _vendor():
    spec = importlib.util.spec_from_file_location(
        "issue_license", REPO_ROOT / "tools/issue_license.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def issue(clock, license_pair):
    """Sign a key for this machine with the vendor tool's own code."""
    vendor = _vendor()

    def make(kind="standard", *, days=365, machine=None, **overrides):
        request = parse_request_code(build_request_code("trial" if kind == "trial" else "standard"))
        payload = vendor.build_payload(
            request, kind=kind, licensed_to="Acme", days=days, now=clock.now
        )
        payload |= overrides
        if machine is not None:
            payload["machineId"] = machine
        return vendor.sign_license(payload, license_pair[0])

    return make


@pytest.fixture
def service(repository, clock, license_pair):
    return TicketService(repository, SECRET, clock=clock, license_public_key=license_pair[1])
