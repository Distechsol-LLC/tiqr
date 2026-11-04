"""The BioStar connection, managed from the web app: settings, readers and scan log (admin)."""

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints

from tiqr.api.deps import AppState, Server, Signed, require_license
from tiqr.api.errors import ApiError
from tiqr.api.schemas import ErrorOut
from tiqr.core.biostar import BioStarClient, BioStarXProvisioner
from tiqr.core.models import AccessEvent
from tiqr.core.service import BioStarLink
from tiqr.core.settings import BioStarSettings, write_biostar_settings

router = APIRouter(
    prefix="/api/biostar",
    tags=["biostar"],
    dependencies=[Depends(require_license)],
    responses={500: {"model": ErrorOut, "description": "Unexpected server error"}},
)

_MAX_LOGS = 500
_REFUSALS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorOut} for code in (401, 403, 409, 422, 502)
}


class BioStarOut(BaseModel):
    configured: bool
    base_url: str = ""
    username: str = ""
    has_password: bool = False
    device_ids: list[str] = []
    access_group_id: str = ""
    verify_tls: bool = False
    door_open_duration: int = 3
    door_open_timeout: int = 10

    @classmethod
    def of(cls, settings: BioStarSettings | None) -> BioStarOut:
        if settings is None:
            return cls(configured=False)
        return cls(
            configured=True,
            base_url=settings.base_url,
            username=settings.username,
            has_password=bool(settings.password),
            device_ids=list(settings.device_ids),
            access_group_id=settings.access_group_id,
            verify_tls=settings.verify_tls,
            door_open_duration=settings.door_open_duration,
            door_open_timeout=settings.door_open_timeout,
        )


class BioStarIn(BaseModel):
    base_url: Annotated[str, StringConstraints(max_length=500)]
    username: Annotated[str, StringConstraints(max_length=150)]
    # Blank keeps the saved password, so it never has to travel back to the browser.
    password: Annotated[str, StringConstraints(max_length=1024)] = ""
    device_ids: list[Annotated[str, StringConstraints(max_length=50)]]
    access_group_id: Annotated[str, StringConstraints(max_length=50)] = ""
    verify_tls: bool = False
    door_open_duration: int = 3
    door_open_timeout: int = 10


class DeviceOut(BaseModel):
    id: str
    name: str
    address: str
    status: str
    selected: bool


class LogOut(BaseModel):
    event_id: str
    event_time: datetime
    point_id: str | None
    point_name: str | None
    direction: str | None
    granted: bool
    outcome: str

    @classmethod
    def of(cls, event: AccessEvent) -> LogOut:
        return cls(
            event_id=event.event_id,
            event_time=event.occurred_at,
            point_id=event.point_id,
            point_name=event.point_name,
            direction=event.direction,
            granted=event.granted,
            outcome=event.outcome.value,
        )


def _link(server: AppState) -> BioStarLink:
    link = server.service.biostar_link
    if link is None:
        raise ApiError(409, "conflict", "This server does not manage a BioStar connection")
    return link


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _address(row: dict[str, Any]) -> str:
    lan = row.get("lan")
    if isinstance(lan, dict):
        lan_row = cast(dict[str, Any], lan)
        if lan_row.get("ip"):
            return _text(lan_row["ip"])
    return _text(row.get("ip"))


@router.get("", responses=_REFUSALS)
def biostar_settings(me: Signed, server: Server) -> BioStarOut:
    """The saved connection, without its password (admin)."""
    server.service.require_admin(me.user)
    return BioStarOut.of(_link(server).settings)


@router.put("", responses=_REFUSALS)
def save_biostar_settings(body: BioStarIn, me: Signed, server: Server) -> BioStarOut:
    """Check the connection, save it, and use it from now on (admin).

    A blank password keeps the saved one. Nothing is saved when BioStar refuses the login.
    """
    server.service.require_admin(me.user)
    link = _link(server)
    held = link.settings
    password = body.password or (held.password if held else "")
    settings = BioStarSettings(
        base_url=body.base_url.strip(),
        username=body.username.strip(),
        password=password,
        device_ids=tuple(dict.fromkeys(item.strip() for item in body.device_ids if item.strip())),
        access_group_id=body.access_group_id.strip(),
        verify_tls=body.verify_tls,
        door_open_duration=body.door_open_duration,
        door_open_timeout=body.door_open_timeout,
    )
    with BioStarClient(settings) as probe:
        probe.login()
        BioStarXProvisioner(probe).ensure_access()
    write_biostar_settings(settings)
    link.connect(settings)
    return BioStarOut.of(settings)


@router.delete("", status_code=204, responses=_REFUSALS)
def disconnect_biostar(me: Signed, server: Server) -> None:
    """Forget the connection and go back to local mode (admin)."""
    server.service.require_admin(me.user)
    link = _link(server)
    write_biostar_settings(None)
    link.connect(None)


@router.get("/devices", responses=_REFUSALS)
def biostar_devices(me: Signed, server: Server) -> list[DeviceOut]:
    """The readers BioStar knows, marking those TiQR uses (admin)."""
    server.service.require_admin(me.user)
    link = _link(server)
    if link.client is None or link.settings is None:
        raise ApiError(409, "conflict", "BioStar is not connected")
    selected = set(link.settings.device_ids)
    devices: list[DeviceOut] = []
    for row in link.client.list_devices():
        identifier = _text(row.get("id"))
        devices.append(
            DeviceOut(
                id=identifier,
                name=_text(row.get("name")),
                address=_address(row),
                status=_text(row.get("status")),
                selected=identifier in selected,
            )
        )
    return devices


@router.get("/logs", responses=_REFUSALS)
def biostar_logs(
    me: Signed, server: Server, limit: Annotated[int, Query(ge=1, le=_MAX_LOGS)] = 100
) -> list[LogOut]:
    """The newest scans the readers reported, newest first (admin)."""
    return [LogOut.of(event) for event in server.service.recent_events(me.user, limit)]
