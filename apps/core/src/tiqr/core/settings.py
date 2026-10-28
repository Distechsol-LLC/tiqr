import json
import os
import re
import secrets
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

from tiqr.core.languages import DEFAULT_LANGUAGES, currencies_for, parse_languages
from tiqr.core.models import Currency
from tiqr.core.qr import DEFAULT_PREFIX, validate_prefix


def _project_root() -> Path:
    # An installed service sets TIQR_HOME, so config and data stay put while release folders
    # change. It must be a real environment variable: the .env files are found through it.
    home = os.environ.get("TIQR_HOME", "").strip()
    if home:
        return Path(home).expanduser().resolve()
    # A frozen build unpacks into a temporary directory, so config and data sit beside the
    # executable. Installed programs sit where the service account cannot write, so they keep
    # config and data in ProgramData on Windows and /var/lib on Linux instead. Source checkouts
    # keep them at the workspace root, never in the working directory: this file is
    # apps/core/src/tiqr/core/settings.py under that root.
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "TiQR"
        if sys.platform.startswith("linux"):
            return Path("/var/lib/tiqr")
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[5]


PROJECT_ROOT = _project_root()
# Later files override earlier ones; real environment variables override both.
LOCAL_ENV_FILE = ".env.local"
ENV_FILES = (".env", LOCAL_ENV_FILE)
# Name, logo, theme and languages. Required beside the executable: the program does not run without.
BRANDING_FILE = "tiqr_brand.jsonc"
SESSION_FILE = ".tiqr-session.json"
# Fixed names, beside the executable: not settings, so nothing can point them elsewhere.
DATABASE_FILE = "tiqr.db"
OUTPUT_DIR = "out"

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
DEFAULT_APP_NAME = "TiQR"
DEFAULT_THEME = "default"
LOGO_SUFFIXES = frozenset({".png", ".svg", ".jpg", ".jpeg"})
_THEME_NAME = re.compile(r"[a-z][a-z0-9-]*")
_BIOSTAR_REQUIRED = ("BASE_URL", "USERNAME", "PASSWORD", "DEVICE_IDS")
_BIOSTAR_OPTIONAL = (
    "ACCESS_GROUP_ID",
    "VERIFY_TLS",
    "TIMEOUT",
    "DOOR_OPEN_DURATION",
    "DOOR_OPEN_TIMEOUT",
)


_JSONC_TOKEN = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)
_TRAILING_COMMA = re.compile(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])')
_BRANDING_KEYS = frozenset({"app_name", "logo_path", "theme", "languages"})
# The rest of the file's keys are the TIQR_* settings of the same name. The signing key and the
# BioStar password are not among them: those stay in .env.local, out of a file that gets shared.
_SETTING_KEYS = frozenset(
    {"prefix", "default_tz", "host", "port", "tls_cert", "tls_key", "server_printing"}
)
_BIOSTAR_KEYS = frozenset(
    {
        "base_url",
        "username",
        "device_ids",
        "access_group_id",
        "verify_tls",
        "timeout",
        "door_open_duration",
        "door_open_timeout",
    }
)


def _jsonc_loads(text: str) -> object:
    """Parse JSON that may carry // and /* */ comments and trailing commas."""
    text = _JSONC_TOKEN.sub(lambda match: match[1] or " ", text)
    return json.loads(_TRAILING_COMMA.sub(lambda match: match[1] or "", text))


def load_branding(path: Path | None = None) -> dict[str, object]:
    """Read tiqr_brand.jsonc, which must sit under the project root."""
    path = path or PROJECT_ROOT / BRANDING_FILE
    if not path.is_file():
        raise ValueError(f"{BRANDING_FILE} is missing; place it beside the program ({path})")
    try:
        data = _jsonc_loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{BRANDING_FILE} is not valid JSONC: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{BRANDING_FILE} must hold a JSON object")  # noqa: TRY004 - ValueErrors
    data = cast("dict[str, object]", data)
    biostar = data.get("biostar")
    if biostar is not None and not isinstance(biostar, dict):
        raise ValueError(f"{BRANDING_FILE}: biostar must be an object")
    biostar_keys = cast("dict[str, object]", biostar or {})
    unknown = sorted(
        {*data, *(f"biostar.{key}" for key in biostar_keys)}
        - _BRANDING_KEYS
        - _SETTING_KEYS
        - {"biostar"}
        - {f"biostar.{key}" for key in _BIOSTAR_KEYS}
    )
    missing = sorted(_BRANDING_KEYS - {"logo_path"} - set(data))
    if unknown or missing:
        raise ValueError(
            f"{BRANDING_FILE} "
            + "; ".join(
                part
                for part in (
                    f"has unknown keys {', '.join(unknown)}" if unknown else "",
                    f"is missing {', '.join(missing)}" if missing else "",
                )
                if part
            )
        )
    return data


def _setting_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return ",".join(str(item) for item in cast("list[object]", value))
    return str(value)


def _file_settings(data: Mapping[str, object]) -> dict[str, str]:
    """The non-branding keys of tiqr_brand.jsonc as TIQR_* values; null leaves one unset."""
    biostar = data.get("biostar")
    block: Mapping[str, object] = (
        cast("Mapping[str, object]", biostar) if isinstance(biostar, dict) else {}
    )
    keys = {
        **{f"TIQR_{key.upper()}": data.get(key) for key in _SETTING_KEYS},
        **{f"TIQR_BIOSTAR_{key.upper()}": block.get(key) for key in _BIOSTAR_KEYS},
    }
    return {key: text for key, value in keys.items() if (text := _setting_text(value)) is not None}


