from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime

from tiqr.core.models import RawEvent, SyncCursor, Ticket, utc
from tiqr.core.ports import EventSource, Registrar


class InMemoryRegistrar(Registrar):
    def __init__(self) -> None:
        self.tickets: dict[str, Ticket] = {}
        self.windows: dict[str, tuple[datetime, datetime]] = {}
        self.deactivated: list[str] = []
        self.removed: list[str] = []

    def register(self, ticket: Ticket) -> str:
        external_id = str(ticket.id)
        self.tickets[external_id] = replace(ticket, external_id=external_id)
        self.windows[external_id] = (ticket.valid_from, ticket.valid_until)
        return external_id

    def set_window(self, external_id: str, start: datetime, end: datetime) -> None:
        self.windows[external_id] = (utc(start), utc(end))

    def deactivate(self, external_id: str) -> None:
        if external_id not in self.deactivated:
            self.deactivated.append(external_id)

    def remove(self, external_id: str) -> None:
        if external_id not in self.removed:
            self.removed.append(external_id)
        self.tickets.pop(external_id, None)
        self.windows.pop(external_id, None)


class InMemoryEventSource(EventSource):
    def __init__(self, events: Iterable[RawEvent] = ()) -> None:
        self.events = list(events)
        self.cursors: list[SyncCursor | None] = []

    def fetch_events(self, cursor: SyncCursor | None) -> tuple[list[RawEvent], SyncCursor]:
        self.cursors.append(cursor)
        return list(self.events), SyncCursor(str(len(self.events)))
