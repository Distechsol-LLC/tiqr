"""Write the OpenAPI schema the web app's client is generated from.

    uv run python -m tiqr.api.openapi apps/web/openapi.json

The tests compare the committed copy with this output, so an API change must regenerate it.
"""

import json
import sys
from pathlib import Path
from typing import Any

from tiqr.api.app import create_app
from tiqr.api.config import ServerConfig


def schema() -> dict[str, Any]:
    # Building the schema opens nothing: no settings, database or BioStar.
    return create_app(ServerConfig(dev=True)).openapi()


def render() -> str:
    return json.dumps(schema(), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        raise SystemExit("usage: python -m tiqr.api.openapi OUTPUT.json")
    Path(arguments[0]).write_text(render(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
