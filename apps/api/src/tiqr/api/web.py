"""The bundled web build under /tiqr: its files, and index.html for every other path there."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, Response

from tiqr.api.errors import ApiError

# Release builds copy apps/web/build here; a source checkout has none and serves the API alone.
WEB_ROOT = Path(__file__).parent / "web"
# Where the app is served; apps/web/vite.config.mts sets the same base.
WEB_PREFIX = "/tiqr"
_IMMUTABLE = "public, max-age=31536000, immutable"
_REVALIDATE = "no-cache"


def install_web(app: FastAPI, root: Path = WEB_ROOT) -> None:
    index = root / "index.html"
    if not index.is_file():
        return
    root = root.resolve()
    # Vite puts content-hashed files here, so they never change under the same name.
    immutable = root / "assets"

    @app.get(WEB_PREFIX, include_in_schema=False)
    @app.get(f"{WEB_PREFIX}/{{path:path}}", include_in_schema=False)
    def web(path: str = "") -> FileResponse:
        file = (root / path).resolve()
        # resolve() undoes "..", so anything outside the build falls back to the app shell.
        if path and file.is_relative_to(root) and file.is_file():
            cache = _IMMUTABLE if file.is_relative_to(immutable) else _REVALIDATE
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": _REVALIDATE})

    # Registered after the routes above, so it only matches what they don't.
    @app.get("/{path:path}", include_in_schema=False)
    def elsewhere(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "Not found")
        return RedirectResponse(f"{WEB_PREFIX}/")