def load_environment() -> dict[str, str]:
    """The .env files, then tiqr_brand.jsonc, overridden by the real environment."""
    values: dict[str, str] = {}
    for name in ENV_FILES:
        values.update(
            (key, value)
            for key, value in dotenv_values(PROJECT_ROOT / name).items()
            if value is not None
        )
    values.update(_file_settings(load_branding()))
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


def write_local_settings(values: Mapping[str, str], path: Path | None = None) -> bool:
    """Set each KEY=value in the local env file, adding keys it lacks; report whether it changed."""
    path = path or PROJECT_ROOT / LOCAL_ENV_FILE

    def edit(lines: list[str]) -> list[str]:
        header = "# Private values. Git-ignored; overrides .env. Real environment variables win."
        updated = list(lines or [header])
        for key, value in values.items():
            entry = f"{key}={value}"
            if any(line.startswith(f"{key}=") for line in updated):
                updated = [entry if line.startswith(f"{key}=") else line for line in updated]
            else:
                updated.append(entry)
        return updated

    return _edit_local_file(path, edit)


def discard_access_group_id(path: Path | None = None) -> bool:
    """Blank the pinned BioStar access group so setup manages it again."""
    path = path or PROJECT_ROOT / LOCAL_ENV_FILE
    key = "TIQR_BIOSTAR_ACCESS_GROUP_ID="
    return _edit_local_file(
        path, lambda lines: [key if line.startswith(key) else line for line in lines]
    )


def database_path() -> Path:
    """The database's location, which needs no valid signing key to find."""
    return PROJECT_ROOT / DATABASE_FILE


def session_path() -> Path:
    """Where the CLI keeps its recent login."""
    return PROJECT_ROOT / SESSION_FILE


def branding_path() -> Path:
    """Where the server reads tiqr_brand.jsonc: TIQR_HOME when it is set."""
    return PROJECT_ROOT / BRANDING_FILE


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


def _branding_text(branding: Mapping[str, object], key: str) -> str:
    value = branding.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{BRANDING_FILE}: {key} must be text")  # noqa: TRY004
    return value.strip()


def _logo_path(branding: Mapping[str, object]) -> Path | None:
    value = branding.get("logo_path")
    if value is None or value == "":
        return None
    # Relative paths are against the project root.
    return PROJECT_ROOT / _branding_text(branding, "logo_path")


def _branding_languages(branding: Mapping[str, object]) -> tuple[str, ...]:
    value = branding.get("languages")
    if value is None:
        return DEFAULT_LANGUAGES
    if not isinstance(value, list):
        raise ValueError(f"{BRANDING_FILE}: languages must be a list of codes such as en-US")  # noqa: TRY004
    codes = cast("list[object]", value)
    if not all(isinstance(code, str) for code in codes):
        raise ValueError(f"{BRANDING_FILE}: languages must be a list of codes such as en-US")
    return parse_languages(cast("list[str]", codes))


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
        if self.timeout <= 0:
            raise ValueError("BioStar timeout must be positive")
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
            door_open_duration=int(_biostar_value(environment, "DOOR_OPEN_DURATION", "3")),
            door_open_timeout=int(_biostar_value(environment, "DOOR_OPEN_TIMEOUT", "10")),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    secret_key: str
    database_path: Path = Path(DATABASE_FILE)
    output_dir: Path = Path(OUTPUT_DIR)
    default_tz: str = "UTC"
    prefix: str = DEFAULT_PREFIX
    biostar: BioStarSettings | None = None
    app_name: str = DEFAULT_APP_NAME
    logo_path: Path | None = None
    theme: str = DEFAULT_THEME
    languages: tuple[str, ...] = DEFAULT_LANGUAGES

    def __post_init__(self) -> None:
        validate_secret(self.secret_key)
        validate_prefix(self.prefix)
        ZoneInfo(self.default_tz)
        if not self.app_name.strip():
            raise ValueError("app_name must not be blank")
        if _THEME_NAME.fullmatch(self.theme) is None:
            raise ValueError("theme must be lowercase letters, digits and dashes")
        if not self.languages or self.languages != parse_languages(self.languages):
            raise ValueError("languages must list each language once, such as en-US, az-AZ")
        if self.logo_path is not None:
            if self.logo_path.suffix.lower() not in LOGO_SUFFIXES:
                raise ValueError("logo_path must be a PNG, SVG or JPG image")
            if not self.logo_path.is_file():
                raise ValueError(f"logo_path does not exist: {self.logo_path}")

    @property
    def currencies(self) -> tuple[Currency, ...]:
        """What prices may be in: the currency of each language's region."""
        return currencies_for(self.languages)

    @classmethod
    def from_env(cls) -> Settings:
        environment = load_environment()
        biostar = BioStarSettings.from_env(environment)
        # Production sets this so a missing BioStar block fails loudly.
        if _biostar_flag(environment, "REQUIRED", default=False) and biostar is None:
            raise ValueError("TIQR_BIOSTAR_REQUIRED is true but BioStar is not configured")
        branding = load_branding()
        return cls(
            secret_key=environment.get("TIQR_SECRET_KEY", ""),
            database_path=database_path(),
            output_dir=PROJECT_ROOT / OUTPUT_DIR,
            default_tz=_default_timezone(environment),
            prefix=_prefix(environment),
            biostar=biostar,
            app_name=_branding_text(branding, "app_name"),
            logo_path=_logo_path(branding),
            theme=_branding_text(branding, "theme").lower(),
            languages=_branding_languages(branding),
        )
