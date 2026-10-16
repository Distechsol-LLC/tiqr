"""Wire settings into a ready service: the database, and BioStar or the in-memory fakes."""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from tiqr.core.biostar import BioStarClient, BioStarXEventSource, BioStarXRegistrar
from tiqr.core.ports import EventSource, Registrar
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService
from tiqr.core.settings import Settings


@contextmanager
def open_service(settings: Settings) -> Generator[TicketService]:
    """Open the database and adapters `settings` names, then close them afterwards."""
    with ExitStack() as stack:
        repository = stack.enter_context(SQLiteRepository(settings.database_path))
        repository.initialize()
        registrar: Registrar | None = None
        event_source: EventSource | None = None
        if settings.biostar is not None:
            client = BioStarClient(settings.biostar)
            stack.callback(client.close)
            registrar = BioStarXRegistrar(client, repository)
            event_source = BioStarXEventSource(client, repository)
        yield TicketService(
            repository,
            settings.secret_key,
            registrar=registrar,
            event_source=event_source,
            prefix=settings.prefix,
        )
