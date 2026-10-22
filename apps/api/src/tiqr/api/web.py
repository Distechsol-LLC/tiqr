"""The bundled web build under /tiqr: its files, and index.html for every other path there."""

import json
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from tiqr.api.errors import ApiError
from tiqr.core.settings import Settings

# Release builds copy apps/web/build here; a source checkout has none and serves the API alone.
WEB_ROOT = Path(__file__).parent / "web"
# Where the app is served; apps/web/vite.config.mts sets the same base.
WEB_PREFIX = "/tiqr"
_IMMUTABLE = "public, max-age=31536000, immutable"
_REVALIDATE = "no-cache"
_LOGO_TYPES = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# The names and icon that index.html and site.webmanifest ship with; the install's own replace them.
_TITLE = "<title>TiQR</title>"
_SOCIAL_TITLE = "<meta content='TiQR' property='og:title'>"
_ICON = "<link href='/favicon.png' rel='icon' sizes='512x512' type='image/png'>"


def _settings(request: Request) -> Settings | None:
    state = getattr(request.app.state, "tiqr", None)
    return state.runtime.settings if state is not None else None


def _branded_index(page: str, settings: Settings | None) -> str:
    if settings is None:
        return page
    name = escape(settings.app_name)
    page = page.replace(_TITLE, f"<title>{name}</title>")
    page = page.replace(_SOCIAL_TITLE, f"<meta content='{name}' property='og:title'>")
    if settings.logo_path is not None:
        kind = _LOGO_TYPES[settings.logo_path.suffix.lower()]
        page = page.replace(_ICON, f"<link href='/api/logo' rel='icon' type='{kind}'>")
    return page


def _branded_manifest(manifest: str, settings: Settings | None) -> str:
    if settings is None:
        return manifest
    data = json.loads(manifest)
    data["name"] = data["short_name"] = settings.app_name
    if settings.logo_path is not None:
        kind = _LOGO_TYPES[settings.logo_path.suffix.lower()]
        data["icons"] = [{"src": "/api/logo", "type": kind, "sizes": "any", "purpose": "any"}]
    return json.dumps(data, ensure_ascii=False, indent=2)


def install_web(app: FastAPI, root: Path = WEB_ROOT) -> None:
    index = root / "index.html"
    if not index.is_file():
        return
    root = root.resolve()
    # Vite puts content-hashed files here, so they never change under the same name.
    immutable = root / "assets"

    manifest = root / "site.webmanifest"

    # Before the catch-all below: the manifest and the page carry the install's name and logo.
    @app.get(f"{WEB_PREFIX}/site.webmanifest", include_in_schema=False)
    def webmanifest(request: Request) -> Response:
        if not manifest.is_file():
            raise ApiError(404, "not_found", "Not found")
        body = _branded_manifest(manifest.read_text(encoding="utf-8"), _settings(request))
        return Response(
            body, media_type="application/manifest+json", headers={"Cache-Control": _REVALIDATE}
        )

    @app.get(WEB_PREFIX, include_in_schema=False)
    @app.get(f"{WEB_PREFIX}/{{path:path}}", include_in_schema=False)
    def web(request: Request, path: str = "") -> Response:
        file = (root / path).resolve()
        # resolve() undoes "..", so anything outside the build falls back to the app shell.
        if path and file.is_relative_to(root) and file.is_file():
            cache = _IMMUTABLE if file.is_relative_to(immutable) else _REVALIDATE
            return FileResponse(file, headers={"Cache-Control": cache})
        page = _branded_index(index.read_text(encoding="utf-8"), _settings(request))
        return HTMLResponse(page, headers={"Cache-Control": _REVALIDATE})

    # Registered after the routes above, so it only matches what they don't.
    @app.get("/{path:path}", include_in_schema=False)
    def elsewhere(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "Not found")
        return RedirectResponse(f"{WEB_PREFIX}/")
