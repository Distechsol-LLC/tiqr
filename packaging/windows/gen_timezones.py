"""Write timezones.txt, the IANA identifiers the installer accepts.

Regenerate with: uv run python packaging/windows/gen_timezones.py

The installer has no time zone database of its own, so it ships this list. It comes from the same
database the app resolves `default_tz` against (zoneinfo, backed by tzdata).
"""

from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

OUTPUT = Path(__file__).with_name("timezones.txt")


def main() -> None:
    names = sorted(name for name in available_timezones() if name.isascii())
    for name in names:
        ZoneInfo(name)  # fail here, not on a customer's machine
    OUTPUT.write_text("".join(f"{name}\n" for name in names), encoding="ascii", newline="\n")
    print(f"Wrote {len(names)} identifiers to {OUTPUT}")  # noqa: T201


if __name__ == "__main__":
    main()
