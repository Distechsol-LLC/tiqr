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
- [Example](#example)
- [OpenAPI](#openapi)
- [Postman and HTTP client](#postman-and-http-client)
- [Database](#database)
- [Develop](#develop)

## Install
```sh
uv python install 3.14
uv sync --locked
```

## Configuration

`tiqr serve` reads `tiqr_brand.jsonc` from the project root, then `.env` and `.env.local` (later files override earlier ones), then the real environment. The brand file is required: the server refuses to start without it. Blank means unset. Command-line flags override the matching variables.

`tiqr_brand.jsonc` (comments allowed) holds the branding and the non-secret settings. Its `host`, `port`, `tls_cert`, `tls_key`, `server_printing`, `default_tz`, `prefix` and `biostar` keys map to the `TIQR_*` variables below; a `null` leaves the lower layer in place. Restart the server to apply changes. Keep `TIQR_SECRET_KEY` and the BioStar password out of it.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIQR_SECRET_KEY` | none, required | Secret for the server. Must be non-empty and not a placeholder. `tiqr setup` generates one. |
| `TIQR_HOME` | unset | Set in the real environment by an installed service. Holds the data, `.env` files and brand file, and must be a real environment variable, not one set in a `.env` file. |
| `TIQR_DEFAULT_TZ` | machine zone, or `UTC` | IANA zone for offset-less input and for all displayed times. |
| `TIQR_PREFIX` | `TQR` | Prefix of each ticket's readable serial. |
| `TIQR_HOST` | `127.0.0.1` | Bind address. Set to the server's LAN address for operators' PCs. |
| `TIQR_PORT` | `7102` | Listen port, 1 to 65535. |
| `TIQR_TLS_CERT`, `TIQR_TLS_KEY` | unset | PEM certificate and key. Set both to serve HTTPS, or neither for plain HTTP. |
| `TIQR_SERVER_PRINTING` | `false` | When `true`, operators may print on the server's default printer as well as download the PDF. Leave `false` to allow download only. |
| `TIQR_IDEMPOTENCY_TTL_HOURS` | `24` | How long an `Idempotency-Key` remembers its answer. |
| `TIQR_BATCH_MAX_SIZE` | `500` | Most tickets one `POST /tickets/batch` may carry; more is a `422`. |
| `TIQR_PASS_WEBHOOK_URL`, `TIQR_PASS_WEBHOOK_SECRET` | unset | Optional. Each new passage is POSTed to the URL, signed with the secret in `X-Tiqr-Signature` (`sha256=` HMAC over `X-Tiqr-Timestamp` and the body). Failed deliveries are retried, then left to the `/passes` feed. Set both, or neither. |
| `TIQR_BIOSTAR_BASE_URL`, `_USERNAME`, `_PASSWORD`, `_DEVICE_IDS` | unset | BioStar connection. Set all four, or none for local mode; a partial set is an error. `_PASSWORD` belongs in `.env.local`, not the brand file. |
| `TIQR_BIOSTAR_ACCESS_GROUP_ID` | unset | Optional. If blank, TiQR uses its own access group named `TiQR AG`, which `tiqr setup` creates. |
| `TIQR_BIOSTAR_VERIFY_TLS` | `false` | `true` verifies BioStar's TLS certificate. |
| `TIQR_BIOSTAR_TIMEOUT` | `30` | Seconds to wait for a BioStar reply. |
| `TIQR_BIOSTAR_DOOR_OPEN_DURATION` | `3` | Seconds a reader keeps its door open after a valid tap. |
| `TIQR_BIOSTAR_DOOR_OPEN_TIMEOUT` | `10` | Seconds a reader waits for the door to open. |
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
| 400 | `license_bad_signature`, `license_wrong_machine`, `license_already_expired`, `license_trial_over_paid` | `POST /license/activate` refused the key: not valid for this product, for another machine, expired, or a trial over a paid license |
| 401 | `unauthenticated` | Not signed in, session expired, or sign-in refused |
| 403 | `forbidden` | The role may not do this |
| 403 | `scope` | The service key lacks a scope the endpoint needs |
| 403 | `csrf` | Missing or wrong `X-CSRF-Token` |
| 403 | `cross_origin` | Write request from another origin |
| 403 | `license_required` | No valid license; every endpoint not marked "no license needed" below is refused |
| 404 | `not_found` | Ticket, user, ticket type, visitor type, service key or logo not found |
| 409 | `conflict` | The ticket or account is not in a state that allows this |
| 409 | `external_code_taken` | Another pass already has this `external_code` |
| 409 | `idempotency_mismatch` | An `Idempotency-Key` was reused with a different body |
| 409 | `invalid_state` | The pass's state does not allow the action (for example revoking an expired pass) |
| 409 | `server_printing_off` | Server printing is off; download the PDF instead |
| 409 | `license_already_active` | That key is already the active license |
| 422 | `credential_format` | An `external_code` the venue's readers cannot read; the allowed formats are in the `external_code` field description under Create body |
| 422 | `invalid` | A value the server refuses |
| 422 | `batch_too_large` | A batch carries more than `TIQR_BATCH_MAX_SIZE` tickets |
| 422 | (validation) | A malformed request. `detail` is a list of per-field errors, as FastAPI reports them |
| 429 | `rate_limited` | Too many failed logins; wait `Retry-After` seconds |
| 502 | `printer` | The server's printer failed |
| 502 | `biostar` | BioStar failed. `detail` includes the BioStar code and HTTP status when present |
| 500 | `internal` | Unexpected error. Details stay in the server log. |

Responses never include password hashes, secrets, or stack traces.

Every response carries an `X-Request-Id` header. A caller's own id is reused when it is short and safe (letters, digits, `.`, `_`, `-`, up to 128 characters); otherwise one is generated. The same id is written to the server log, so quote it when reporting an incident.

## Endpoints

All paths are relative to `/api`. Times are ISO 8601 and always carry an offset, for example `2026-11-20T17:00:00+05:00`. Input without an offset is read in the request's `timezone` (or the server's default). Ticket times are returned in the ticket's `timezone`; passage `event_time` values are returned in UTC, shown with `Z` (for example `2026-11-20T12:00:00Z`).

The `Auth` column says what a call needs: `session` is the cookie from login; `+ CSRF` adds the `X-CSRF-Token` header on writes; `key` is a service key with that scope (see [Service-to-service calls](#service-to-service-calls)).

### Pagination

`GET /users`, `GET /tickets`, `GET /ticket-types` and `GET /visitor-types` answer one page: `{items, total, page, size}`, where `total` counts every match. Ask with `?page=` (from 1, default 1) and `?size=` (1 to 100, default 20); anything else is a `422`. A page past the end has an empty `items`. Other lists (license history, service keys, ticket audit) are not paged.

### Meta

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | none, no license needed | Readiness and version. Returns `200` with `status: "ok"`, or `503` with `status: "unavailable"` if the database does not answer or the scheduler has stopped. |
| GET | `/branding` | none, no license needed | `app_name`, `theme`, `languages`, `currencies` and `has_logo`, for the login page. |
| GET | `/logo` | none, no license needed | The configured logo file; `404` if none is set. |
| GET | `/config` | session | Server `timezone` and whether `server_printing` is on. |

### License

Every endpoint not marked "no license needed" is refused with `403` `license_required` until a valid license is active.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/license/status` | session, no license needed | The license, verified now: `state`, `is_valid`, `machine_id`, and when licensed `type`, `licensed_to`, `expires_at`, `days_remaining`. |
| GET | `/license/request-code` | session, no license needed | A code to send the vendor. Any role. |
| POST | `/license/activate` | session + CSRF, no license needed | Body `{license_key}`. Admins only. Returns the new status; a refused key (`400`, or `409` if already active) leaves the current license in place. |
| POST | `/license/deactivate` | session + CSRF | Retire the active key. Admins only. Returns `204`. |
| GET | `/license/history` | session | Every stored key, newest first, with most of each key hidden. Admins only. |

### Auth

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/auth/login` | none, no license needed | Body `{username, password}`. Returns the `user`, `csrf_token`, `expires_at`, and `idle_timeout` (seconds), and sets the cookie. `401` for wrong credentials, `429` when throttled. |
| POST | `/auth/logout` | session + CSRF, no license needed | Ends the session and clears the cookie. Returns `204`. |
| GET | `/auth/session` | session, no license needed | The signed-in user, `csrf_token`, `expires_at`, and `idle_timeout` (seconds). |

### Users

Admins manage every account. Managers list accounts, create operators, and deactivate or reactivate them.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/users` | session | List accounts, by username, as a page (see Pagination). Admins and managers; `403` for operators. |
| POST | `/users` | session + CSRF | Create a user. Body `{username, password, role}`. Admins create any role; managers create operators only. Returns `201`; `422` for a blank or taken username. |
| PATCH | `/users/{user_id}` | session + CSRF | Change `role`, set `active`, or reset `password`. Omitted fields are unchanged. Managers may only set `active`, on operators. Deactivating or resetting a password ends that user's sessions. |
| DELETE | `/users/{user_id}` | session + CSRF | Delete a deactivated user. Admins only. Returns `204`; `409` if active or they created or hold tickets. |

Admins cannot change their own role or deactivate themselves. The last active admin cannot be demoted.

### Catalog

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/ticket-types` | session | List ticket types, by name, as a page (see Pagination). Every role may read them. |
| POST | `/ticket-types` | session + CSRF | Add a ticket type. Body `{name, price_minor, currency}`; `price_minor` is whole minor units (1250 is 12.50), 0 to 100000000000; `currency` is required and must be one of the currencies `GET /branding` lists (those of the configured languages' regions: `USD`, `RUB` and `AZN` by default, plus `KZT` once a `kk-KZ` language is configured). Admins and managers. Returns `201`; `422` for a blank or taken name (case-insensitive). |
| PATCH | `/ticket-types/{type_id}` | session + CSRF | Change `name`, `price_minor` or `currency`; omitted fields are unchanged. A type may keep a currency that is no longer offered, but not move to one. Admins and managers. Issued tickets keep their price. |
| DELETE | `/ticket-types/{type_id}` | session + CSRF | Remove a ticket type. Admins and managers. Returns `204`; issued tickets keep their price. |
| GET | `/visitor-types` | session | List visitor types, by name, as a page (see Pagination). Every role may read them. |
| POST | `/visitor-types` | session + CSRF | Add a visitor type. Body `{name, discount_percent}`; the discount is a whole number from 0 (the default) to 100. Admins and managers. Returns `201`. |
| PATCH | `/visitor-types/{type_id}` | session + CSRF | Change `name` or `discount_percent`; omitted fields are unchanged. Admins and managers. Issued tickets keep their discount. |
| DELETE | `/visitor-types/{type_id}` | session + CSRF | Remove a visitor type. Admins and managers. Returns `204`; issued tickets keep their discount. |

### Tickets

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/tickets` | session, or key `tickets:read` | List tickets, newest first (by readable serial), as a page (see Pagination). Optional filters: `?state=issued\|passed\|expired\|revoked` (only tickets in that state), `?search=` (serial, visitor, type or external code, up to 200 characters), `?external_code=` (exactly this code, up to 128 characters). Longer values are a `422`. Operators see only tickets assigned to them. |
| POST | `/tickets` | session + CSRF, or key `tickets:write` | Issue a ticket (see Create body below). Returns `201`; `422` for bad input or an unknown `ticket_type`; `409` if `external_code` is taken; `502` if BioStar fails. |
| GET | `/tickets/{ticket_id}` | session, or key `tickets:read` | One ticket. `403` for an operator if it is not assigned to them. |
| POST | `/tickets/{ticket_id}/assign` | session + CSRF | Body `{assignee}`: the username of an existing, active account to assign the ticket to. Admins and managers. `404` if the account does not exist, `409` if it is deactivated. |
| POST | `/tickets/{ticket_id}/pdf` | session + CSRF | Render the one-page A4 badge and return it as `application/pdf`. Counts as a print, and the file is also saved to `out/`. Issued tickets only (`409` otherwise). |
| POST | `/tickets/{ticket_id}/print` | session + CSRF | Print on the server's default printer. Needs `TIQR_SERVER_PRINTING=true` (`409` `server_printing_off` otherwise). Issued tickets only. Returns the updated ticket; `502` if the printer fails. |
| PATCH | `/tickets/{ticket_id}` | session + CSRF, or key `tickets:write` | Move `valid_from` / `valid_until` (end after start), synced to BioStar. Admins and managers. Issued, or passed and multi-use, tickets only; otherwise `409`. |
| POST | `/tickets/{ticket_id}/revoke` | session + CSRF, or key `tickets:revoke` | Cancel a ticket (`{"reason"}` optional, audited) and disable its BioStar user. Idempotent: a revoked ticket is returned as is. Expired is `409`; a BioStar failure is `502` and changes nothing. |
| POST | `/tickets/{ticket_id}/transfer` | session + CSRF, or key `tickets:write` | Move to another `event_session` (and optionally a new window), keeping id, state and audit history. |
| POST | `/tickets/{ticket_id}/reissue` | session + CSRF, or key `tickets:write` | Reissue a ticket in any state as the same ticket, back to issued; the window may move and must end in the future. This is also how a ticket is edited. Returns the ticket. |
| POST | `/tickets/batch` | session + CSRF, or key `tickets:write` | Body `{items, atomic}`. Always `200` unless the request is malformed; returns `{atomic, committed, created, failed, results}`, each result `created` / `replayed` / `error` / `rolled_back` / `skipped`. At most `TIQR_BATCH_MAX_SIZE` items. |
| GET | `/tickets/{ticket_id}/audit` | session, or key `tickets:read` | The ticket's audit trail, oldest first (admins and managers). |
| GET | `/passes` | session, or key `tickets:read` | The passage feed, in arrival order. Query `?after=` (the `next_cursor` of the last page read, default 0) and `?limit=` (1 to 500, default 500). Each record gives `event_id`, `ticket_id`, `external_code`, `event_time` (UTC, shown with `Z`), `point_id`, `point_name`, `direction` (`entry` or `exit`, when BioStar says), `granted` and `outcome`. A repeat with the same cursor returns the same records; a late event lands after the cursor it missed, so none are lost. Admins, managers and service keys with `tickets:read`; operators get `403`. |

#### Create body

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
- `ticket_type` is optional: the name of a catalog ticket type, which prices the ticket. A `visitor_type` from the catalog takes its discount off that price.
- `timezone` is optional. It defaults to the server's `TIQR_DEFAULT_TZ`.
- `external_code` is optional. It is the BioStar pass code, used unchanged; leading and trailing spaces are trimmed. Allowed formats: alphanumeric, up to 32 characters of letters, digits and hyphens; or numeric, exactly 12 or 16 digits with leading zeros kept. It must be unique per tenant, and the code of a revoked pass remains occupied. A code the readers cannot read is a `422` `credential_format`.
- `event_session` is optional (at most 200 characters).
- Names are at most 200 characters.

A ticket response contains `id`, `readable_serial`, `visitor_name`, `visitor_type`, `valid_from`, `valid_until`, `usage_type`, `state` (`issued`, `passed`, `expired` or `revoked`), `created_by`, `assigned_operator`, `created_at`, `passed_at`, `print_count`, `use_count`, `ticket_type`, `base_price_minor`, `discount_percent`, `price_minor`, `currency` (the price fields are null without a ticket type), `timezone`, `external_code` and `event_session`. All datetimes are shown in `timezone`.

### Service keys

Admins only, signed in with a session (a key cannot manage keys).

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/service-keys` | session + CSRF | Body `{name, scopes, acts_as?, expires_at?}`. Returns `201` with the key and its `secret`, shown once. `acts_as` is a username (default: the caller); `404` if it does not exist. |
| GET | `/service-keys` | session | Every key, without secrets. |
| POST | `/service-keys/{key_id}/rotate` | session + CSRF | Body `{grace_minutes}` (0 to 10080, default 60). Issues a successor with the same scopes and returns `201` with its `secret`; the old key works on for the grace period. |
| DELETE | `/service-keys/{key_id}` | session + CSRF | End a key at once. Returns the key; revoking a revoked key returns it unchanged. |

### Service-to-service calls

Send `Authorization: Bearer tqk_...` (or `X-API-Key`). A key acts as one account, so that role's limits
apply, within its scopes (`tickets:read`, `tickets:write`, `tickets:revoke`). It needs no session and no
CSRF token; browsers keep the cookie and `X-CSRF-Token`, unchanged. A wrong key is a `401`, never
a fallback to the cookie. Only hashes are stored.

### Idempotency

`POST /tickets` and `/tickets/{id}/reissue` take an `Idempotency-Key` header (per account). The same key
and body replays the first status and body with `Idempotent-Replayed: true`; the same key with another
body is `409`. Only successful answers are kept, so a refused request may be retried under its key.
In a batch, an item uses its own `idempotency_key`, or the header plus `:index`.

### Operations

Admins and managers.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/sync` | session + CSRF | Fetch and apply new access events now. Returns `{count}`; `502` if BioStar fails. |
| POST | `/cleanup` | session + CSRF | Remove finished tickets from BioStar now. Returns `{count}`; `502` if BioStar fails. |
| GET | `/stats` | session | Totals: `total`, `issued`, `passed`, `expired`, plus the same counts per visitor type under `visitor_types` (each split by ticket type) and per ticket type under `ticket_types`. `?since=YYYY-MM-DD&until=YYYY-MM-DD` (either optional, both inclusive) counts only tickets created on those days in `TIQR_DEFAULT_TZ`; an end before the start is a 422. |

Sync and cleanup share a lock with the scheduled jobs, so runs never overlap.

## Roles

| Role | Can |
| --- | --- |
| `admin` | Manage users (create, change role, deactivate, reset passwords, delete), licenses and service keys, plus everything a manager can do |
| `manager` | Assign tickets, change validity, revoke, transfer and reissue tickets, run sync, cleanup and stats, list users, create, deactivate or reactivate operators, and manage ticket types and visitor types |
| `operator` | Issue tickets; view, print, revoke and reissue only the tickets assigned to them |

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

## Postman and HTTP client

Ready-made requests live beside this file. Start the server, then:

- **Postman:** import `postman/tiqr.postman_collection.json`, set the `username` and `password` collection variables, run **Login** first, then the folders top to bottom.
- **HTTP client (JetBrains):** open `http/tiqr.http`, pick the `local` environment from `http/http-client.env.json`, put the `password` in `http/http-client.private.env.json` (not committed), run **Login** first, then the rest top to bottom.

Requests marked **[WRITE]** change data: use a test server. Activate a license first, or everything except health, branding, the auth calls and the license status, request-code and activation calls is refused. Don't share an export with a password filled in.

## Database

Schema 8 adds the `revoked` state, `external_code` (unique per `tenant_id` through a partial index), `tenant_id` and `event_session`. Schema 9 adds `audit_log`, `idempotency_keys` and `api_keys`. Both are reversible: `SQLiteRepository.downgrade(7)` undoes them (revoked tickets read as expired afterwards and the new columns and tables are dropped, so back the database up first).

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
