# TiQR

A Python 3.14 **core library, CLI and web API** for QR tickets registered with Suprema
BioStar X and scanned by XPass Q2 readers. SQLite keeps local history; the reader
enforces each ticket's UTC access window. PDF output is saved as a file; `ticket print` also
sends that file to the default printer. `tiqr serve` runs the same commands as a JSON API for
the planned Svelte frontend; see [Web API](#web-api), and
[DEPLOYMENT.md](DEPLOYMENT.md) for how the product is packaged and installed on customer servers.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```text
uv python install 3.14
uv sync --locked
```

Run the one-time setup, which creates the private signing key in `.env.local`
(git-ignored, mode `600`) and initializes the database:

```text
uv run tiqr setup
```

This writes a fresh `TIQR_SECRET_KEY` only when none is set or the value is empty or a
known placeholder; it never prints the key. The database is created if missing and
left alone otherwise, so running setup again is a no-op. Keep the same key and
database between runs. Nothing needs exporting; the CLI reads `.env.local`
on every run. To use a different key for one shell, set `TIQR_SECRET_KEY` in the
environment, which overrides the file.

Configuration comes from explicit `Settings` objects or environment variables. The CLI
also reads `.env` and then `.env.local` from the project root (the checkout that contains
`apps/`), not from the directory it is run in: `.env.local` wins over `.env`, and real
environment variables win over both. `.env` is committed and lists every key with blank
placeholders; a blank value counts as unset, so local mode works and CI can fill the
BioStar block in. `.env.local` is git-ignored and holds private values such as
`TIQR_SECRET_KEY` and `TIQR_BIOSTAR_PASSWORD`. `tiqr_brand.jsonc` (comments allowed) sits in the same folder and is required: the program
does not run without it. It holds the name, logo, theme and languages (the web app reads them from
the server at load, so one build serves any of them) and may also set the other non-secret keys:
`prefix`, `default_tz`, the server's `host`, `port`, `tls_cert`, `tls_key`,
`server_printing`, and a `biostar` block. Each is the
`TIQR_*` setting of the same name; the file wins over `.env` and `.env.local`, real environment
variables win over it, and `null` leaves a key to the layers below. `TIQR_SECRET_KEY` and the
BioStar password are refused there. `theme` is `default` (the Vintage theme) or any Skeleton theme
name, and a visitor's browser language is shown when `languages` offers it; otherwise the first of `languages` is shown. A partly filled BioStar block is an error.
An installed service sets `TIQR_HOME` in its real environment instead, and the project root
becomes that folder: config, database, PDFs and the CLI session then stay put while release
folders change. It cannot be set in `.env`, which is found through it.
No demo flag or simulator switch exists.

Production sets `TIQR_BIOSTAR_REQUIRED=true` in its real environment. Then a missing
BioStar block stops every command instead of falling back to local mode. Do not put this
flag in `.env`, because local mode must keep working.

| Variable | Default / requirement |
|---|---|
| `TIQR_HOME` | Unset; when set, the project root for every relative path and `.env` file |
| `TIQR_SECRET_KEY` | Required, private non-placeholder signing key |
| `TIQR_DEFAULT_TZ` | This machine's IANA zone when blank, else `UTC` |
| `TIQR_PREFIX` | `TQR`; any three printable ASCII characters except `:` and `-`, prefixing new readable serials and QR payloads |
| `TIQR_BIOSTAR_BASE_URL` | HTTPS host URL, optionally ending in `/api` |
| `TIQR_BIOSTAR_USERNAME` | BioStar account username |
| `TIQR_BIOSTAR_PASSWORD` | BioStar account password |
| `TIQR_BIOSTAR_DEVICE_IDS` | Comma-separated existing reader IDs, at least one |
| `TIQR_BIOSTAR_ACCESS_GROUP_ID` | Optional existing access group ID; blank lets `tiqr setup` manage a group named `TiQR AG` |
| `TIQR_BIOSTAR_VERIFY_TLS` | `false`; set `true` to verify the server's TLS certificate against the operating system's trust store, where an internal CA can be installed. Verification is off by default, so enable it for any server reached over an untrusted network |
| `TIQR_BIOSTAR_TIMEOUT` | `30` seconds |
| `TIQR_BIOSTAR_DOOR_OPEN_DURATION` | `3` seconds a door stays unlocked; applies to doors `tiqr setup` creates |
| `TIQR_BIOSTAR_DOOR_OPEN_TIMEOUT` | `10` seconds a door may stay open before BioStar flags it; applies to doors `tiqr setup` creates |
| `TIQR_BIOSTAR_REQUIRED` | `false`; `true` makes a missing BioStar block a startup error |
| `TIQR_HOST` | `127.0.0.1`; the address `tiqr serve` binds. Use the server's LAN IP, not `0.0.0.0` |
| `TIQR_PORT` | `7102` |
| `TIQR_TLS_CERT`, `TIQR_TLS_KEY` | Optional PEM certificate and key, relative to the project root; both set serves HTTPS |
| `TIQR_SERVER_PRINTING` | `false`; `true` lets operators print on the server's default printer from the web UI |

With **no** BioStar settings, in-memory registrar and event-source fakes are the
defaults. Supplying BioStar settings requires the base URL, username, password and at least one
device ID; partial or empty configuration fails instead of silently using fakes. Only enable
live settings for the intended server. Changing the database file, deleting sequence records,
or sharing the ID range with another application risks reusing remote IDs. Reserve
the range and keep database backups. The CLI never deletes doors, access levels or access groups.

### BioStar access group

The BioStar account in `TIQR_BIOSTAR_USERNAME` is the single admin TiQR signs in with;
TiQR's own admin, manager and operator accounts live in SQLite (`tiqr user add`) and are
unrelated to it. A BioStar reader reaches users through this chain: access group, access
level, door, reader. Every ticket user joins one access group.

- **`TIQR_BIOSTAR_ACCESS_GROUP_ID` set:** `tiqr setup` only checks that the group exists
  and changes nothing. The group must already cover your readers.
- **Blank:** `tiqr setup` creates the group, one access level and one door per reader in
  `TIQR_BIOSTAR_DEVICE_IDS`: the group is `TiQR AG`, the level is `TiQR AL`, and the doors
  are `TiQR <device id>`. It uses the built-in Always schedule. Rerunning it fills gaps, so adding a device ID and running
  `tiqr setup` again adds that reader's door to the level. Ticket commands find the group
  by its name, so run `tiqr setup` before the first ticket.

The door request follows the BioStar X API reference but has not been run against a live
server by the test suite, and the exit-button and sensor inputs are defaults. Check the
result in BioStar after the first setup.

## Commands

`uv run tiqr --help` and each subcommand's `--help` show usage.
Actor commands prompt for that user's password; `--as` is not an authentication bypass.
Passwords are hashed with Argon2id. After a successful login, the same user's next actor
commands skip the prompt for 5 minutes. That login is kept in `.tiqr-session.json`
(git-ignored, mode `600`), as a token derived from `TIQR_SECRET_KEY`; the password is never
written to disk. Any other user, or a command after the 5 minutes, prompts again.

```text
uv run tiqr user add admin --role admin
uv run tiqr user add manager --role manager
uv run tiqr user add operator --role operator
uv run tiqr user list
uv run tiqr user role operator manager
uv run tiqr user deactivate operator
uv run tiqr user activate operator
uv run tiqr user delete operator
uv run tiqr user password operator

uv run tiqr ticket create --name "Adam Tələbə" --type Student --from "2030-06-01T09:00:00" --until "2030-06-01T18:00:00" --usage one_time --as operator
uv run tiqr ticket create --name "Guest" --type Guest --from "2030-06-01T09:00:00" --until "2030-06-01T18:00:00" --usage multi_use --tz Asia/Almaty --as manager
uv run tiqr ticket list --as operator
uv run tiqr ticket list --state issued --as manager
uv run tiqr ticket save <ticket-uuid> --as operator
uv run tiqr ticket print <ticket-uuid> --as operator
uv run tiqr ticket assign <ticket-uuid> operator --as manager
uv run tiqr sync --as manager
uv run tiqr cleanup --as admin
uv run tiqr stats --as manager
uv run tiqr stats --since 2026-09-01 --until 2026-09-30 --as manager
```

Replace `<ticket-uuid>` with the ID returned by creation. `ticket save` and `ticket print`
write `./out/<ticket-uuid>.pdf`; `ticket print` then sends that file
to the default printer. The PDF
is a foldable badge with name, visitor type, validity, a QR code, and the readable serial,
with packaged badge logos. Printing is unlimited while the ticket is `issued` only;
every successful generation increments `print_count`.

Naive ISO datetimes use `--tz`, falling back to `TIQR_DEFAULT_TZ`; explicit offsets
are honored. Access windows require whole-second precision to match the verified
BioStar format without silently rounding. Storage is timezone-aware UTC.
Ambiguous/nonexistent local times need an explicit offset. Output uses the
configured timezone. `tzdata` supplies the same IANA database on Windows and Linux.

`setup`, `reset`, and the `user` commands are **trusted local bootstrap commands**:
the specification has no `--as` for these. Protect database and shell access with
OS permissions. This is not a security boundary against somebody who can edit SQLite.
The web API's user endpoints are the authenticated counterparts; see
[Permissions](#permissions). Reference-application databases are refused.

Schema changes are never applied implicitly. A database with an older schema stops every
command with a message to back it up and run `tiqr setup`, which upgrades it in numbered,
one-transaction steps. A database newer than the program is always refused, so a downgrade
past a schema change fails instead of corrupting data.

### Starting over

```text
uv run tiqr reset
```

Deletes `TIQR_SECRET_KEY` from `.env.local` and the database (after a confirmation
prompt; `--yes` skips it), then `uv run tiqr setup` starts fresh. All users and tickets
are lost and printed QR codes stop verifying. BioStar is not touched and PDFs in the
output directory are kept.

### Permissions

| Action | Admin | Manager | Operator |
|---|---|---|---|
| Create | Yes | Yes | Yes |
| View | All tickets | All tickets | Assigned tickets only |
| Assign/reassign | No | Yes | No |
| Statistics, sync, cleanup | Yes | Yes | No |
| Print/reprint | Visible issued tickets | Visible issued tickets | Assigned issued tickets |
| Add users, deactivate, reactivate (web) | Yes, except their own active state | Operators only | No |
| Change roles, reset passwords, delete deactivated users (web) | Yes, except their own role | No | No |
| List users (web) | Yes | Yes, to pick assignees | No |
| Create, edit, delete ticket types and visitor types (web) | Yes | Yes | No |
| Read ticket types and visitor types (web) | Yes | Yes | Yes, to issue tickets |

A deactivated account keeps its tickets and history but cannot sign in, act, or be assigned
tickets; a manager can reassign its tickets. Only a deactivated account can be deleted, and only
if it never created or held a ticket; otherwise it stays, deactivated. Deactivating a user or resetting their password ends
all their sessions, web and CLI. A new role applies from the user's next request. The last active
admin can be neither demoted nor deactivated, by the web or the CLI, so somebody can always
manage accounts.

The creator is always the initial assignee, regardless of role. An admin or manager may
assign to any existing account. Ticket usage types cannot be changed after issuance.

### Example session with the defaults

Leave every `TIQR_BIOSTAR_*` variable unset and run the bootstrap, creation, list,
print, sync, cleanup, and stats commands above. Local records persist between CLI
runs, but the in-memory hardware fakes do not: an empty fake event source makes
`sync` a no-op. To exercise a granted scan without hardware, use the core library:

```python
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

from tiqr.core.models import RawEvent, Role, UsageType
from tiqr.core.repository import SQLiteRepository
from tiqr.core.service import TicketService
from tiqr.core.settings import Settings

settings = Settings.from_env()
repo = SQLiteRepository(":memory:")
repo.initialize()
service = TicketService(repo, settings.secret_key)
try:
    manager = service.add_user("manager", "local-example-password", Role.MANAGER)
    operator = service.add_user("operator", "different-example-password", Role.OPERATOR)
    now = datetime.now(UTC).replace(microsecond=0)
    ticket = service.create_ticket(
        operator,
        visitor_name="Example Guest",
        visitor_type="Guest",
        valid_from=now,
        valid_until=now + timedelta(hours=1),
        usage_type=UsageType.ONE_TIME,
    )
    with TemporaryDirectory() as directory:
        from pathlib import Path

        print(service.print_ticket(operator, ticket.id, Path(directory)))
    service.event_source.events.append(RawEvent("scan-1", ticket.external_id, now, True))
    assert service.sync(manager) == 1
    assert service.sync(manager) == 0
    assert service.get_ticket(operator, ticket.id).passed_at == now
    assert service.registrar.deactivated == [ticket.external_id]
    assert service.cleanup(manager) == 1
    print(service.stats(manager))
finally:
    repo.close()
```

## Web API

```text
uv run tiqr serve                                         # HTTP on TIQR_HOST:TIQR_PORT, 127.0.0.1:7102
uv run tiqr serve --tls-cert cert.pem --tls-key key.pem   # HTTPS; or TIQR_TLS_CERT / TIQR_TLS_KEY
uv run tiqr serve --dev                                   # adds the API docs, loopback only
```

`tiqr serve` runs one Uvicorn process. It serves the JSON API under `/api` and, when a web build
is bundled, the Svelte app under `/tiqr`, with `index.html` as the fallback there; `/` redirects
to `/tiqr/`. It checks
the settings and database before it listens, so a bad key or an outdated schema fails at once.
TiQR runs entirely on the customer's network, so plain HTTP is the default; with a certificate
and key it terminates TLS in-process instead. Over HTTP, passwords and session cookies cross that
network unencrypted. `--dev` only binds a loopback address and is the only mode that serves the
interactive docs at `/api/docs`.
Run one server process per database: scheduling, login limits and the sync lock live in it.

| Method and path | CLI equivalent | Who |
|---|---|---|
| `GET /api/health` | — | Anyone; returns the version, or 503 if the database or scheduler is down |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/session` | `--as` | — |
| `GET /api/config` | — | Signed in; default timezone and server printing |
| `GET /api/users`, `POST /api/users` | `user list`, `user add` | See [Permissions](#permissions) |
| `PATCH /api/users/{id}` with any of `role`, `active`, `password` | `user role`, `user deactivate`, `user activate`, `user password` | Admins; managers change `active` for operators |
| `DELETE /api/users/{id}` | `user delete` | Admins; deactivated users without tickets |
| `GET /api/ticket-types` | — | Any signed-in role |
| `GET /api/visitor-types` | — | Any signed-in role, and service keys with `tickets:read` |
| `POST /api/ticket-types`, `PATCH`/`DELETE /api/ticket-types/{id}` | — | Admins and managers; a ticket type has a price |
| `POST /api/visitor-types`, `PATCH`/`DELETE /api/visitor-types/{id}` | — | Admins and managers; a visitor type has a discount |
| `GET /api/tickets?state=`, `POST /api/tickets`, `GET /api/tickets/{id}` | `ticket list`, `ticket create` | As the CLI; `POST` also takes an optional `ticket_type` and `external_code` |
| `POST /api/tickets/batch` | — | Admins, managers and operators; up to `TIQR_BATCH_MAX_SIZE` tickets, `atomic` all or nothing |
| `PATCH /api/tickets/{id}` | — | Admins and managers; moves the validity window, synced to BioStar |
| `POST /api/tickets/{id}/revoke` | — | Admins and managers; idempotent, `409` for an expired ticket |
| `POST /api/tickets/{id}/transfer`, `POST /api/tickets/{id}/reissue` | — | Admins and managers; reissue also brings an expired ticket back |
| `GET /api/tickets/{id}/audit` | — | Admins and managers |
| `POST /api/tickets/{id}/assign` | `ticket assign` | Admins and managers |
| `POST /api/tickets/{id}/pdf` | `ticket save` | Returns the PDF and keeps it in `out/` |
| `POST /api/tickets/{id}/print` | `ticket print` | Server printer; `409` unless `TIQR_SERVER_PRINTING` |
| `GET /api/passes` | — | Admins, managers and service keys with `tickets:read`; the passage feed, read by `after` cursor |
| `POST /api/service-keys`, `GET /api/service-keys`, `POST /api/service-keys/{id}/rotate`, `DELETE /api/service-keys/{id}` | — | Admins only, signed in; a key acts as one account, within its scopes |
| `POST /api/sync`, `POST /api/cleanup`, `GET /api/stats` | `sync`, `cleanup`, `stats` | Admins and managers |

Service keys (`Authorization: Bearer tqk_...`) let an integration call the ticket endpoints without a
session or CSRF token. Their scopes are `tickets:read`, `tickets:write` and `tickets:revoke`. A wrong
key is `401`, and the key is never second-guessed by a cookie. Only the key's hash is stored.

Prices are whole minor units (cents): `price_minor` 1250 is 12.50. Naming a `ticket_type` when
creating a ticket prices it, and a `visitor_type` that matches one defined in the catalog takes its
`discount_percent` off that price, rounding half up; any other visitor type is kept as written, at
no discount. The ticket keeps the name, base price and discount it was made with, so editing or
deleting a type later never changes issued tickets. Names are unique whatever their case.

Rendering a PDF is a `POST` because every render counts as a print. Ticket bodies take the CLI's
datetime rules: an ISO datetime with an offset, or without one in `timezone` (default
`TIQR_DEFAULT_TZ`). Responses show datetimes in that zone, with their offset, and never include
password hashes, QR payloads or BioStar IDs. Refusals are `{"detail": ..., "code": ...}`: `401`
signed out, `403` forbidden, `404` not found, `409` wrong state, `422` invalid, `429` too many
logins, `502` BioStar or server printer failure. The `409` codes are told apart: `external_code_taken`,
`idempotency_mismatch`, `invalid_state`, and `conflict` for the rest. A `422` with `credential_format`
means an `external_code` the readers cannot read. Schema errors use FastAPI's `422` list format, and
unexpected errors answer `500` without details, which go to the server log. Every response carries an
`X-Request-Id`, which a caller may set to trace an incident.

Signing in creates a server-side session in SQLite; only a SHA-256 hash of its random token is
stored. The browser holds the token in an `HttpOnly`, `SameSite=Strict` cookie named
`tiqr-session`, with no expiry of its own; under TLS it is also `Secure`, named
`__Host-tiqr-session`, and responses add HSTS. A
session ends after 30 minutes without a request, after 12 hours regardless, or at logout, which
deletes it on the server. Login responses and `GET /api/auth/session` return a CSRF token that
every `POST` and `PATCH` must send as `X-CSRF-Token`; writes whose `Origin` is another site are refused, and
JSON bodies need a JSON `Content-Type`. Five failed logins for one username from one address, or
twenty from one address, wait 15 minutes; a username alone is never locked, so nobody can lock an
account out from elsewhere. An unknown username costs the same password hash as a wrong password,
so timing does not reveal which accounts exist.

`apps/api/openapi.json` is the API's OpenAPI schema for generating the web client. After changing
the API, regenerate it with `uv run poe openapi`; a test fails while it is stale.

## Web app

The Svelte UI in `apps/web` talks to the API. A source checkout has no bundled build, so
develop with two processes: the API on `:7102`, and the Vite dev server, which proxies `/api`
to it.

```text
uv run tiqr serve                  # terminal 1: API on 127.0.0.1:7102
cd apps/web && bun i && bun dev    # terminal 2: UI at http://localhost:5173/tiqr/
```

Sign in with an account from `tiqr user add`. Each role lands on the Tickets page at `/`
(under `/admin`, `/manager` or `/operator`).

The Tickets page:

- **Header:** the title, a refresh button, and a **New ticket** button.
- **Toolbar:** filter tabs for All and each ticket state, plus a search box that matches
  serial, visitor name, visitor type and ticket type.
- **Table**, newest first, with sortable headers. Columns: serial (with an icon for one-time
  or multi-use), visitor, valid from and until, state badge with first-passage time, price with
  discount and ticket type, print and door-use counts, assignee (staff only), and actions.
- **Actions:** download the PDF, print the PDF in the browser, print on the server
  (only when `TIQR_SERVER_PRINTING=true`), and assign (admins and managers). Download and print are
  enabled only for `issued` tickets.

Operators see only their own tickets. Managers and admins see all tickets, and admins and managers can
assign them. The UI has light and dark themes and is available in English, Azerbaijani,
Kazakh and Russian.

For a production-style run from the built UI, `bun bundle` in `apps/web` writes `build/`.
Release builds copy that folder to `apps/api/src/tiqr/api/web`, which `tiqr serve` then serves
under `/tiqr/`. The folder is git-ignored, so copy it by hand only for a local test.

## Printing

`uv run tiqr ticket save` only writes a PDF file. `uv run tiqr ticket print` writes the same
file and then sends it to the default printer through the operating system:

- **Linux:** CUPS `lp` with `print-scaling=none`, so the page prints at 100%. Linux needs the
  CUPS client tools installed.
- **Windows:** [SumatraPDF](https://www.sumatrapdfreader.org/) when it is installed, found on
  `PATH` or in its default folder under `%LOCALAPPDATA%` or `%ProgramFiles%`. TiQR runs it with
  `-print-to-default -print-settings noscale -silent`, which prints silently at 100%. Without
  SumatraPDF, TiQR uses the shell's print verb, which hands the job to whatever application is
  associated with `.pdf`. That application decides whether the job prints silently, and the
  command returns once the job is queued, so a job that fails later at the printer is not
  reported.

TiQR has no print queue or printer driver of its own. The print count rises only after the
system accepts the job, so a failed print leaves it unchanged. The saved PDF is kept either way.
The web API offers both paths: the browser downloads the PDF for the operator's own printer,
and, with `TIQR_SERVER_PRINTING=true`, the same OS print path runs on the server's default
printer.

Each PDF is one A4 sheet holding a single foldable badge (not to scale):

```text
       105 mm      105 mm
    ┌──────────┬──────────┐  <- sheet edge: punch holes here
    │   FRONT  │          │
    │          │  scrap   │
    ├┄┄┄┄┄┄┄┄┄┄┤          │  <- fold, at the bottom of the badge
    │   BACK   │          │
    │  (180°)  │          │
    └──────────┴──────────┘  <- other end, same holes
                ↑ cut
```

1. Print the sheet at 100% on A4 and cut along the vertical line. The right half is scrap, as
   guests arrive one at a time and there is no second badge to fill it.
2. Fold the left half along the horizontal dashed line. The fold ends up at the bottom of the
   badge, and the two free ends meet at the top.
3. Punch two holes through both layers at the circles on the front and thread the chain.

The result is a two-layer 105 × 148.5 mm (A6) badge. The back is printed upside down, so after
folding it reads correctly from behind. Instructions in the scrap half repeat these steps.

The front, from the top edge down, shows:

1. The hole guides, then a navy `TiQR` band with a turquoise and a crimson stripe.
2. The Distechsol and Suprema logos.
3. The visitor type in a crimson chip, and the visitor name in bold, in up to two lines.
4. A panel with the QR code, drawn as vector graphics with a quiet zone, and the readable
   serial (`TQR-YYMMDD-NNNNN`).
5. The validity window in the configured timezone, such as `01.06.30 · 09:00 — 18:00`, or
   `01.06.30 · 09:00 — 02.06.30 · 18:00` across days.
6. A navy footer, `Suprema BioStar X`, next to the fold.

The back repeats the header and logos, with the type chip and the name in up to three lines
centred below them, and the same footer. It has no QR code, so the name stays readable when the
badge turns around.

The labels are in English because visitors include foreigners. Names and types are printed as
entered, in the packaged Geist font, which covers Azerbaijani and Cyrillic; bold is the same
weight with a stroke added, as the font has one weight. A character the font cannot draw stops
the render with an error. The file is not written, and any existing PDF for that ticket is left
unchanged. A long name first shrinks, then, below 4.2 mm, is cut with `…` rather than overflow
the badge. A type too long for its chip is cut the same way.

Print at 100% (actual size) so the layout keeps its size and the folded badge matches the
printed cut and fold lines. "Fit to page" scaling changes that. `ticket print` requests this on
Linux and, with SumatraPDF, Windows. Without SumatraPDF on Windows, set the PDF
application's print scaling to 100% or "Actual size". Inkjet printers often cannot print the
bottom 14 mm of a sheet, so the back's header keeps 18 mm clear of that edge.

Reprinting uses the same command and replaces the file at the same path. The rules for
when a ticket may be printed, and what `print_count` records, are described under
[Commands](#commands).

## Operations

`tiqr serve` runs `sync` every 60 seconds and `cleanup` every hour, both once at startup,
through the service's `scheduled_sync` and
`scheduled_cleanup` entry points. Those take no actor: like the bootstrap commands, they trust
their in-process caller. Failures are logged and retried on the next run. Without a running
server, schedule the CLI's `sync` and `cleanup` yourself; CLI actor commands prompt
interactively, and an embedded application can authenticate once and call the core methods
directly. Do not skip cleanup: BioStar user creation gets slower as
users accumulate. Cleanup deletes remote users and cards for expired tickets and
passed one-time tickets, but retains local tickets and events permanently.

One-time cards are disabled immediately when their first grant is processed.
Polling and reader propagation still have an unavoidable delay; this is **not**
a hardware guarantee against two scans before sync catches up. A single reader
cannot use anti-passback. Multi-use passes remain usable until expiry.

Expiry is lazy on every domain ticket read/write and global on sync/cleanup/stats.
The inclusive endpoint decision means expiration occurs when `now > valid_until`.
A delayed grant processed after local expiry is audited as `ignored_expired`, even
if its scan timestamp was within the original window.

Live polling resumes from a persisted UTC cursor and overlaps 15 minutes to capture
late events. A saturated one-second event bucket fails closed rather than advancing
past potentially missing scans. See [DESIGN.md](DESIGN.md) for reference citations,
recovery boundaries, and the 32-character QR payload.

## Development and distribution

```text
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv build --all-packages --wheel
uv run poe openapi   # after API changes
```

### Git hooks

Install the hooks once per clone (they stay in `.git/hooks` after that):

```text
uv run lefthook install
```

- **commit-msg:** `cz check` requires a conventional commit message (`feat: ...`, `ci: ...`).
- **pre-commit:** ruff lint, `ruff format --check`, and `pyright`, without changing files. Run `uv run poe fix` to apply ruff's fixes and formatting, then run `pyright`.
- **pre-push:** `pytest`.

Git clients that start without `~/.local/bin` on `PATH`, such as PyCharm's, can't find
`uv` and fail the hooks. If that happens, create a git-ignored `lefthook-local.yml` that
adds the directory containing `uv` to `PATH` for each hook command:

```yaml
commit-msg:
  commands:
    commitizen:
      env:
        PATH: /path/to/uv/bin:$PATH
pre-commit:
  commands:
    lint:
      env:
        PATH: /path/to/uv/bin:$PATH
    format:
      env:
        PATH: /path/to/uv/bin:$PATH
    typecheck:
      env:
        PATH: /path/to/uv/bin:$PATH
pre-push:
  commands:
    test:
      env:
        PATH: /path/to/uv/bin:$PATH
```

Run `dirname "$(command -v uv)"` in a terminal to find that directory.

CI runs those checks on Python 3.14 on Windows and Linux. Tests use in-memory
hardware fakes or recorded BioStar response bodies, never a live server. Packaging
tests build every member's wheel and check its assets, imports, and scope in isolation.

### Layout

The repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/).
The root `pyproject.toml` holds the product version and shared tool settings; it is never built
itself. Each member is its own distribution, and all of them share the `tiqr` import namespace:

| Path | Distribution | Import | Contents |
|---|---|---|---|
| `apps/core` | `tiqr-core` | `tiqr.core` | Models, service, SQLite, BioStar adapters, QR, PDF, OS printing, assets |
| `apps/cli` | `tiqr-cli` | `tiqr.cli` | Typer commands, `tiqr serve`, and the executable's launcher |
| `apps/api` | `tiqr-api` | `tiqr.api` | FastAPI app, sessions, scheduler, the bundled web build's host, and `openapi.json` |
| `apps/web` | — | — | Svelte + Vite web UI; see its README |
| `packaging/` | — | — | PyInstaller spec and entry script |
| `tests/` | — | — | `core/`, `cli/`, `api/` and packaging tests, sharing one `conftest.py` |

Dependencies point one way: `api` uses `core`; `cli` uses `core`, and `api` only inside
`tiqr serve`, which imports it when it runs; `core` imports neither. The packaging tests enforce
this and keep web frameworks out of `core` and `cli`. Every member's version must match the
root's. There is no browser UI, print queue, printer driver, or reference helper-script build
yet.

### Executables

`packaging/tiqr.spec` builds one file with PyInstaller: `tiqr.exe` on Windows and `tiqr`
on Linux. PyInstaller cannot cross-compile, so build on the platform you target:

```text
uv sync --locked
uv run pyinstaller packaging/tiqr.spec --noconfirm
```

The **Executables** workflow (`.github/workflows/executables.yml`) runs the CI tests, then builds
the executable on Windows and Linux and smoke-tests each one from an empty folder, then assembles
the install archive (see [Installing a release](#installing-a-release)) and tests it as a customer
unpacks it. CI holds no vendor key, so the smoke test checks that unlicensed work is refused.
Builds from `prod` or a `v*` tag upload the archives as 7-day artifacts; a manual run on any other ref
only builds and tests. The executable contains Python, the fonts and logos, and
the time zone data. Its config and data live beside it, not in a temporary folder:
`.env.local`, `tiqr.db` and `out/` appear in the folder that holds the executable. Copy
your own `.env.local` there to supply BioStar settings, and put `tiqr_brand.jsonc` there too: the
executable refuses to run without it. Secrets are never built in.

- **Windows:** double-clicking `tiqr.exe` runs setup when needed, then opens a terminal
  window in its folder that runs the CLI.
- **Linux:** double-clicking opens a terminal window when the file manager runs the file
  in a terminal; otherwise run `./tiqr` from a terminal.

Any run with arguments, or from a terminal, first runs `setup` when the signing key or
database is missing, then runs the CLI. `setup`, `reset` and `--help` never run it. `tiqr serve`
works the same way and serves from that folder. The executable bundles the web build, which the
Executables workflow compiles in before PyInstaller runs.

### Installing a release

Each release carries one archive per OS, `tiqr-Linux-X64.tar.gz` and `tiqr-Windows-X64.zip`,
holding the executable, `tiqr_brand.jsonc`, `INSTALL.txt`, `THIRD-PARTY-NOTICES.txt` and an
install script (plus WinSW on Windows). Unpack it and run the script as an administrator:

```text
sudo ./install.sh          # Linux: program to /opt/tiqr, data to /var/lib/tiqr
install.cmd                # Windows: program to C:\Program Files\TiQR, data to C:\ProgramData\TiQR
```

It runs `tiqr install`: address, port, first admin, firewall and the boot-time service. A rerun from
a newer archive upgrades the program and keeps the data, branding and license. `tiqr selftest`
renders a sample badge to prove the bundled assets are intact.

The program does nothing until a license is activated. The install ends by printing a request
code. Send it to the vendor, who answers with a key (`tools/issue_license.py`); the admin pastes
it into the **License** page, or runs `tiqr license activate --as <admin> <key>` (or `--file`).
`tiqr license request-code` prints a new code and `tiqr license status` shows the
holder and expiry. Every CLI command that touches tickets or the BioStar link checks the license, as
the API does; `user`, `setup`, `reset`, `install`, `selftest` and the `license` commands do not.

When a terminal run finds no users, it asks for the first admin's username and password
before the command runs, so the database always gets an admin on first use. Scripts with
no terminal are never prompted; they fail as usual if no users exist.

### Releases

The **CI** workflow (`ci.yml`) runs on pull requests and on pushes to `main` and `prod`.
A release is a commit on `main` whose message contains `[PROD]`, such as
`feat: init project [PROD]`:

1. **Prod** (`prod.yml`) waits for CI to pass on that push, then points the `prod` branch at
   the commit. If `prod` already exists and is not an ancestor of the commit, it leaves `prod`
   unchanged and warns, so an older run that finishes late cannot move it backwards.
2. Prod then dispatches **Executables** on `prod`. The push uses `GITHUB_TOKEN`, which does not
   start workflows by itself, so the dispatch is explicit.

To publish a GitHub release, push a `v*` tag whose version matches `version` in
`pyproject.toml`. The Executables workflow then attaches the archives
and a `SHA256SUMS` file to that release.
