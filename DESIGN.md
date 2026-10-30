# TiQR design

## Authority and approved changes

The original checkout at commit `9175b0ca0602b56f22430f06b60d9fb2f87c5ad7`
is the reference. Citations below refer to **that revision**, not current file
positions. The user explicitly authorized overhauling this checkout in place;
the old source remains inspectable with `git show <revision>:<path>`.
Read before implementation: `docs/findings.md`, `docs/qr-algorithm.md`,
`docs/api-reference.md`, the BioStar client, QR, guests, events, and auth modules.
No live BioStar server was contacted.

Clarifications approved during this task:

- Payloads are **exactly 32 characters**: the `TiQR` prefix leaves room for a
  14-character base64url HMAC signature, keeping the reference signing algorithm.
- Both access-window endpoints are inclusive. Lazy expiration therefore uses
  `current UTC time > valid_until`, not `>=`.
- `tzdata` is allowed for cross-platform IANA zones; `uv_build` is allowed as the
  build-only backend. Other direct application/dev dependencies stay within the
  original permitted list.

The QR algorithm document in this checkout contained only five lines and no
implementation/vectors. The authoritative available vectors instead come from
`tests/test_qr_doc.py:19–37`; the implementation is `app/qr.py:43–112`.
The reference auth module does **not** hash individual passwords: its two shared
roles and cookie behavior (`app/auth.py:23–97`) are deliberately replaced with
individual Argon2id users and the required three-role permission matrix.

## Layers

1. Core (`apps/core`, `tiqr.core`): frozen dataclass models, authentication, settings,
   QR, PDF file generation, the OS print hand-off, local datetime input, repository and
   integration protocols, SQLite storage, fakes, BioStar adapters, `TicketService`, and
   `open_service`, which wires settings into a ready service for both adapters.
2. CLI (`apps/cli`, `tiqr.cli`): Typer parsing, local password prompts, formatting, and
   `tiqr serve`. It contains no state/permission decisions or SQL.
3. API (`apps/api`, `tiqr.api`): a FastAPI app over the same service. It turns a session
   cookie into the service's actor, maps core exceptions to HTTP statuses, protects browsers
   (CSRF, origin checks, headers, login limits), runs scheduled sync and cleanup, and serves
   the static web build. [DEPLOYMENT.md](DEPLOYMENT.md) describes how it is packaged and
   installed.

Each layer is a uv workspace member with its own dependencies. Only `core` holds domain
decisions; `cli` and `api` are adapters over it, and `core` imports neither. `cli` reaches `api`
only inside `tiqr serve`, so FastAPI's import cost stays off every other command. The web
framework and listener live in `api` alone; no ORM, UI, print queue or printer agent exists.
Endpoints are synchronous functions on FastAPI's thread pool: the core is synchronous, and the
repository and BioStar client each serialize their own access with a lock. The PyInstaller
executable under `packaging/` wraps all three and adds no behavior beyond first-run setup. The
HTTP **client** is exclusively an outbound BioStar adapter.

## Models and storage

- UUIDs identify local tickets and users; BioStar user IDs are separate strings.
- Readable serials use `TiQR-YYMMDD-NNNNN` and persistent, atomic daily counters.
  Dates for serial allocation are UTC. Capacity is 99,999 tickets per UTC day.
- `Ticket`, `User`, `AccessEvent`, and `SyncCursor` are dataclasses. Tickets are
  immutable snapshots. No public manual-pass or arbitrary state-update service exists.
- `Repository` is the boundary; `SQLiteRepository` uses only stdlib `sqlite3`.
  Repository state-column writes only serialize snapshots decided by the service;
  it never derives transitions, expiry, permissions, or event outcomes.
- UTC-aware ISO timestamps retain their offset in SQLite. Naive datetimes are
  rejected by the core. Local input/output conversion is confined to boundaries.
- Foreign keys, unique usernames/serials/payloads/external IDs/event IDs, enum
  checks, and nonnegative counter checks enforce persistence invariants.
