"""Write THIRD-PARTY-NOTICES.txt: the licenses of everything bundled into the executable.

    uv run python packaging/notices.py OUTPUT [--web apps/web]

Python packages come from the active environment; with `--web`, the web app's direct runtime
dependencies come from its node_modules. The fixed entries cover what has no package metadata.
"""

import argparse
import json
import re
from importlib.metadata import Distribution, distributions
from pathlib import Path

_LICENSE_FILE = re.compile(r"(licen[sc]e|copying|notice)", re.IGNORECASE)
_SHORT_LICENSE_FIELD = 80
_OWN = re.compile(r"^tiqr(-|$)")
# Build tools and test runners are not in the executable; the runtime set is what ships.
_NOT_SHIPPED = re.compile(
    r"^(pyinstaller|pyinstaller-hooks-contrib|altgraph|pefile|pywin32-ctypes|packaging|setuptools"
    r"|pytest.*|ruff|pyright|nodeenv|iniconfig|pluggy|pygments|coverage.*|pip|uv|types-.*"
    r"|pip-audit.*|lefthook.*|commitizen.*)$"
)
_FIXED = (
    (
        "Geist font",
        "SIL Open Font License 1.1",
        (
            "Geist is copyright The Geist Project Authors (https://github.com/vercel/geist-font). "
            "It is licensed under the SIL Open Font License, Version 1.1: "
            "https://openfontlicense.org"
        ),
    ),
    (
        "PyInstaller bootloader",
        "GPL-2.0-or-later with the PyInstaller bootloader exception",
        (
            "The bootloader that starts the executable may be used in closed-source programs; see "
            "https://pyinstaller.org/en/stable/license.html"
        ),
    ),
    (
        "WinSW (Windows bundle only)",
        "MIT",
        (
            "Copyright (c) 2008 Kohsuke Kawaguchi, Sun Microsystems, Inc., CloudBees, Inc. and "
            "contributors. https://github.com/winsw/winsw"
        ),
    ),
)


def _license_name(dist: Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        value.rsplit(" :: ", 1)[-1]
        for value in meta.get_all("Classifier") or []
        if value.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    text = (meta.get("License") or "").strip()
    return (
        text
        if 0 < len(text) < _SHORT_LICENSE_FIELD and "\n" not in text
        else "see the license text below"
    )


def _license_text(dist: Distribution) -> str:
    chunks: list[str] = []
    for file in dist.files or []:
        if _LICENSE_FILE.search(file.name) and file.suffix in {"", ".txt", ".md", ".rst"}:
            try:
                chunks.append(
                    Path(str(dist.locate_file(file)))
                    .read_text(encoding="utf-8", errors="replace")
                    .strip()
                )
            except OSError, UnicodeError:
                continue
    return "\n\n".join(dict.fromkeys(chunks))


def _python_section() -> list[str]:
    seen: dict[str, Distribution] = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name and not _OWN.match(name.lower()) and not _NOT_SHIPPED.match(name.lower()):
            seen.setdefault(name.lower(), dist)
    entries = []
    for name in sorted(seen):
        dist = seen[name]
        text = _license_text(dist) or "(no license file in the package)"
        entries.append(f"{dist.metadata['Name']} {dist.version}: {_license_name(dist)}\n\n{text}")
    return entries


def _web_section(web: Path) -> list[str]:
    package = json.loads((web / "package.json").read_text(encoding="utf-8"))
    entries = []
    for name in sorted(package.get("dependencies", {})):
        folder = web / "node_modules" / name
        try:
            meta = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        except OSError:
            entries.append(f"{name}: not installed when these notices were written")
            continue
        text = "\n\n".join(
            path.read_text(encoding="utf-8", errors="replace").strip()
            for path in sorted(folder.iterdir())
            if path.is_file() and _LICENSE_FILE.search(path.name)
        )
        license_name = meta.get("license", "see the license text below")
        entries.append(f"{name} {meta.get('version', '?')}: {license_name}\n\n{text}")
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("output", type=Path)
    parser.add_argument("--web", type=Path, help="the web app folder, with node_modules")
    args = parser.parse_args()
    rule = "\n\n" + "=" * 78 + "\n\n"
    sections = [
        "TiQR bundles the following third-party software. Each is used under its own license."
    ]
    sections += [f"{name}: {licence}\n\n{text}" for name, licence, text in _FIXED]
    sections += _python_section()
    if args.web:
        sections += _web_section(args.web)
    args.output.write_text(rule.join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
