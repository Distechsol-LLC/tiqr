"""Reading local wall-clock input at the edges; the rest of the core works in UTC."""

import re
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")


def zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {timezone}") from exc


def parse_input_datetime(text: str, timezone: str) -> datetime:
    """Read an ISO datetime; one without an offset is a wall-clock time in `timezone`."""
    local = zone(timezone)
    text = text.strip()
    if not _ISO_DATETIME.match(text):
        raise ValueError("Use an ISO datetime including a time, such as 2030-01-01T12:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {text}") from exc
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    # A wall-clock time maps to one instant, two (DST fall-back) or none (spring-forward).
    candidates: set[datetime] = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=local, fold=fold).astimezone(UTC)
        if candidate.astimezone(local).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if len(candidates) != 1:
        kind = "Ambiguous" if candidates else "Nonexistent"
        raise ValueError(f"{kind} local datetime in {timezone}; supply an explicit UTC offset")
    return candidates.pop()


def day_start(day: date, timezone: str) -> datetime:
    """The instant `day` began in `timezone`; each midnight takes its own offset, DST or not."""
    return datetime.combine(day, time(), tzinfo=zone(timezone)).astimezone(UTC)