- The schema is versioned through `PRAGMA user_version` and built by numbered migrations,
  each applied once in its own `BEGIN IMMEDIATE` transaction together with its version bump;
  the version is re-read inside that transaction, so two processes upgrading at once run each
  step once. A new database runs them all. An older one is refused until `tiqr setup`
  upgrades it, so it can be backed up first; a newer one is always refused. Version 2 adds
  `web_sessions`; version 3 adds `users.active`. The old application schema is refused rather than migrated. No existing
  user data is deleted.
- `BEGIN IMMEDIATE` serializes sync writers; event inserts, ticket effects, and
  cursor updates share one transaction. A reentrant lock supports threads using
  the same repository; SQLite serializes independent processes.
- Sequences are committed before remote registration. Cleanup metadata and
  internal card IDs live in repository integration tables, not ticket state.
  Removed external IDs remain on local tickets for late-event association.

## State and expiry

Only the domain service transitions state:

| From | To | Trigger |
|---|---|---|
| issued | passed | First applied granted event within inclusive window |
| issued | expired | Current UTC time is strictly after valid_until |
| passed | expired | Current UTC time is strictly after valid_until |

Every other transition, including reopening expired tickets, is illegal. Expiry
is final even if the clock later moves backwards.

**Lazy expiry** avoids a separate scheduler layer. Every domain read or write of
an existing ticket first checks expiry and persists it. Ticket lists and statistics
also refresh states. Sync and cleanup sweep all tickets so untouched records stay
current. The sweep commits before remote I/O: a failed fetch/removal does not undo
expiry. Passive repository reads are internal infrastructure, not user-facing
domain reads; directly querying SQLite does not invoke lazy expiry.

Creation rejects blank names/types, reversed or already-expired windows, invalid
usage types, and naive timestamps. A zero-duration window is legal at its one
inclusive instant. Creator and assignee are identical initially, regardless of role.
Validity boundaries require whole-second precision: the verified reference client
serializes windows as `.00Z` (`app/biostar.py:15–18`). Rejecting subsecond boundaries
prevents silently rounding and widening reader access relative to local validity.
Scan and audit timestamps retain their full source precision.

Events are processed in scan-time order within each fetched batch. Only grants
apply; denied events are audited as `denied` without changing passage counters.
A denial for an unknown user remains `denied` with a null ticket ID. Grant outcome
priority is: unknown ticket, expired, spent one-time, outside window, applied.
Lazy expiry may still occur while reading a ticket associated with a denial.
Already-expired tickets do not apply delayed historical grants, as required.

`passed_at` is the first applied event's scan time, not poll time. It remains
unchanged on subsequent grants. First application sets `use_count=1`; multi-use
applications increment it, keep state `passed`, and preserve the remote window.
Repeated event IDs make no changes, including denied and ignored events.

For one-time tickets the registrar disables the user before the local pass/event
transaction commits and before processing the next event. If disabling fails,
the event, pass and cursor roll back and retry on the next sync. If the remote
disable succeeded but commit failed, retrying the idempotent disable is safe.
Later grants are audited as `ignored_second_one_time_scan`, unless expired.
This cannot eliminate the reader-to-server delay observed in
`docs/findings.md:139–154,204–214`; no hardware anti-passback is assumed.

## Permissions and local authentication

All enforcement is in `TicketService`, which resolves actors from persisted
accounts rather than trusting a caller-supplied role. Admin/manager see all states;
operators see only currently assigned tickets. Admins and managers assign/reassign,
including tickets initially assigned to an admin/manager. Assignees can be any
existing account; the initial creator-role exception must not create nulls.

Every role may create. Statistics, sync and cleanup require admin/manager. Print
and unlimited reprint require visibility and `issued`; success increments only
`print_count`, never usage/state. Renderer failures do not increment print counts.
Ticket usage type cannot be changed, and users cannot cause a pass.

