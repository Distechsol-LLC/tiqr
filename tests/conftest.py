from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_DNS, uuid5

import pytest

from tiqr.core import settings
from tiqr.core.auth import new_user
from tiqr.core.models import Role
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService

SECRET = "development-only-64e2d7e02b9f49828c52d840565de390"


@pytest.fixture(autouse=True)
def project_root(tmp_path, monkeypatch):
    # Config lives under each test's own directory, never the real checkout's.
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
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


@pytest.fixture
def service(repository, clock):
    return TicketService(repository, SECRET, clock=clock)
