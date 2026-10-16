"""BioStar X HTTP, registration, and polling adapters.

Polling overlaps the persisted upper bound by 15 minutes to catch delayed scans. Saturated ranges
are split; a saturated one-second range fails closed because event offsets are undocumented.
"""

import json
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from types import TracebackType
from typing import Self, TypeIs, cast
from urllib.parse import quote

import httpx2

from tiqr.core.models import RawEvent, Registration, SyncCursor, Ticket, utc
from tiqr.core.ports import Clock, EventSource, Registrar, Repository
from tiqr.core.qr import PAYLOAD_LENGTH
from tiqr.core.settings import BioStarSettings

type JsonObject = dict[str, object]
type QueryParams = Mapping[str, str | int]

SESSION_HEADER = "bs-session-id"
CARD_PAGE_SIZE = 500
# Names of the objects TiQR owns in BioStar; doors are the plain name plus the device ID.
ACCESS_NAME = "TiQR"
ACCESS_GROUP_NAME = "TiQR AG"
ACCESS_LEVEL_NAME = "TiQR AL"
_ROOT_DOOR_GROUP_ID = 1
_ALWAYS_SCHEDULE_ID = "1"
_GRANTED_PREFIXES = ("VERIFY_SUCCESS", "IDENTIFY_SUCCESS", "ACCESS_GRANTED", "DUAL_AUTH_SUCCESS")
_DENIED_PREFIXES = (
    "VERIFY_FAIL",
    "IDENTIFY_FAIL",
    "ACCESS_DENIED",
    "AUTH_FAILED",
    "DUAL_AUTH_FAIL",
)