The library exposes username/password verification using Argon2id. An unknown username
still costs one Argon2 verification against a decoy hash, so response time does not reveal
which accounts exist. The CLI verifies
a hidden password for an `--as` command, then keeps a short-lived session for 5 minutes:
an HMAC over the user ID and expiry, keyed by `TIQR_SECRET_KEY`, in the git-ignored
`.tiqr-session.json` (mode `600`). The password is never stored, and the session is
accepted only for the same username, before expiry, and while that account exists.
The CLI uses no cookies and no server-side session state; the web API's sessions follow.
User add prompts with confirmation and rejects empty/whitespace passwords. Bootstrap
and account listing have no actor argument by specification and trust OS access. Their
authenticated counterparts, `create_user` (admins) and `list_accounts` (admins and managers,
who need it to pick assignees), back the web API.

Accounts are never deleted, since tickets and audit history reference them. `edit_user` (trusted
local) and `manage_user` (admins) change a role, the `active` flag, or the password hash, in one
transaction. A deactivated account fails `authenticate` after its password is checked, so only
its holder learns why; `_actor` refuses it, so a stale `User` object cannot act; and it cannot be
assigned tickets. Deactivation and password resets delete the user's web sessions, and the CLI
token signs the password hash, so a reset ends that too. Roles are re-read on every request.
The last active admin can be neither demoted nor deactivated; through the API, admins also
cannot change their own role or active state.

Browser sessions are server-side, unlike the CLI's. `open_web_session` stores a row keyed by
the SHA-256 of a 256-bit random token, with a separate random CSRF token; the token itself
exists only in the browser's `HttpOnly`, `SameSite=Strict` cookie, which is also `Secure` and
`__Host-` prefixed when the server has TLS. Plain HTTP is the default, as TiQR runs on the
customer's own network.
`resume_web_session` ends a session 30 minutes after its last request or 12 hours after login,
deleting the row; requests under a minute apart skip the seen-time write. Logout deletes the
row, and each login sweeps ended ones. The API layer checks the CSRF token on every write and
refuses cross-origin writes by `Origin`; these are transport checks, not domain decisions.

`scheduled_sync` and `scheduled_cleanup` are the actor-free entry points for the server's
scheduler, which runs in the trusted server process like the bootstrap commands. `sync` and
`cleanup` check the actor's role, then call them. The API serializes scheduled and on-demand
runs with one lock, so a slower run cannot store an older event cursor over a newer one.
The library's actor object represents the caller's authenticated principal; this
local library is not a sandbox against callers with direct database access.

Settings are explicit dataclasses or environment variables, optionally loaded from
`.env` then `.env.local` in the project root; real environment variables win. Secret validation
rejects empty and common placeholders at core and CLI startup. There is no fallback
key, demo mode, simulator selector, or second credentials-loading path. With zero
BioStar settings use the default in-memory protocols; otherwise require complete
configuration, including reader and access group. TLS verification defaults off; setting
`TIQR_BIOSTAR_VERIFY_TLS=true` enables it, against the operating system's trust store
(`httpx2` uses `truststore`), so a site's internal CA works once the OS trusts it.

## QR and PDF

Reference behavior: `app/qr.py:55–87,90–112`, `docs/findings.md:65–109,502–516`.
Sign the **full readable serial** using UTF-8 HMAC-SHA256, encode base64url without
padding, truncate to the approved 14-character signature. Payload:

```text
TiQR:YYMMDD-NNNNN:<14-character signature>
```

Length is 5 + 12 + 1 + 14 = 32. No UUID or personal data appears. Strict ASCII
patterns and byte-wise constant-time comparison reject malformed/Unicode signatures.
Tests pin five fixed vectors and assert every payload is exactly 32 characters.
The prefix is part of the signing input, so it must never change without re-issuing tickets.
The exact format has not been physically rescanned in this task.

