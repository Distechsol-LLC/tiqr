import os
import secrets
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

from tiqr.qr import DEFAULT_PREFIX, validate_prefix


def _project_root() -> Path:
    # A frozen build unpacks into a temporary directory, so config and data sit beside the
    # executable. Source checkouts keep them beside src/, never in the working directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()
# Later files override earlier ones; real environment variables override both.
LOCAL_ENV_FILE = ".env.local"
ENV_FILES = (".env", LOCAL_ENV_FILE)
SESSION_FILE = ".tiqr-session.json"

_PLACEHOLDER_SECRETS = frozenset(
    {
        "secret",
        "secret-key",
        "placeholder",
        "changeme",
        "change-me",
        "change-me-now",
        "your-secret-key",
        "your-secret-here",
        "replace-me",
        "test-secret-key",
        "demo-secret-key-do-not-use",
    }
)
_PLACEHOLDER_FRAGMENTS = ("placeholder", "do-not-use", "change-me")
_BIOSTAR_REQUIRED = ("BASE_URL", "USERNAME", "PASSWORD", "DEVICE_IDS")
_BIOSTAR_OPTIONAL = (
    "ACCESS_GROUP_ID",
    "VERIFY_TLS",
    "TIMEOUT",
    "USER_ID_BASE",
    "DOOR_OPEN_DURATION",
    "DOOR_OPEN_TIMEOUT",
)


def _environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ENV_FILES:
        values.update(
            (key, value)
            for key, value in dotenv_values(PROJECT_ROOT / name).items()
            if value is not None
        )
    return values | dict(os.environ)


def _biostar_value(environment: Mapping[str, str], name: str, default: str = "") -> str:
    # Blank means "not set", so committed templates can list every key.
    value = environment.get(f"TIQR_BIOSTAR_{name}", "")
    return value if value.strip() else default