class BioStarError(RuntimeError):
    def __init__(
        self, message: str, *, code: str | None = None, http_status: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def to_biostar_datetime(value: datetime) -> str:
    return utc(value).strftime("%Y-%m-%dT%H:%M:%S.00Z")


def _datetime(value: object) -> datetime:
    if isinstance(value, str):
        with suppress(ValueError):
            return utc(datetime.fromisoformat(value))
    raise BioStarError("Missing or invalid timezone-aware scan/cursor datetime")


def _is_json_object(value: object) -> TypeIs[JsonObject]:
    return isinstance(value, dict)


def _is_json_object_list(value: object) -> TypeIs[list[JsonObject]]:
    return isinstance(value, list) and all(
        _is_json_object(row) for row in cast(list[object], value)
    )


def _identifier(value: object) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
        return str(value)
    return None


def _required_identifier(value: object, error: str) -> str:
    identifier = _identifier(value)
    if identifier is None:
        raise BioStarError(error)
    return identifier


def _entity(collection: str, identifier: str) -> str:
    return f"{collection}/{quote(identifier, safe='')}"


def _related_id(value: object) -> str | None:
    if _is_json_object(value):
        value = value.get("user_id") or value.get("id") or value.get("code")
    return _identifier(value)


def _object_list(value: object) -> list[JsonObject]:
    return (
        [row for row in cast(list[object], value) if _is_json_object(row)]
        if isinstance(value, list)
        else []
    )


def _has_collection(payload: JsonObject) -> bool:
    return any(isinstance(value, dict) and "rows" in value for value in payload.values())


def _json_type(text: str) -> str:
    try:
        return type(json.loads(text)).__name__
    except ValueError:
        return "invalid"


def _shape(collection: JsonObject) -> str:
    """Types and sizes only; row values carry personal data and must never be logged."""
    rows = collection["rows"]
    element_types = (
        sorted({type(row).__name__ for row in cast(list[object], rows)})
        if isinstance(rows, list)
        else []
    )
    text = f" length={len(rows)} json={_json_type(rows)}" if isinstance(rows, str) else ""
    rows_type = type(cast(object, rows)).__name__
    return f"keys={sorted(collection)} rows={rows_type}{text} elements={element_types}"


def _rows(payload: JsonObject) -> list[JsonObject]:
    collections = [
        value
        for key, value in payload.items()
        if key != "Response" and _is_json_object(value) and "rows" in value
    ]
    match collections:
        case [{"rows": object() as rows}] if _is_json_object_list(rows):
            return rows
        # BioStar answers an empty result with an empty string, not an empty list.
        case [{"rows": ""}]:
            return []
        case [collection]:
            raise BioStarError(f"Malformed BioStar collection rows: {_shape(collection)}")
        case _:
            raise BioStarError("Missing or ambiguous BioStar collection")


class BioStarClient:
    def __init__(
        self, settings: BioStarSettings, *, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        base = settings.base_url.rstrip("/").removesuffix("/api")
        self._http = httpx2.Client(
            base_url=f"{base}/api/",
            verify=settings.verify_tls,
            timeout=settings.timeout,
            transport=transport,
        )
        self._session_id: str | None = None
        self._access_group_id = settings.access_group_id or None
        self._lock = threading.RLock()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def _send(
        self, method: str, path: str, *, json: object = None, params: QueryParams | None = None
    ) -> httpx2.Response:
        path = path.strip("/").removeprefix("api/")
        headers = {SESSION_HEADER: self._session_id} if self._session_id else {}
        try:
            return self._http.request(method, path, json=json, params=params, headers=headers)
        except httpx2.HTTPError as exc:
            raise BioStarError("BioStar transport request failed") from exc

    @staticmethod
    def _decode(response: httpx2.Response) -> JsonObject:
        status = response.status_code
        try:
            payload = response.json()
        except ValueError as exc:
            raise BioStarError("BioStar response is not JSON", http_status=status) from exc
        if not _is_json_object(payload) or not _is_json_object(envelope := payload.get("Response")):
            raise BioStarError("Missing BioStar Response envelope", http_status=status)
        code = _identifier(envelope.get("code"))
        message = envelope.get("message")
        if code is None or not code.isdigit() or not isinstance(message, str):
            raise BioStarError("Malformed BioStar Response envelope", http_status=status)
        if code != "0":
            raise BioStarError(message, code=code, http_status=status)
        if not response.is_success:
            raise BioStarError("BioStar HTTP request failed", code=code, http_status=status)
        return payload

    def login(self) -> str:
        with self._lock:
            self._session_id = None
            response = self._send(
                "POST",
                "login",
                json={
                    "User": {"login_id": self.settings.username, "password": self.settings.password}
                },
            )
            self._decode(response)
            session_id = _identifier(response.headers.get(SESSION_HEADER))
            if session_id is None:
                raise BioStarError(
                    f"BioStar login did not return {SESSION_HEADER}",
                    http_status=response.status_code,
                )
            self._session_id = session_id
            return session_id

    def request(
        self, method: str, path: str, *, json: object = None, params: QueryParams | None = None
    ) -> JsonObject:
        with self._lock:
            if self._session_id is None:
                self.login()
            response = self._send(method, path, json=json, params=params)
            if response.status_code == HTTPStatus.UNAUTHORIZED:
                self.login()
                response = self._send(method, path, json=json, params=params)
            return self._decode(response)

    def access_group_id(self) -> str:
        """The configured access group, else the TiQR-managed one found by name."""
        with self._lock:
            if self._access_group_id is None:
                group = self.find_named(self.search_access_groups(), ACCESS_GROUP_NAME)
                if group is None:
                    raise BioStarError(
                        f"BioStar access group {ACCESS_GROUP_NAME} not found;"
                        " run `tiqr setup` first"
                    )
                self._access_group_id = _required_identifier(
                    group.get("id"), "Access group has no ID"
                )
            return self._access_group_id

    @staticmethod
    def find_named(rows: list[JsonObject], name: str) -> JsonObject | None:
        matches = [row for row in rows if row.get("name") == name]
        if len(matches) > 1:
            raise BioStarError(f"Several BioStar objects are named {name}")
        return matches[0] if matches else None

    def search_access_groups(self) -> list[JsonObject]:
        return _rows(
            self.request(
                "POST", "v2/access_groups/search", json={"limit": 0, "order_by": "id:false"}
            )
        )

    def list_access_levels(self) -> list[JsonObject]:
        return _rows(
            self.request(
                "GET", "access_levels", params={"limit": 0, "offset": 0, "order_by": "id:false"}
            )
        )

    def search_doors(self, name: str) -> list[JsonObject]:
        return _rows(
            self.request(
                "POST",
                "v2/doors/search",
                json={"limit": 0, "search_text": name, "order_by": "id:false"},
            )
        )

    def create_user(self, external_id: str, ticket: Ticket) -> None:
        self.request(
            "POST",
            "users",
            json={
                "User": {
                    "user_id": external_id,
                    "name": ticket.visitor_name,
                    "user_group_id": {"id": "1"},
                    "disabled": "false",
                    "start_datetime": to_biostar_datetime(ticket.valid_from),
                    "expiry_datetime": to_biostar_datetime(ticket.valid_until),
                    "access_groups": [{"id": self.access_group_id()}],
                }
            },
        )

    def update_user(self, external_id: str, fields: JsonObject) -> None:
        self.request("PUT", _entity("users", external_id), json={"User": fields})

    def search_users(self) -> list[JsonObject]:
        return _rows(
            self.request(
                "POST",
                "v2/users/search",
                json={"limit": 0, "search_text": None, "order_by": "user_id:false"},
            )
        )

    def delete_user(self, external_id: str) -> None:
        self.request("DELETE", "users", params={"id": external_id})

    def find_card(self, card_id: str) -> JsonObject | None:
        payload = self.request("GET", "v2/cards/registered", params={"card_id": card_id})
        if _is_json_object(card := payload.get("Card")):
            return card or None
        rows = _rows(payload)
        if len(rows) > 1:
            raise BioStarError("Ambiguous registered card response")
        return rows[0] if rows else None

    def create_qr_card(self, card_id: str) -> str:
        if len(card_id) != PAYLOAD_LENGTH:
            raise ValueError(
                f"The ticket QR payload must contain exactly {PAYLOAD_LENGTH} characters"
            )
        payload = self.request(
            "POST",
            "cards",
            json={
                "CardCollection": {
                    "rows": [{"card_id": card_id, "card_type": {"id": "6", "type": "6"}}]
                }
            },
        )
        # BioStar versions disagree on where the new ID lives.
        internal_id = _identifier(payload.get("id"))
        if internal_id is None and _is_json_object(card := payload.get("Card")):
            internal_id = _identifier(card.get("id"))
        if internal_id is None and _has_collection(payload):
            rows = _rows(payload)
            if len(rows) == 1:
                internal_id = _identifier(rows[0].get("id"))
        if internal_id is None:
            found = self.find_card(card_id)
            internal_id = _identifier(found.get("id")) if found else None
        if internal_id is None:
            raise BioStarError("Created QR card has no internal ID")
        return internal_id

    def list_cards(self, *, limit: int = CARD_PAGE_SIZE, offset: int = 0) -> list[JsonObject]:
        return _rows(self.request("GET", "cards", params={"limit": limit, "offset": offset}))

    def delete_card(self, internal_id: str) -> None:
        self.request("DELETE", "cards", params={"id": internal_id})

    def list_event_types(self) -> list[JsonObject]:
        return _rows(
            self.request(
                "GET",
                "event_types",
                params={"is_break_glass": "false", "setting_alert": "false", "setting_all": "true"},
            )
        )

    def search_events(
        self, since: datetime, until: datetime, *, limit: int, device_id: str
    ) -> list[JsonObject]:
        return _rows(
            self.request(
                "POST",
                "events/search",
                json={
                    "Query": {
                        "limit": limit,
                        "conditions": [
                            {
                                "column": "datetime",
                                "operator": 3,
                                "values": [to_biostar_datetime(since), to_biostar_datetime(until)],
                            },
                            {"column": "device_id", "operator": 0, "values": [device_id]},
                        ],
                        "orders": [{"column": "datetime", "descending": False}],
                    }
                },
            )
        )


class BioStarXProvisioner:
    """Create the TiQR access group, its access level, and one door per reader.

    Each object is looked up by name first, so reruns only fill gaps. A configured
    TIQR_BIOSTAR_ACCESS_GROUP_ID is verified, never modified.
    """

    def __init__(self, client: BioStarClient) -> None:
        self.client = client

    def ensure_access(self) -> str:
        settings = self.client.settings
        if settings.access_group_id:
            self.client.request("GET", _entity("access_groups", settings.access_group_id))
            return settings.access_group_id
        doors = [self._ensure_door(device_id) for device_id in settings.device_ids]
        return self._ensure_group(self._ensure_level(doors))

    @staticmethod
    def _created_or_found(
        payload: JsonObject, key: str, find: Callable[[], JsonObject | None], error: str
    ) -> str:
        created = payload.get(key)
        created_id = _identifier(created.get("id")) if _is_json_object(created) else None
        # Some BioStar versions omit the new ID from the create response.
        if created_id is None and (found := find()):
            created_id = _identifier(found.get("id"))
        return _required_identifier(created_id, error)

    def _find_door(self, name: str) -> JsonObject | None:
        return self.client.find_named(self.client.search_doors(name), name)

    def _find_level(self) -> JsonObject | None:
        return self.client.find_named(self.client.list_access_levels(), ACCESS_LEVEL_NAME)

    def _find_group(self) -> JsonObject | None:
        return self.client.find_named(self.client.search_access_groups(), ACCESS_GROUP_NAME)

    def _ensure_door(self, device_id: str) -> str:
        name = f"{ACCESS_NAME} {device_id}"
        if existing := self._find_door(name):
            return _required_identifier(existing.get("id"), "Door has no ID")
        device = {"id": int(device_id)}
        payload = self.client.request(
            "POST",
            "doors",
            json={
                "Door": {
                    "name": name,
                    "description": "Managed by TiQR",
                    "door_group_id": {"id": _ROOT_DOOR_GROUP_ID},
                    # Omitting the unlock time leaves a door the reader may not accept.
                    "open_duration": self.client.settings.door_open_duration,
                    "open_timeout": self.client.settings.door_open_timeout,
                    "entry_device_id": device,
                    "relay_output_id": {"device_id": device, "relay_index": 0},
                    "exit_button_input_id": {"device_id": device, "input_index": 0, "type": "1"},
                    "sensor_input_id": {
                        "device_id": device,
                        "input_index": 1,
                        "type": "1",
                        "apb_use_door_sensor": "1",
                    },
                }
            },
        )
        return self._created_or_found(
            payload, "Door", lambda: self._find_door(name), "Created door has no ID"
        )

    def _ensure_level(self, door_ids: list[str]) -> str:
        """Create the level, or realign its doors with the configured devices."""

        def items(item_id: str | None) -> list[JsonObject]:
            item: JsonObject = {
                "doors": [{"id": door_id} for door_id in door_ids],
                "schedule_id": {"id": _ALWAYS_SCHEDULE_ID},
            }
            return [{"id": item_id, **item} if item_id else item]

        level = self._find_level()
        if level is None:
            payload = self.client.request(
                "POST",
                "access_levels",
                json={
                    "AccessLevel": {
                        "name": ACCESS_LEVEL_NAME,
                        "description": "Managed by TiQR",
                        "access_level_items": items(None),
                    }
                },
            )
            return self._created_or_found(
                payload, "AccessLevel", self._find_level, "Created access level has no ID"
            )
        level_id = _required_identifier(level.get("id"), "Access level has no ID")
        current = _object_list(level.get("access_level_items"))
        have = {
            _identifier(door.get("id"))
            for item in current
            for door in _object_list(item.get("doors"))
        }
        if have != set(door_ids):
            item_id = _identifier(current[0].get("id")) if len(current) == 1 else None
            self.client.request(
                "PUT",
                _entity("access_levels", level_id),
                json={
                    "AccessLevel": {
                        "name": ACCESS_LEVEL_NAME,
                        "description": "Managed by TiQR",
                        "access_level_items": items(item_id),
                    }
                },
            )
        return level_id

    def _ensure_group(self, level_id: str) -> str:
        group = self._find_group()
        if group is None:
            payload = self.client.request(
                "POST",
                "access_groups",
                json={
                    "AccessGroup": {
                        "name": ACCESS_GROUP_NAME,
                        "description": "Managed by TiQR",
                        "access_levels": [{"id": level_id}],
                    }
                },
            )
            return self._created_or_found(
                payload, "AccessGroup", self._find_group, "Created access group has no ID"
            )
        group_id = _required_identifier(group.get("id"), "Access group has no ID")
        levels = [
            _identifier(level.get("id")) for level in _object_list(group.get("access_levels"))
        ]
        if level_id not in levels:
            self.client.request(
                "PUT",
                _entity("access_groups", group_id),
                json={
                    "AccessGroup": {
                        "name": ACCESS_GROUP_NAME,
                        "access_levels": [{"id": other} for other in (*levels, level_id) if other],
                    }
                },
            )
        return group_id


class BioStarXRegistrar(Registrar):
    def __init__(self, client: BioStarClient, repository: Repository) -> None:
        self.client = client
        self.repository = repository

    def register(self, ticket: Ticket) -> str:
        external_id = str(
            self.repository.allocate("biostar_user_id", self.client.settings.user_id_base)
        )
        self.client.create_user(external_id, ticket)
        registration = Registration(external_id, "", card_removed=True)
        try:
            self.repository.save_registration(registration)
            registration = replace(registration, card_removed=False)
            self.repository.save_registration(registration)
            card_id = self.client.create_qr_card(ticket.qr_payload)
            registration = replace(registration, card_id=card_id)
            self.repository.save_registration(registration)
            self.client.update_user(external_id, {"cards": [{"id": card_id}]})
        except Exception as primary:
            try:
                self._cleanup(registration, qr_payload=ticket.qr_payload)
            except Exception as cleanup:  # noqa: BLE001 - the original error is re-raised
                primary.add_note(f"BioStar registration rollback failed: {cleanup}")
            raise
        return external_id

    def set_window(self, external_id: str, start: datetime, end: datetime) -> None:
        start, end = utc(start), utc(end)
        if end < start:
            raise ValueError("Access window ends before it starts")
        self.client.update_user(
            external_id,
            {
                "start_datetime": to_biostar_datetime(start),
                "expiry_datetime": to_biostar_datetime(end),
            },
        )

    def deactivate(self, external_id: str) -> None:
        self.client.update_user(external_id, {"disabled": "true"})

    def _user_exists(self, external_id: str) -> bool:
        ids = {
            _required_identifier(row.get("user_id"), "User search returned a row without user_id")
            for row in self.client.search_users()
        }
        return external_id in ids

    def _card_exists(self, internal_id: str) -> bool:
        offset, seen = 0, set[str]()
        while True:
            rows = self.client.list_cards(offset=offset)
            ids = {
                _required_identifier(row.get("id"), "Card list returned a row without internal ID")
                for row in rows
            }
            if internal_id in ids:
                return True
            if len(rows) < CARD_PAGE_SIZE:
                return False
            if not seen.isdisjoint(ids):
                raise BioStarError("Card pagination did not advance")
            seen |= ids
            offset += len(rows)

    @staticmethod
    def _delete_verified(delete: Callable[[], None], exists: Callable[[], bool]) -> None:
        if not exists():
            return
        try:
            delete()
        except BioStarError:
            if exists():
                raise
            return
        if exists():
            raise BioStarError("BioStar deletion acknowledged but record still exists")

    def _find_card_id(self, external_id: str, qr_payload: str | None) -> str | None:
        """Find a card whose internal ID was never persisted."""
        if qr_payload is None:
            ticket = self.repository.ticket_by_external_id(external_id)
            qr_payload = ticket.qr_payload if ticket else None
        if qr_payload is None:
            raise BioStarError("Cannot verify pending card cleanup without its QR payload")
        card = self.client.find_card(qr_payload)
        if card is None:
            return None
        return _required_identifier(card.get("id"), "Registered card has no internal ID")

    def _cleanup(self, registration: Registration, *, qr_payload: str | None = None) -> None:
        external_id = registration.external_id
        if not registration.user_removed:
            self._delete_verified(
                lambda: self.client.delete_user(external_id), lambda: self._user_exists(external_id)
            )
            registration = replace(registration, user_removed=True)
            self.repository.save_registration(registration)
        if registration.card_removed:
            return
        if not registration.card_id and (found := self._find_card_id(external_id, qr_payload)):
            registration = replace(registration, card_id=found)
            self.repository.save_registration(registration)
        if card_id := registration.card_id:
            self._delete_verified(
                lambda: self.client.delete_card(card_id), lambda: self._card_exists(card_id)
            )
        self.repository.save_registration(replace(registration, card_removed=True))

    def remove(self, external_id: str) -> None:
        registration = self.repository.get_registration(external_id)
        if registration is None:
            raise BioStarError("No persisted BioStar registration; cleanup cannot be verified")
        self._cleanup(registration)


class BioStarXEventSource(EventSource):
    OVERLAP = timedelta(minutes=15)
    BATCH_LIMIT = 100

    def __init__(
        self,
        client: BioStarClient,
        repository: Repository | None = None,
        *,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.repository = repository
        self.clock = clock
        self._event_names: dict[str, str] | None = None

    def _load_event_names(self) -> dict[str, str]:
        names: dict[str, str] = {}
        for row in self.client.list_event_types():
            code = _identifier(row.get("code"))
            name = row.get("name") or row.get("description")
            if code is None or not code.isdigit() or not isinstance(name, str) or not name:
                raise BioStarError("Malformed BioStar event type")
            code, name = str(int(code)), name.upper()
            if names.setdefault(code, name) != name:
                raise BioStarError("Conflicting BioStar event types")
        if not names:
            raise BioStarError("Empty BioStar event type reference")
        return names

    def _normalize(self, row: JsonObject, event_names: Mapping[str, str]) -> RawEvent | None:
        event_id = _required_identifier(row.get("id"), "Scan is missing its event ID")
        occurred_at = _datetime(row.get("datetime"))
        if _related_id(row.get("device_id")) not in self.client.settings.device_ids:
            return None
        code = _related_id(row.get("event_type_id"))
        if code is None or not code.isdigit():
            raise BioStarError("Scan is missing its numeric event type")
        name = event_names.get(str(int(code)), "")
        if name.startswith(_GRANTED_PREFIXES):
            granted = True
        elif name.startswith(_DENIED_PREFIXES):
            granted = False
        else:
            return None
        return RawEvent(event_id, _related_id(row.get("user_id")), occurred_at, granted)

    def _since(self, cursor: SyncCursor | None, upper: datetime) -> datetime:
        if cursor is not None:
            try:
                previous = _datetime(json.loads(cursor.token)["until"])
            except (ValueError, TypeError, KeyError) as exc:
                raise BioStarError("Invalid BioStar sync cursor") from exc
            if previous > upper:
                raise BioStarError("BioStar cursor is ahead of the polling clock")
            since = previous - self.OVERLAP
        else:
            # A first sync reaches back to the oldest ticket.
            tickets = self.repository.list_tickets() if self.repository else []
            since = min((ticket.created_at for ticket in tickets), default=upper - self.OVERLAP)
        return min(since.replace(microsecond=0), upper)

    def fetch_events(self, cursor: SyncCursor | None) -> tuple[list[RawEvent], SyncCursor]:
        upper = utc(self.clock()).replace(microsecond=0)
        since = self._since(cursor, upper)
        event_names = self._event_names
        if event_names is None:
            event_names = self._event_names = self._load_event_names()
        pending = [(since, upper)]
        events: dict[str, RawEvent] = {}
        while pending:
            start, end = pending.pop()
            # One query per reader: the filter has no multi-value form, and saturation is
            # checked per reader.
            batches = [
                self.client.search_events(start, end, limit=self.BATCH_LIMIT, device_id=device_id)
                for device_id in self.client.settings.device_ids
            ]
            rows = [row for batch in batches for row in batch]
            if any(len(batch) >= self.BATCH_LIMIT for batch in batches):
                seconds = int((end - start).total_seconds())
                if seconds <= 1:
                    raise BioStarError(
                        "BioStar one-second event bucket is saturated; cursor unchanged"
                    )
                middle = start + timedelta(seconds=seconds // 2)
                pending.extend([(middle, end), (start, middle)])
                continue
            for row in rows:
                event = self._normalize(row, event_names)
                if event is None:
                    continue
                if events.setdefault(event.event_id, event) != event:
                    raise BioStarError("Conflicting duplicate BioStar scan ID")
        result = sorted(events.values(), key=lambda raw: (raw.occurred_at, raw.event_id))
        return result, SyncCursor(json.dumps({"until": upper.isoformat()}))