PDF generation is core file output, not a queue. `tiqr.core.printer` hands a rendered file to
the operating system's print path; only the adapters call it, from a renderer passed to
`print_ticket`, so a print counts only once the system accepts the job. The service itself
never touches a printer. The web API offers browser download and, per site, the server's own
printer. ReportLab draws vector QR modules
with a quiet zone and renders name/type/validity/readable serial. Badge logos are
package resources copied from the reference assets; wheel tests require their
presence. A temporary closed file is atomically replaced into the final UUID path
for Windows compatibility. Reprints overwrite that path. Geist (TrueType, default
weight) is packaged with its SIL Open Font License for Azerbaijani/Cyrillic support, independently of
system font paths. Unsupported glyphs fail explicitly; font coverage is not universal.

The PDF is one A4 sheet laid out as a foldable badge. The left half (105 × 148.5 mm) holds the
front above and the back below, and is cut off and folded horizontally into a two-layer A6 badge
whose fold is at the bottom; the free ends meet at the top, where two holes are punched. Both
sides run from the outer sheet edge toward the fold (header and holes at the edge, footer at the
fold), so the lower half is drawn rotated 180°, as folding flips it. The right half is scrap
and carries the cutting instructions: a second badge cannot fill it because guests arrive one at
a time. A PDF rather than an image is kept, because the CLI hands the file to the system print
path, which rasterizes it for printers without PDF support. Labels are English. The visitor type
is the badge label and is printed as entered, never upper-cased, as Python's case mapping is
wrong for Azerbaijani `i`. The front has name, QR code and serial; the back has name and ticket type, as it
faces outward when the badge turns. Names shrink to fit and are then cut with an ellipsis, so
the layout is always exactly one page. Validity is shown to the minute as `dd.mm.yy · HH:MM`,
in the configured timezone, which is no longer printed itself.

## BioStar endpoints and fields

The following citations identify every implemented endpoint and request/response
field family. All paths omit trailing slashes. Numeric IDs/codes are normalized
from strings; a response must have a successful `Response.code` envelope and a
successful HTTP status. Authentication gets one retry after 401.

| Endpoint | Fields/behavior | Original source |
|---|---|---|
| POST /api/login | User.login_id/password, bs-session-id response header, Response.code/message | docs/api-reference.md:16–40; app/biostar.py:148–179,246–258 |
| POST /api/users | User.user_id/name/user_group_id.id/start_datetime/expiry_datetime/disabled/access_groups[].id; no permission; UserCollection.rows | app/biostar.py:483–498; docs/api-reference.md:95–123; docs/findings.md:80–82,106–109 |
| POST /api/cards | CardCollection.rows[].card_id/card_type.id/type, type 6; internal id from rows/Card/id shapes | app/biostar.py:408–435,619–635; docs/api-reference.md:158–185; docs/findings.md:71–78 |
| PUT /api/users/{id} | User.cards[].id assignment; User.start_datetime/expiry_datetime windows; User.disabled="true" deactivation | app/biostar.py:500–510; docs/api-reference.md:125–131; docs/findings.md:120–125 |
| DELETE /api/users?id=... | Space-separated user IDs, singleton cleanup, user before card | app/biostar.py:512–528; docs/findings.md:102–104,316–328 |
| DELETE /api/cards?id=... | Internal card IDs, deletion only after user; verified acknowledgement | app/biostar.py:442–458; docs/findings.md:102–104,626–636 |
| POST /api/v2/users/search | limit/search_text/order_by, UserCollection.rows[].user_id; limit=0 full verification | app/biostar.py:530–538 |
| GET /api/cards | limit/offset, CardCollection.rows[].id, paged cleanup verification | app/biostar.py:540–544 |
| GET /api/v2/cards/registered | card_id lookup; Card or collection response for missing creation ID | app/biostar.py:399–406; docs/api-reference.md:140 |
| GET /api/event_types | is_break_glass/setting_alert/setting_all; rows[].code/name/description | app/biostar.py:364–372; app/events.py:231–235 |
| POST /api/events/search | Query.limit/conditions(column,operator,values)/orders(column,descending); datetime BETWEEN (3), device_id EQUAL (0) | app/biostar.py:553–590; docs/api-reference.md:226–256 |

