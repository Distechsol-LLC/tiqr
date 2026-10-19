"""What a running server holds open: settings, the service, and the way it prints."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tiqr.core.printer import send_to_printer
from tiqr.core.runtime import open_service
from tiqr.core.service import TicketService
from tiqr.core.settings import Settings


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    service: TicketService
    printer: Callable[[Path], None] = send_to_printer


@contextmanager
def open_runtime() -> Generator[Runtime]:
    """Read the settings and open the service for the life of the server."""
    settings = Settings.from_env()
    with open_service(settings) as service:
        yield Runtime(settings, service)
