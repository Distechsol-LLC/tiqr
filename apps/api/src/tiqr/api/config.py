"""How `tiqr serve` listens and what it runs, from TIQR_* variables and command-line overrides."""

from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

from tiqr.core import settings

_LOOPBACK_NAMES = frozenset({"localhost"})
_HOST = "127.0.0.1"
_PORT = 7102
_SYNC_INTERVAL = 60
_CLEANUP_INTERVAL = 3600


def _value(environment: Mapping[str, str], name: str) -> str:
    # Blank means "not set", as for every TIQR_* variable.
    return environment.get(f"TIQR_{name}", "").strip()


def _number(environment: Mapping[str, str], name: str, default: int) -> int:
    value = _value(environment, name)
    try:
        return int(value) if value else default
    except ValueError as exc:
        raise ValueError(f"TIQR_{name} must be a whole number") from exc


def _flag(environment: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = _value(environment, name).lower() or str(default).lower()
    if value not in ("true", "false"):
        raise ValueError(f"TIQR_{name} must be true or false")
    return value == "true"


def _path(environment: Mapping[str, str], name: str) -> Path | None:
    value = _value(environment, name)
    # Relative paths follow TIQR_DB and TIQR_OUT: against the project root, not the directory.
    return settings.PROJECT_ROOT / value if value else None


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = _HOST
    port: int = _PORT
    # Optional: the app runs on the customer's own network, so plain HTTP is the default.
    tls_cert: Path | None = None
    tls_key: Path | None = None
    # Development only: loopback, and the interactive API docs.
    dev: bool = False
    # Whether operators may print on the server's own default printer, besides downloading.
    server_printing: bool = False
    # Seconds between scheduled runs; 0 turns that job off.
    sync_interval: int = _SYNC_INTERVAL
    cleanup_interval: int = _CLEANUP_INTERVAL

    def __post_init__(self) -> None:
        if not 0 < self.port < 65536:  # noqa: PLR2004 - the TCP port range
            raise ValueError("TIQR_PORT must be between 1 and 65535")
        if (self.tls_cert is None) != (self.tls_key is None):
            raise ValueError("Set both TIQR_TLS_CERT and TIQR_TLS_KEY, or neither")
        # The docs describe every endpoint, so they never face the network.
        if self.dev and not _is_loopback(self.host):
            raise ValueError("--dev only listens on a loopback address, such as 127.0.0.1")
        if self.sync_interval < 0 or self.cleanup_interval < 0:
            raise ValueError("Sync and cleanup intervals must not be negative")

    @property
    def secure(self) -> bool:
        return self.tls_cert is not None

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        tls_cert: Path | None = None,
        tls_key: Path | None = None,
        dev: bool = False,
    ) -> ServerConfig:
        """Read TIQR_* settings; arguments that are given win over them."""
        environment = settings.load_environment() if environment is None else environment
        return cls(
            host=host or _value(environment, "HOST") or _HOST,
            port=port or _number(environment, "PORT", _PORT),
            tls_cert=tls_cert or _path(environment, "TLS_CERT"),
            tls_key=tls_key or _path(environment, "TLS_KEY"),
            dev=dev,
            server_printing=_flag(environment, "SERVER_PRINTING", default=False),
            sync_interval=_number(environment, "SYNC_INTERVAL", _SYNC_INTERVAL),
            cleanup_interval=_number(environment, "CLEANUP_INTERVAL", _CLEANUP_INTERVAL),
        )