Event row field extraction follows `app/events.py:65–86,94–101`: id/event_id,
nested/flat device_id, user_id.user_id/id, event_type_id.code/id/name/description,
and datetime. Classification uses `app/events.py:34–53`: successful authentication
prefixes only, denial prefixes only, not ENROLL_SUCCESS or system events.
Always use scan `datetime`, **never** the misleading local `server_datetime` with
its Z suffix (`docs/findings.md:204–210`). Invalid scan IDs/timestamps fail the batch
rather than inventing a timestamp. Raw endpoint rows become `RawEvent`; the service
attaches the matched ticket ID and domain outcome to the audited `AccessEvent`.

## Integration lifecycle and recovery

One ticket creates a user with its window and configured group, a type-6 QR card,
and a separate internal-ID assignment. The service explicitly calls `set_window`
before committing the ticket, so registrar implementations must honor alignment.
Failure compensates in user-before-card order. IDs come from an atomically reserved,
persisted dedicated range and are never recycled, even after cleanup/failure:
`app/guests.py:119–127`; `docs/findings.md:192–197` explains reused-ID misattribution.
Keep the database and its sequence history; do not share this range.

Cleanup is operationally required because user creation slows as counts grow
(`docs/findings.md:243–300`). It removes **expired tickets and passed one-time
tickets**, leaving issued and unexpired passed multi-use tickets alone. Local
history is kept. Remote removal is user first, card second; absence is verified by
recorded reference search/list mechanisms, not just a successful envelope.
Removal progress is persisted between steps, so failed card deletion can retry
without recreating or reopening a user. Completed local cleanups are idempotent.

Polling cursor tokens record a UTC upper bound. On restart fetch the backlog from
the old bound with a 15-minute overlap for late events; the first fetch starts at
the earliest local ticket (or 15 minutes ago if none). Event-ID deduplication makes
overlap safe. Ascending time queries subdivide saturated ranges using documented
BETWEEN rather than inventing offset pagination. A full one-second bucket fails
closed and does not advance the cursor. Events delayed more than the overlap
require explicit cursor backfill; there is no undocumented real-time channel.

Remote network operations and SQLite cannot form a distributed atomic transaction.
Known internal card IDs/removal progress survive reopen. Lost creation responses,
termination before mapping persistence, or failed compensating cleanup require
operator reconciliation using the original failure notes. Core creation rejects
errors rather than presenting an unregistered ticket as successful. No full
cross-system crash reconciler is claimed.

## Deliberately excluded reference components

- app/main.py, server.py and all reference FastAPI routes, HTTP authentication, cookies and
  sessions. TiQR's own API in `apps/api` was written afresh over `TicketService`.
- app/static and browser pass/workstation/printing pages.
- app/printing.py queue and printer_agent USB/Windows printer operations.
- deploy, release ZIPs, and helper scripts.
- app/config.py/credentials.py alternate demo/live configuration paths.
- Reference ticket-type switching/reactivation and anti-passback provisioning.
- Museum, Ticketon, carts, subscriptions, reporting servers and unrelated application code.
- Original broad application specification and web/executable CI/build dependencies.

Retained reference material is limited to two badge logos and the four recorded
BioStar response fixtures with their provenance. Behavior was reimplemented in
TiQR's core structure; whole application files were not copied.

## Verification

Pytest covers state and illegal transitions, inclusive boundaries, scan outcomes,
expiry on reads/sweeps/failures, one-time/multi-use, dedupe and concurrency, every
role/action matrix cell, reassignment, printing/counters, cleanup, QR vectors,
timezone conversion including Asia/Almaty, password/secret refusal, SQLite restart,
BioStar recordings, CLI commands, PDFs, built-wheel resources and isolated imports, schema
migrations, web sessions, and every API endpoint, refusal and security header in-process
through FastAPI's TestClient.
CI uses Python 3.14 on Windows and Linux, with Ruff check and format checks plus
pytest and wheel builds. No tests require a live reader/server or physical printer.