def _biostar_flag(environment: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = _biostar_value(environment, name, str(default)).lower()
    if value not in ("true", "false"):
        raise ValueError(f"TIQR_BIOSTAR_{name} must be true or false")
    return value == "true"


def _prefix(environment: Mapping[str, str]) -> str:
    return environment.get("TIQR_PREFIX", "").strip() or DEFAULT_PREFIX


def _device_ids(value: str) -> tuple[str, ...]:
    """Split a comma-separated list, dropping blanks and repeats but keeping order."""
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def _is_placeholder(secret: str) -> bool:
    normalized = secret.strip().lower().replace("_", "-")
    return (
        not normalized
        or normalized in _PLACEHOLDER_SECRETS
        or any(fragment in normalized for fragment in _PLACEHOLDER_FRAGMENTS)
    )


def validate_secret(secret: str) -> None:
    if _is_placeholder(secret):
        raise ValueError("TIQR_SECRET_KEY must be a nonempty, non-placeholder secret")


def _edit_local_file(path: Path, edit: Callable[[list[str]], list[str]]) -> bool:
    """Rewrite the file's lines through `edit`; report whether anything changed."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = edit(lines)
    if updated == lines:
        return False
    path.write_text("".join(f"{line}\n" for line in updated), encoding="utf-8")
    path.chmod(0o600)
    return True


def provision_secret(path: Path | None = None) -> bool:
    """Write a new signing key to the local env file unless it already holds a valid one."""
    path = path or PROJECT_ROOT / LOCAL_ENV_FILE
    if not _is_placeholder(dotenv_values(path).get("TIQR_SECRET_KEY") or ""):
        return False
    entry = f"TIQR_SECRET_KEY={secrets.token_hex(32)}"

    def edit(lines: list[str]) -> list[str]:
        header = "# Private values. Git-ignored; overrides .env. Real environment variables win."
        updated = [
            entry if line.startswith("TIQR_SECRET_KEY=") else line for line in lines or [header]
        ]
        return updated if entry in updated else [*updated, entry]

    return _edit_local_file(path, edit)


def discard_secret(path: Path | None = None) -> bool:
    """Drop the signing key from the local env file; report whether one was there."""
    path = path or PROJECT_ROOT / LOCAL_ENV_FILE
    return _edit_local_file(
        path, lambda lines: [line for line in lines if not line.startswith("TIQR_SECRET_KEY=")]
    )


def discard_access_group_id(path: Path | None = None) -> bool:
    """Blank the pinned BioStar access group so setup manages it again."""
    path = path or PROJECT_ROOT / LOCAL_ENV_FILE
    key = "TIQR_BIOSTAR_ACCESS_GROUP_ID="
    return _edit_local_file(
        path, lambda lines: [key if line.startswith(key) else line for line in lines]
    )


def database_path(environment: Mapping[str, str] | None = None) -> Path:
    """Resolve the database location without needing a valid signing key."""
    environment = _environment() if environment is None else environment
    return PROJECT_ROOT / environment.get("TIQR_DB", "tiqr.db")


def session_path() -> Path:
    """Where the CLI keeps its recent login."""
    return PROJECT_ROOT / SESSION_FILE


def _detected_timezone(
    localtime: Path = Path("/etc/localtime"), timezone_file: Path = Path("/etc/timezone")
) -> str | None:
    """Return this machine's IANA zone from TZ, /etc/localtime, or /etc/timezone, else None."""
    names = [os.environ.get("TZ", "").lstrip(":")]
    with suppress(OSError):
        # /usr/share/zoneinfo/Asia/Baku names the zone after "zoneinfo/".
        names.append(localtime.resolve(strict=True).as_posix().partition("zoneinfo/")[2])
    with suppress(OSError):
        names.append(timezone_file.read_text(encoding="utf-8").strip())
    for name in names:
        # Windows reports names with characters like "<" as OSError rather than not-found.
        with suppress(OSError, ValueError, ZoneInfoNotFoundError):
            ZoneInfo(name)
            return name
    return None


def _default_timezone(environment: Mapping[str, str]) -> str:
    configured = environment.get("TIQR_DEFAULT_TZ", "").strip()
    return configured or _detected_timezone() or "UTC"


@dataclass(frozen=True, slots=True)
class BioStarSettings:
    base_url: str
    username: str
    password: str
    device_ids: tuple[str, ...]
    # Blank means TiQR manages its own access group.
    access_group_id: str = ""
    verify_tls: bool = False
    timeout: float = 30.0
    user_id_base: int = 1_000_000
    # Seconds a door stays unlocked, and may stay open before BioStar alarms.
    door_open_duration: int = 3
    door_open_timeout: int = 10

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.netloc or url.username or url.query or url.fragment:
            raise ValueError("BioStar base URL must be HTTPS without embedded credentials")
        if url.path.rstrip("/") not in ("", "/api"):
            raise ValueError("BioStar base URL must end at the host or /api")
        if not all(value.strip() for value in (self.username, self.password)):
            raise ValueError("BioStar username and password are required")
        if not self.device_ids or not all(device.strip() for device in self.device_ids):
            raise ValueError("At least one BioStar device ID is required")
        if self.timeout <= 0 or self.user_id_base < 1:
            raise ValueError("BioStar timeout and user ID base must be positive")
        if self.door_open_duration < 1 or self.door_open_timeout < 1:
            raise ValueError("BioStar door open duration and timeout must be positive")

    @classmethod
    def from_env(cls, environment: Mapping[str, str]) -> BioStarSettings | None:
        """Read the TIQR_BIOSTAR_* block, or None when none of it is set."""
        required = {name: _biostar_value(environment, name) for name in _BIOSTAR_REQUIRED}
        optional = (_biostar_value(environment, name) for name in _BIOSTAR_OPTIONAL)
        if not any(required.values()) and not any(optional):
            return None
        if not all(required.values()):
            raise ValueError(
                "Incomplete BioStar settings; set TIQR_BIOSTAR_BASE_URL, USERNAME, PASSWORD "
                "and DEVICE_IDS"
            )
        return cls(
            base_url=required["BASE_URL"],
            username=required["USERNAME"],
            password=required["PASSWORD"],
            device_ids=_device_ids(required["DEVICE_IDS"]),
            access_group_id=_biostar_value(environment, "ACCESS_GROUP_ID"),
            verify_tls=_biostar_flag(environment, "VERIFY_TLS", default=False),
            timeout=float(_biostar_value(environment, "TIMEOUT", "30")),
            user_id_base=int(_biostar_value(environment, "USER_ID_BASE", "1000000")),
            door_open_duration=int(_biostar_value(environment, "DOOR_OPEN_DURATION", "3")),
            door_open_timeout=int(_biostar_value(environment, "DOOR_OPEN_TIMEOUT", "10")),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    secret_key: str
    database_path: Path = Path("tiqr.db")
    output_dir: Path = Path("out")
    default_tz: str = "UTC"
    prefix: str = DEFAULT_PREFIX
    biostar: BioStarSettings | None = None

    def __post_init__(self) -> None:
        validate_secret(self.secret_key)
        validate_prefix(self.prefix)
        ZoneInfo(self.default_tz)

    @classmethod
    def from_env(cls) -> Settings:
        environment = _environment()
        biostar = BioStarSettings.from_env(environment)
        # Production sets this so a missing BioStar block fails loudly.
        if _biostar_flag(environment, "REQUIRED", default=False) and biostar is None:
            raise ValueError("TIQR_BIOSTAR_REQUIRED is true but BioStar is not configured")
        return cls(
            secret_key=environment.get("TIQR_SECRET_KEY", ""),
            database_path=database_path(environment),
            output_dir=PROJECT_ROOT / environment.get("TIQR_OUT", "out"),
            default_tz=_default_timezone(environment),
            prefix=_prefix(environment),
            biostar=biostar,
        )
