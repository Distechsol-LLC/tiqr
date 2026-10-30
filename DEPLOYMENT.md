# TiQR packaging and deployment

How TiQR is built, shipped as a closed-source product, installed on a customer's server, and
updated. The customer never receives source code. Everything runs on their network, on a Linux
or Windows server at an address they choose.

Status: the repository is restructured for this design (see [Layout](README.md#layout)), and the
backend API and `tiqr serve` are implemented (see [Web API](README.md#web-api)). The local-mode
installer works on Linux and Windows, but its Windows steps have not yet been run on a Windows
host. The frontend, Nuitka builds, remote installer, signed releases and automatic backups
described here are **not implemented yet**; [Implementation plan](#implementation-plan) lists the
order.

## Recommendation in brief

- **One program, `tiqr`, per OS.** It holds the core, CLI, backend API, installer and the
  frontend's static files. Subcommands select the role: `tiqr serve` runs the API,
  `tiqr install` deploys, and the existing admin commands keep working.
- **Compiled with Nuitka**, not PyInstaller, for anything shipped to customers. The service gets
  a *standalone* (folder) build; the workstation installer gets a *onefile* build.
- **The frontend is static files the backend serves from the same origin.** It calls `/api/...`
  with relative URLs, so no IP or hostname is built into it and it needs no CORS.
- **The installer has two modes over one code path.** `tiqr install --local` installs on the
  machine it runs on. `tiqr install --host <ip>` copies the bundle over SSH, then runs
  `--local` on the target.
- **Releases are signed bundles.** The installer verifies the signature before anything touches
  the server, and an upgrade is the same install with automatic rollback.

## Artifacts

### Build shapes

Both shapes come from the same source and entry code:

| Shape | Used for | Why |
|---|---|---|
| Standalone folder (`tiqr/` with `tiqr` or `tiqr.exe` plus libraries) | The service on the server | Starts instantly and runs from a fixed path. A onefile build unpacks into a temp folder on every start, which is slow, leaves files behind, breaks on `noexec` `/tmp`, and is what antivirus flags most |
| Onefile (`tiqr-install`, `tiqr-install.exe`) | The admin's workstation | One file to double-click; it runs once and exits |

The web build is copied into the api package as package data before compiling, so it
sits inside the executable's folder and cannot drift from the API version.

### Release bundle

One zip per release, the same for every customer:

```text
tiqr-0.10.0/
├── tiqr-install                     # onefile installer for a Linux admin workstation
├── tiqr-install.exe                 # same, for Windows
├── payload/
│   ├── tiqr-0.10.0-linux-x86_64.tar.gz
│   └── tiqr-0.10.0-windows-x86_64.zip
├── SHA256SUMS                       # every file above
├── SHA256SUMS.sig                   # Ed25519 signature over SHA256SUMS
└── THIRD-PARTY-NOTICES.txt
```

Neither CI nor the bundle holds per-customer data or secrets. A per-customer license key is
issued separately by the vendor (see [Licensing](#licensing) and [Security risks](#security-risks)).

Nuitka, like PyInstaller, cannot cross-compile: each payload is built on a runner of its OS.
Build Linux binaries on the **oldest glibc you support** (for example in a `manylinux_2_28`
container or on Ubuntu 22.04), because a binary built on a newer distribution will not start on
an older one. Add `aarch64` payloads only if a customer needs them.

## One executable or several

| | One `tiqr` program (recommended) | Separate CLI, backend and frontend executables |
|---|---|---|
| Version skew | Impossible: CLI, API and UI are built, shipped and upgraded together | Each pair needs compatibility checks, and a half-finished upgrade can mix versions |
| Size | One embedded Python runtime and dependency set | The runtime and shared core are duplicated in every executable |
| Build, signing, antivirus | One artifact per OS to compile, sign and get allowlisted | Three |
| Shared code | Core is compiled once | Core is compiled into each and must match |
| Workstation copy | Contains the server code too | The CLI can leave the server out |
| Separate scaling or updates | No | Yes, but a single-server product rarely needs it |

The frontend is not a candidate for its own executable. It is static files. The only reason to
wrap it would be a desktop client (for example Tauri), and the one strong case for that is
[printing](#what-changes-when-tiqr-becomes-a-server).

Keep the source split into `core`, `cli` and `api` packages anyway, even though they ship as
one program. That split enforces the dependency direction and keeps web frameworks out of the
core; the packaging tests check both.

## Source protection

| Tool | What the customer can recover |
|---|---|
| PyInstaller (current) | Bytecode, which public tools (`pyinstxtractor` plus a decompiler) turn back into near-original source in minutes. **The executables built today effectively ship the source.** |
| Nuitka | Python translated to C and compiled to machine code. Recovering logic needs a disassembler and real effort. String constants, route names and the general structure stay visible |
| Cython on selected modules + PyInstaller | Similar to Nuitka for the compiled modules, and you must manage which ones |

Use Nuitka for every customer build. Keep PyInstaller only until the Nuitka build passes the
same smoke tests. Nuitka's commercial tier adds constant and data encryption if you need more.

No compiler makes code secret, though. Treat compilation as a speed bump. Licensing terms that
forbid reverse engineering, and keeping anything truly sensitive off the customer's machine,
are the real protection.

## Installer

### Modes

Today the installer runs from the unpacked bundle:

```text
sudo ./install.sh [tiqr install options]   # Linux: copies the program to /opt/tiqr, data to /var/lib/tiqr, then installs
tiqr_setup.exe                             # Windows: wizard that writes the branding file and logo, copies the program to C:\Program Files\TiQR, then runs tiqr install
tiqr install [options]                     # the program itself, run as admin from its own folder
```

`tiqr install` takes `--source` (where `tiqr_brand.jsonc` and WinSW are; default the executable's
folder), `--host`, `--port`, `--pass-webhook-url`, `--pass-webhook-secret`,
`--service/--no-service` and `--firewall/--no-firewall`. At a terminal it asks for anything missing,
including the pass webhook (the secret is hidden); scripts take the defaults, and a blank webhook
means none. Change the webhook later with `tiqr webhook set`, `tiqr webhook show` and
`tiqr webhook clear`, then restart the service. `--no-service --no-firewall` runs on any
machine and is what the CI smoke test uses.

Planned, not built: remote mode, the interactive wizard, `--answers` files and the signed
`tiqr-install` workstation tool. Remote mode would copy the bundle over system OpenSSH and run the
local steps there, so host-key checking stays OpenSSH's job. WinRM is deliberately not supported:
it would add a second transport, NTLM/Kerberos handling and different firewall rules.

### What the install does

1. Refuses to register a service or firewall rule without administrator rights (sudo on Linux).
2. Checks `tiqr_brand.jsonc`, asks for the address operators use (default: this machine's LAN
   address) and the port (default 7102), and writes `TIQR_HOST` and `TIQR_PORT` to `.env.local`.
3. Runs `tiqr setup`: creates `TIQR_SECRET_KEY` if it is missing, creates or migrates the database,
   and provisions the BioStar group when BioStar is configured.
4. Creates the first admin account if none exists. At a terminal it asks; otherwise it prints the
   command to run.
5. Opens the port: `ufw` or `firewalld` on Linux when active, or a `TiQR-<port>` rule in Windows
   Firewall. Otherwise it reports that nothing needs opening.
6. Registers and starts the service (see [Server layout](#server-layout)), then waits up to 30
   seconds for `/api/health`.
7. Prints the license request code if the program is not licensed yet.

The service runs as a system user `tiqr` on Linux, or the virtual account `NT SERVICE\TiQR` on
Windows, never root or LocalSystem.

### Server layout

| | Linux (systemd) | Windows (service) |
|---|---|---|
| Program | `/opt/tiqr/`, root-owned: `tiqr`, the notices, the health probe. The service cannot write it | `C:\Program Files\TiQR\`: `tiqr.exe`, WinSW and the scripts. No grant to the service account |
| Config | `/var/lib/tiqr/.env` and `.env.local`, owned by `tiqr` | `C:\ProgramData\TiQR\.env` and `.env.local`, granted to the service account |
| Data (DB, key, PDFs, backups) | `/var/lib/tiqr/`, owned by `tiqr` (`TIQR_HOME`) | `C:\ProgramData\TiQR\`, granted to the service account (`TIQR_HOME`) |
| Logs | journald | Rotated files under `C:\ProgramData\TiQR\logs\` |
| Service | `tiqr.service` unit written by `tiqr install`, enabled at boot, restarted on failure | [WinSW](https://github.com/winsw/winsw) wrapper written by `tiqr install`, automatic start, restarted on failure with delays of 5 seconds, 30 seconds, then 1 minute |

The installer writes the Linux unit, which runs `ExecStart=/opt/tiqr/tiqr serve` as `User=tiqr`
with `TIQR_HOME=/var/lib/tiqr`. The default port 7102 needs no privilege;
a site that picks one below 1024, such as 443, must add `AmbientCapabilities=CAP_NET_BIND_SERVICE`
by hand rather than run as root. The unit also sets `NoNewPrivileges`, `ProtectSystem=strict`,
`ReadWritePaths` on `/var/lib/tiqr`, `ProtectHome` and `PrivateTmp`. It starts at boot
(`WantedBy=multi-user.target`) and restarts after a crash or non-zero exit; a clean stop stays
stopped.

The program folder gives the service no rights, on Linux and Windows alike, so the service cannot
change the program it runs, including after an upgrade. On Linux only `/var/lib/tiqr` is owned by
`tiqr`. On Windows only `C:\ProgramData\TiQR` is granted Modify, and the files already there are
granted directly, since inheritance reaches only files created later. `tiqr_brand.jsonc` is not
granted on either, so the service cannot change it.

On Linux, `tiqr install` writes `tiqr-health.timer` and `tiqr-health.service` and enables the timer.
The timer runs `tiqr-health.sh` every minute as the service user, with the settings from `.env`
and `.env.local`. The script polls `/api/health` and exits non-zero on each failure, so
`systemctl --failed` shows an outage. After three failures in a row it logs a critical journal
entry (`tiqr-health`) for the customer's monitoring to pick up, and a notice once the server
answers again.

On Windows, `tiqr install` runs `tiqr-health.ps1 -Install`, which registers a scheduled task,
`TiQR Health Probe`, that runs the same probe every minute as the TiQR service account. It reads
`.env` and `.env.local` from the data folder, keeps its failure count in
`health-failures.txt` there, and logs to the Application event log under source `TiQR-Health`
(event 1 after three failures in a row, event 2 on recovery). The install step registers that
source, since only an administrator can.

Admin commands on the server run as the service account against the same configuration, for
example `sudo -u tiqr /opt/tiqr/tiqr user add ...`.

## Configuration

The settings live in `.env` and `.env.local` in the data folder: `/var/lib/tiqr` on Linux,
`C:\ProgramData\TiQR` on Windows. `.env.local` wins, and it is the file the installer writes. Real
environment variables override both.

| Setting | Set by |
|---|---|
| `TIQR_HOST`, `TIQR_PORT` | `tiqr install`: asked for, defaulting to this machine's LAN address and 7102 |
| `TIQR_PASS_WEBHOOK_URL`, `TIQR_PASS_WEBHOOK_SECRET` | `tiqr install` or the setup wizard, or later with `tiqr webhook set`. Both or neither; the secret signs each request. Read at startup, so restart the service after a change |
| `TIQR_SECRET_KEY` | `tiqr setup`, on the server. It never leaves the server, and the installer never reads it back |
| `TIQR_HOME` | The service definition, set to the data folder. It must be a real environment variable, because `.env` files are found through it |
| `TIQR_BIOSTAR_*`, `TIQR_BIOSTAR_VERIFY_TLS` | By hand in `.env.local`. Keep the BioStar password out of shared files. The library's `false` for `VERIFY_TLS` suits development only; installs should set `true` |
| `TIQR_DEFAULT_TZ`, `TIQR_SERVER_PRINTING` | By hand in `.env.local` |
| `TIQR_TLS_CERT`, `TIQR_TLS_KEY` | By hand: the customer's certificate. The installer does not generate one yet |

With `TIQR_HOME` set, data and config stay in the data folder when the program is replaced.

The server reads `tiqr_brand.jsonc` from the data folder at every start and refuses to run without
it. `tiqr install` checks the bundle's file, copies it there the first time, and keeps the copy
already there on later runs. The Windows installer (`tiqr_setup.exe`) is the exception: it writes the
file from its wizard, saves the file it replaces as `tiqr_brand.jsonc.bak`, and copies the chosen
logo beside it. Branding changes take effect on restart: edit the file in the data folder and
restart the service.

To change the address, port or any other setting, edit `.env.local` and restart the service. Or run
`tiqr install` again: at a terminal it asks for the address and port, re-registers the service and
runs the health check. A script takes the defaults unless `--host` and `--port` are given.

## Frontend and backend

`tiqr serve` serves:

- `/api/...`: the JSON API over `TicketService`.
- `/api/health`: version and readiness, without authentication. It answers 503 when the database
  does not respond or the scheduler has stopped. The installer, upgrades and the health probe use
  it.
- `/`: the frontend's static files, with `index.html` for any other path (SPA fallback).

Because the browser loads the UI from the same origin as the API, the frontend uses relative URLs
and needs no build-time address. The customer can change the server's IP or add a DNS name
without a rebuild; with TLS, only the certificate's names have to follow. Authentication uses
`HttpOnly`, `SameSite=Strict` session cookies, `Secure` under TLS, with no CORS configuration.

TiQR is fully on-premises, so `tiqr serve` speaks plain HTTP by default. The trade-off is that
passwords and session cookies cross the customer's LAN unencrypted, readable by anyone who can
capture its traffic. Sites that want it set `TIQR_TLS_CERT` and `TIQR_TLS_KEY`; TLS is then
terminated in-process by the ASGI server, so the same setup works on both OSes without shipping
a reverse proxy. Certificates, in order of preference:

1. **The customer's own certificate** from their internal CA, covering the IP and any DNS name.
2. **An installer-generated private CA** with a server certificate that has the IP in its
   subject alternative names. The customer installs the CA certificate on operator PCs once,
   through GPO, MDM or by hand, and later certificates reissue without new warnings.
3. **Self-signed**, only as a last resort: browsers warn on every machine, and teaching
   operators to click through warnings undoes the point of TLS.

## Updates

Run the install script from the newer bundle, on the same machine:

```text
sudo ./install.sh     # Linux
install.cmd           # Windows, as administrator
```

1. The script stops the running service. `install.cmd` stops the TiQR service itself, and
   `install.sh` stops `tiqr.service`.
2. If TiQR is already installed (the service, the program folder or the data folder exists), the script
   asks `Reinstall it?`. A no changes nothing. A yes deletes the program folder and the data folder,
   including `tiqr.db`, `.env.local` and `tiqr_brand.jsonc`, and installs from scratch, so the first
   admin is created again. Copy `tiqr.db` and `.env.local` somewhere safe first if they must be kept.
   The wizard asks the same question on Windows.
3. It runs `tiqr install` as on a first install. `tiqr setup` migrates the database, and the
   service and health probe are registered again. The health check then waits for the answer.

Migrations are numbered, forward-only steps, each in one transaction with its version bump. A
failed step rolls back alone. The steps before it stay applied, and the next install resumes from
there. `tiqr serve` refuses a database that is older than the program until `tiqr setup` has run.
An older program refuses a newer database, so going back needs the saved database copy below.

The database is not backed up automatically yet. Before an upgrade, stop the service and copy
`tiqr.db` from the data folder to a dated name, then start the service again. To go back, stop
the service, reinstall the previous bundle, restore the saved `tiqr.db`, and start the service.

Updates are offline by design, from a bundle delivered by download or USB, because many sites have
no internet access.

Planned, not built: checking `SHA256SUMS.sig` and every checksum before anything is replaced, a
backup taken automatically before migrations, rollback when the health check fails after an
upgrade, and keeping the last two releases.

The repository has a forward-only migration runner: numbered steps, each run once in one
transaction with its version bump. Version 2 added the web session table, version 3 the users'
`active` flag.

## What changes when TiQR becomes a server

These were decided in the backend phase and shape deployment:

- **Printing.** `ticket print` sends PDFs to *this machine's* default printer, but the server is
  not at the operator's desk. Both of the first two options are implemented:
  1. The browser downloads the PDF and the operator prints it. Browsers can't force 100% scale,
     so the operator must pick "Actual size". Always available.
  2. The server prints to a printer configured on it (CUPS or the Windows spooler), using the
     CLI's print path, when the site sets `TIQR_SERVER_PRINTING=true`.
  3. Later, a small desktop client or agent on operator PCs that prints silently at 100%.
- **Scheduling.** `tiqr serve` runs `sync` and `cleanup` on a background thread, on
  a built-in interval (sync every 60 seconds, cleanup hourly). Run **one** server process: the schedule,
  the login limits and the lock that keeps runs apart are per process.
- **Authentication.** Server-side sessions in SQLite with `HttpOnly` cookies, a CSRF token on
  every write, `Origin` checks, and login rate limiting; see [Web API](README.md#web-api).
- **Backups.** The database is now the customer's production record and holds the never-reused
  BioStar ID range. Backups are not automated yet: copy `tiqr.db` while the service is stopped,
  and document restoring it.

## Security risks

Risks specific to shipping compiled code to third parties, most important first:

1. **Compiled is not secret.** The current PyInstaller builds hand over recoverable source.
   Nuitka raises the cost but does not stop a determined reader. Don't rely on obscurity for
   anything, and keep the EULA's reverse-engineering terms explicit.
2. **The customer is root on the box.** They can read the database, config, BioStar password
   and process memory, and they can patch out any license check. Design for that: a license key
   signed with RSA-2048 (private key only on the vendor's machine, public key in the binary) is
   a deterrent, not a lock.
3. **Never build a secret into an artifact.** No shared signing key, BioStar credentials or
   license private key in the code or bundle, and no secret that is the same across customers.
   `TIQR_SECRET_KEY` is already generated per install. Add a CI step that scans built artifacts
   for key material.
4. **Update integrity.** An unsigned bundle lets anyone on the path swap the binary that runs as
   a service. Sign every bundle and verify before install. Authenticode-sign the Windows
   executables, or SmartScreen will warn and antivirus may quarantine them: onefile Python
   builds are frequent false positives. Keep signing keys in a CI secret store or KMS, never in
   the repository.
5. **Frozen dependencies.** Python, OpenSSL, httpx2 and the rest are baked in, and customers can't
   patch them. Track advisories (Dependabot, `pip-audit`), rebuild on fixes, and have a release
   cadence customers expect.
6. **TLS on a LAN.** The server speaks plain HTTP unless a site configures a certificate, so
   on such sites anyone who can capture LAN traffic can read passwords and session cookies.
   Public CAs won't issue for private IPs, so certificates are the customer's or yours; see
   [Frontend and backend](#frontend-and-backend). BioStar TLS verification is off
   by default in the library. Installs should turn it on, or pin BioStar's certificate.
7. **The installer handles admin credentials.** Keep OpenSSH's host-key verification (never
   `StrictHostKeyChecking=no`). Never log, cache or write passwords. Prefer key authentication.
   The installer needs root or admin; the service it installs must not have it.
8. **Network exposure.** The API is reachable from the customer's LAN. Bind to the given IP, not
   every interface. Disable interactive API docs (`/docs`, `/openapi.json`) in production. Return
   no stack traces. Rate-limit login.
9. **The frontend is public by nature.** Ship it minified, without source maps, and with no keys
   or logic the API doesn't also enforce.
10. **Open-source obligations.** Current dependencies are permissive: MIT, BSD, Apache-2.0 and PSF,
    plus Geist under the OFL. PyInstaller's bootloader and Nuitka's runtime allow closed-source
    distribution, and WinSW is MIT. Closed-source shipping is allowed, but `THIRD-PARTY-NOTICES`
    must reproduce their notices. Check every new dependency, because one GPL or AGPL
    dependency could force you to disclose source.
11. **Personal data.** Visitor names live in the database, PDFs and possibly logs. Keep them under
    the service account's permissions, and don't log request bodies.

## Implementation plan

Done: **0. Restructure.** uv workspace with `core`, `cli` and `api` members under `apps/`, sharing
the `tiqr` namespace. Layering is enforced by the packaging tests, `apps/web/` is a placeholder, and
CI is updated.

Done: **1. API (`apps/api`).** FastAPI and Uvicorn in `tiqr-api` only; `tiqr serve` with bind
address and optional TLS; `TIQR_HOME`; account roles, deactivation and password resets; server-side cookie sessions with CSRF protection and login
rate limiting; endpoints mirroring the CLI's ticket, user, sync, cleanup and stats commands, all
through `TicketService`; scheduled sync and cleanup; `/api/health`; the web build's host with the
SPA fallback; browser and server printing; the schema migration runner. Tests run in-process
through FastAPI's TestClient, never against a live BioStar. The PyInstaller smoke test starts
`tiqr serve` and signs in.

2. **Nuitka builds.** Build the standalone server folder and onefile installer per OS, with the
   Linux build on an old-glibc base. Include `tiqr-api`'s distribution metadata, which its
   version is read from, and Uvicorn's dynamically imported protocol modules, as the PyInstaller
   spec does. Port the CI smoke test. Retire the PyInstaller spec once it passes.
3. **Installer, local mode.** Written for Linux and Windows: service, service user, layout,
   firewall, `tiqr setup`, first admin, health check and health timer.
   - Not done: TLS generation, and the Windows steps have not run on a Windows host.
   - Test on throwaway VMs: Ubuntu 22.04 and 24.04, Windows Server 2022 and 2025.
4. **Installer, remote mode.** OS detection, `scp` and `ssh -t` into local mode, and the
   interactive wizard plus the `--answers` file.
5. **Web (`apps/web`).** Scaffold Svelte with Vite, building to static files, following
   [apps/web/README.md](apps/web/README.md). Add a locked CI job that builds it and copies
   `build/` into the api package before compiling.
6. **Releases and upgrades.**
   - Bundle assembly, `SHA256SUMS`, Ed25519 signing, Authenticode and `THIRD-PARTY-NOTICES` in
     the Executables workflow.
   - `--upgrade` with backup, migrations and rollback.
   - The license check is built in (see [Licensing](#licensing)).

## Licensing

The program refuses every API request without a valid license, and the web app shows a wall
until one is activated. There is no license server and no telemetry.

1. The customer opens the app, copies the **request code** from the wall and sends it to the
   vendor. The code carries this install's machine ID and a random request ID; it always asks for
   a standard license.
2. The vendor runs `tools/issue_license.py --request CODE --type trial`, or
   `--type standard --licensedTo "Company" --days 365`, and sends back the key. The vendor's
   `--type` decides the license. A machine gets only one trial; the tool refuses a second.
3. An admin pastes the key into the wall (or **License** in the admin menu). The key is
   `base64(payload).base64(signature)`: RSA-2048, PKCS#1 v1.5, SHA-256 over the payload bytes.

The signature is verified on every status read; the database only caches it. A trial is a
vendor-signed key with a 30-day expiry, never issued by the program.

**Vendor setup.** Keep `license-private.pem`, `license-public.pem` and `issued.json` in
`TIQR_VENDOR_DIR` (default `~/.tiqr-vendor`), never in the repository or a build. The public key
is the `PUBLIC_KEY` constant in `apps/core/src/tiqr/core/license.py`; the tool refuses to sign if
they differ. `issued.json` is the trial registry (one trial per machine ID) and holds working
keys: back it up and restrict it. Rotating the key pair voids every issued key.

**Not covered.** A new hostname or MAC gets a new trial, clock rollback extends a license, a
copied install keeps working, and there is no revocation. See the accepted limitations in the
design notes; short licenses with scheduled reissue are the cheapest mitigation.
