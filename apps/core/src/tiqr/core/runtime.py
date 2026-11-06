"""Wire settings into a ready service: the database, and BioStar or the in-memory fakes."""

from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager

from tiqr.core.biostar import BioStarClient, BioStarXEventSource, BioStarXRegistrar
from tiqr.core.models import Mode
from tiqr.core.ports import EventSource, Registrar
from tiqr.core.service import BioStarLink, ModeSwitch, TicketService
from tiqr.core.settings import DATABASE_FILES, Settings, adopt_legacy_database, write_mode


@contextmanager
def open_service(
    settings: Settings, save_mode: Callable[[Mode], object] | None = write_mode
) -> Generator[TicketService]:
    """Open the database and adapters `settings` names, then close them afterwards.

    The other mode's database sits beside the active one and opens on the first switch to it;
    `save_mode` records a switch for the next start (None keeps it to this run).
    """
    with ExitStack() as stack:
        adopt_legacy_database(settings.database_path.parent)
        paths = {
            mode: settings.database_path
            if mode == settings.mode
            else settings.database_path.with_name(DATABASE_FILES[mode])
            for mode in Mode
        }
        switch = ModeSwitch(paths, save_mode)
        stack.callback(switch.close)
        repository = switch.open(settings.mode)
        registrar: Registrar | None = None
        event_source: EventSource | None = None
        link = BioStarLink(settings.biostar)
        # The link closes whichever client is current, including one swapped in later.
        stack.callback(link.close)
        if settings.biostar is not None:
            link.client = BioStarClient(settings.biostar)
            registrar = BioStarXRegistrar(link.client, repository)
            event_source = BioStarXEventSource(link.client, repository)
        service = TicketService(
            repository,
            settings.secret_key,
            registrar=registrar,
            event_source=event_source,
            prefix=settings.prefix,
            timezone=settings.default_tz,
            mode=settings.mode,
        )
        link.service = service
        service.biostar_link = link
        switch.service = service
        service.mode_switch = switch
        yield service
