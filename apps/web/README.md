# TiQR web

Not started. This folder will hold a Svelte app built with Vite into static files. It is not a
separate program: the API serves the build, so it ships inside the `tiqr` executable. The rules
it must follow, from [DEPLOYMENT.md](../../DEPLOYMENT.md):

- **Static build.** Use plain Vite with `@sveltejs/vite-plugin-svelte`, no SvelteKit and no
  adapter. Set `build.outDir` to `build`. The backend serves `index.html` for every non-API path,
  so the app needs no server-side routing. No Node.js runs on the customer's server.
- **Same origin, relative URLs.** Call the API as `fetch("/api/...")`, never an absolute URL or
  an IP. The browser already knows the server's address, so the build is identical for every
  customer and needs no CORS. In development, Vite's `server.proxy` forwards `/api` to a
  local `tiqr serve`.
- **Nothing private in the bundle.** Everything shipped to the browser is readable by anyone
  who loads the page. Minify, ship no source maps, and keep secrets, license checks and
  permission decisions on the server; the UI only hides what the API already forbids.
- **Build output.** `build/` is copied to `apps/api/src/tiqr/api/web/` at release time; both are
  git-ignored. Vite writes hashed files to `assets/`, and `tiqr serve` caches those for a year.
  Everything else, the `index.html` fallback included, gets `no-cache`. Commit the package
  manager's lockfile and build with a locked install in CI.
- **Content Security Policy.** The server sets one on `/api` responses only. Set the app's own
  in `index.html` with a `<meta http-equiv="Content-Security-Policy">` tag. Vite's build emits no
  inline scripts, so `script-src 'self'` needs no hashes.

## Talking to the API

The [Web API](../../README.md#web-api) section of the main README lists the endpoints and their
rules. [`openapi.json`](../api/openapi.json) is the schema to generate a typed client from, for example with
`openapi-typescript` and `openapi-fetch`. Its operation IDs are the backend's function names,
such as `create_ticket`. Regenerate it with `uv run poe openapi` after an API change.

- **Sessions.** `POST /api/auth/login` sets an `HttpOnly` cookie the app never sees, and returns
  the user and a `csrf_token`. On load, call `GET /api/auth/session` to get both again; a `401`
  there, or from any request, means show the login page. Same-origin `fetch` sends the cookie
  without extra options.
- **CSRF.** Send the token as `X-CSRF-Token` on every `POST` and `PATCH`, logout included. Keep it in memory
  only, never in `localStorage`.
- **Errors.** Refusals are `{"detail": "...", "code": "..."}`; show `detail` and branch on `code`.
  Malformed bodies answer FastAPI's `422` form instead, whose `detail` is a list. `429` from login
  carries `Retry-After` in seconds.
- **PDFs.** `POST /api/tickets/{id}/pdf` returns the badge. Fetch it, then open
  `URL.createObjectURL(blob)` in a new tab, and tell the operator to print at "Actual size".
  Show the server print button only when `GET /api/config` reports `server_printing`.
- **Times.** Send `valid_from` and `valid_until` as ISO datetimes without an offset, plus the
  operator's IANA `timezone`, or with an explicit offset. Responses use `GET /api/config`'s
  `timezone`, offsets included.
- **Development.** Run `uv run tiqr serve --dev` and point Vite's `server.proxy` at it:
  `{"/api": "http://127.0.0.1:7102"}`. Leave `changeOrigin` off, so the API's origin check sees
  the browser's own host.
