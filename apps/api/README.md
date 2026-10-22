# TiQR API

> TiQR API is made with
> - **[Python](https://python.org)**
> - **[FastAPI](https://fastapi.tiangolo.com)**
> - **[Uvicorn](https://uvicorn.dev)**
>
> and is the HTTP layer over `tiqr-core`. It serves the bundled web app from the same process, so `tiqr serve` runs both.

## Contents
- [Install](#install)
- [Configuration](#configuration)
- [Run](#run)
- [Authentication and sessions](#authentication-and-sessions)
- [Errors](#errors)
- [Endpoints](#endpoints)
- [Roles](#roles)
- [Develop](#develop)

## Install
```sh
uv python install 3.14
uv sync --locked
```

## Configuration

`tiqr serve` reads the `TIQR_*` variables from the environment and from `.env` / `.env.local` in the project root. Blank means unset. Command-line flags override the matching variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIQR_SECRET_KEY` | none, required | Secret for the server. Must be non-empty and not a placeholder. `tiqr setup` generates one. |
| `TIQR_DB` | `tiqr.db` | SQLite database path, relative to the project root. |
| `TIQR_OUT` | `out` | Directory where PDFs are kept. |
| `TIQR_DEFAULT_TZ` | machine zone, or `UTC` | IANA zone for offset-less input and for all displayed times. |
| `TIQR_HOST` | `127.0.0.1` | Bind address. Set to the server's LAN address for operators' PCs. |
| `TIQR_PORT` | `7102` | Listen port, 1 to 65535. |
| `TIQR_TLS_CERT`, `TIQR_TLS_KEY` | unset | PEM certificate and key. Set both to serve HTTPS, or neither for plain HTTP. |
| `TIQR_SERVER_PRINTING` | `false` | When `true`, operators may print on the server's default printer as well as download the PDF. |
| `TIQR_SYNC_INTERVAL` | `60` | Seconds between scheduled access-event syncs. `0` turns it off. |
| `TIQR_CLEANUP_INTERVAL` | `3600` | Seconds between scheduled BioStar cleanups. `0` turns it off. |
| `TIQR_BIOSTAR_BASE_URL`, `_USERNAME`, `_PASSWORD` | unset | BioStar connection. Leave all three unset for local mode. |
| `TIQR_BIOSTAR_DEVICE_IDS` | unset | Comma-separated reader IDs, all added to the TiQR access group. |
| `TIQR_BIOSTAR_ACCESS_GROUP_ID` | unset | Optional. If blank, `tiqr setup` creates an access group named TiQR. |
| `TIQR_BIOSTAR_VERIFY_TLS` | `false` | `true` verifies BioStar's TLS certificate. |
| `TIQR_BIOSTAR_REQUIRED` | `false` | `true` refuses to start unless BioStar is configured. |

Keep private values, especially the password and secret key, in `.env.local`, which is not committed.

## Run

```sh
uv run tiqr serve            # production: no API docs, no schema endpoint
uv run tiqr serve --dev      # loopback only; also serves the interactive docs
```

- The app is served at `http://<host>:<port>/tiqr`. Any other path redirects there. Unknown paths under `/api` return `404`.
- The JSON API lives under `/api`.
- With `--dev`, the interactive docs are at `/api/docs` and the OpenAPI schema at `/api/openapi.json`. Production exposes neither.
- On startup, a background job runs one sync and one cleanup, then repeats them on their intervals.

## Authentication and sessions

1. `POST /api/auth/login` with a username and password. The response sets an HTTP-only session cookie and returns a `csrf_token`.
2. Every later request sends the cookie automatically (browsers) or as a `Cookie` header.
3. Every **write** request (`POST`, `PATCH`, and so on) must also send the token in the `X-CSRF-Token` header. A missing or wrong token gets `403`.
4. Requests with an `Origin` header that does not match the server's own scheme and host are refused with `403` (`cross_origin`).

Session rules:

- The cookie is named `__Host-tiqr-session` over HTTPS and `tiqr-session` over plain HTTP. It is `SameSite=Strict` and cleared on logout.
- A session ends after **30 minutes** without a request, or **12 hours** after sign-in, whichever comes first. `GET /api/auth/session` reports both values.
- Signing in again replaces the browser's previous session.
- Deactivating a user, or resetting their password, ends that user's sessions.

Login throttling: after repeated failures, `POST /api/auth/login` returns `429` with a `Retry-After` header (in seconds). The limit is 5 failures per address and username pair, or 20 per address, within 15 minutes. A success clears the pair's count.

## Errors

Refusals use one shape:

```json
{ "detail": "Ticket not found", "code": "not_found" }
```

| HTTP | `code` | Meaning |
| --- | --- | --- |
| 401 | `unauthenticated` | Not signed in, session expired, or sign-in refused |
| 403 | `forbidden` | The role may not do this |
| 403 | `csrf` | Missing or wrong `X-CSRF-Token` |
| 403 | `cross_origin` | Write request from another origin |
| 404 | `not_found` | Ticket or user not found |
| 409 | `conflict` | The ticket or account is not in a state that allows this |
| 409 | `server_printing_off` | Server printing is off; download the PDF instead |
| 422 | `invalid` | A value the server refuses |
| 422 | (validation) | A malformed request. `detail` is a list of per-field errors, as FastAPI reports them |
| 429 | `rate_limited` | Too many failed logins; wait `Retry-After` seconds |
| 502 | `printer` | The server's printer failed |
| 502 | `biostar` | BioStar failed. `detail` includes the BioStar code and HTTP status when present |
| 500 | `internal` | Unexpected error. Details stay in the server log. |

Responses never include password hashes, secrets, or stack traces.

## Endpoints

All paths are relative to `/api`. Times are ISO 8601 with an offset. Input without an offset is read in the ticket's `timezone` (or the server's default).

### Meta

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | none | Readiness and version. Returns `200` with `status: "ok"`, or `503` with `status: "unavailable"` if the database does not answer or the scheduler has stopped. |
| GET | `/config` | session | Server timezone and whether server printing is on. |

### Auth

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/auth/login` | none | Body `{username, password}`. Returns the user, `csrf_token`, `expires_at`, and `idle_timeout`, and sets the cookie. |
| POST | `/auth/logout` | session + CSRF | Ends the session and clears the cookie. Returns `204`. |
| GET | `/auth/session` | session | The signed-in user, `csrf_token`, `expires_at`, and `idle_timeout`. |

### Users

Admins manage every account. Managers list accounts, create operators, and deactivate or reactivate them.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/users` | session | List accounts visible to the caller. |
| POST | `/users` | session + CSRF | Create a user. Body `{username, password, role}`. Managers create operators only. Returns `201`. |
| PATCH | `/users/{user_id}` | session + CSRF | Change `role`, set `active`, or reset `password`. Omitted fields are unchanged. Managers may only set `active`, on operators. |
| DELETE | `/users/{user_id}` | session + CSRF | Delete a deactivated user. Admins only. Returns `204`; `409` if active or they created or hold tickets. |

Admins cannot change their own role or deactivate themselves. The last active admin cannot be demoted.

### Tickets

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/tickets` | session | List tickets, sorted by readable serial. Optional `?state=issued\|passed\|expired`. |
| POST | `/tickets` | session + CSRF | Issue a ticket. Returns `201`. |
| GET | `/tickets/{ticket_id}` | session | One ticket. |
| POST | `/tickets/{ticket_id}/assign` | session + CSRF | Body `{assignee}`: the username of any existing account to assign the ticket to. Managers only. |
| POST | `/tickets/{ticket_id}/pdf` | session + CSRF | Render the one-page A4 badge and return it as `application/pdf`. Counts as a print, and the file is also saved to `TIQR_OUT`. Issued tickets only. |
| POST | `/tickets/{ticket_id}/print` | session + CSRF | Print on the server's default printer. Needs `TIQR_SERVER_PRINTING=true`. Issued tickets only. Returns the updated ticket. |

Create body:

```json
{
  "visitor_name": "Jane Doe",
  "visitor_type": "Contractor",
  "valid_from": "2030-06-01T09:00",
  "valid_until": "2030-06-01T17:00",
  "usage_type": "one_time",
  "timezone": "Asia/Dubai"
}
```

- `usage_type` is `one_time` or `multi_use`.
- `timezone` is optional. It defaults to the server's `TIQR_DEFAULT_TZ`.
- Names are at most 200 characters.

A ticket response contains `id`, `readable_serial`, `visitor_name`, `visitor_type`, `valid_from`, `valid_until`, `usage_type`, `state` (`issued`, `passed`, or `expired`), `created_by`, `assigned_operator`, `created_at`, `passed_at`, `print_count`, `use_count`, and `timezone`. All datetimes are shown in `timezone`.

### Operations

Admins and managers.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/sync` | session + CSRF | Fetch and apply new access events now. Returns `{count}`. |
| POST | `/cleanup` | session + CSRF | Remove finished tickets from BioStar now. Returns `{count}`. |
| GET | `/stats` | session | Totals: `total`, `issued`, `passed`, `expired`, `uses`, `prints`, plus the same counts per visitor type under `visitor_types`. |

Sync and cleanup share a lock with the scheduled jobs, so runs never overlap.

## Roles

| Role | Can |
| --- | --- |
| `admin` | Manage users (create, change role, deactivate, reset passwords, delete), plus everything a manager can do |
| `manager` | Assign tickets, run sync, cleanup and stats, list users, and create, deactivate or reactivate operators |
| `operator` | Issue tickets, and view and print only the tickets assigned to them |

Anyone active can issue tickets. Permissions are enforced in `tiqr-core`'s service layer, and this table summarizes them.

## Example

```sh
# Sign in and keep the cookie
curl -c jar.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"..."}' \
  http://127.0.0.1:7102/api/auth/login

# Copy csrf_token from the response, then send it on writes
curl -b jar.txt -H 'Content-Type: application/json' \
  -H 'X-CSRF-Token: <csrf_token>' \
  -d '{"visitor_name":"Jane Doe","visitor_type":"Contractor","valid_from":"2030-06-01T09:00","valid_until":"2030-06-01T17:00","usage_type":"one_time"}' \
  http://127.0.0.1:7102/api/tickets
```

## OpenAPI

The schema is committed as `openapi.json`. The web app's client is generated from it, so regenerate it after any API change. The tests fail if the committed copy is out of date.

```sh
uv run poe openapi
```

## Develop
### Start Server
```sh
uv run tiqr serve
```
### Regenerate OpenAPI Schema
```sh
uv run poe openapi
```
## Tools
### Fix Code (Ruff + Pyright)
```sh
uv run poe fix
```
## Test
### Run Suite
```sh
uv run pytest
```
