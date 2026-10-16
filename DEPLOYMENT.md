# TiQR packaging and deployment

How TiQR is built, shipped as a closed-source product, installed on a customer's server, and
updated. The customer never receives source code. Everything runs on their network, on a Linux
or Windows server at an address they choose.

Status: the repository is restructured for this design (see [Layout](README.md#layout)), and the
backend API and `tiqr serve` are implemented (see [Web API](README.md#web-api)). The frontend,
Nuitka builds, installer and release pipeline described here are **not implemented yet**;
[Implementation plan](#implementation-plan) lists the order.

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

Neither CI nor the bundle holds per-customer data or secrets. A per-customer license file, if
used, is delivered separately (see [Security risks](#security-risks)).

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

```text
tiqr-install                                   # interactive wizard; asks for everything below
tiqr-install --host 10.0.0.5 --ssh-user admin  # remote: Linux or Windows target, detected
tiqr-install --local                           # run on the target server itself
tiqr-install --answers site.toml               # unattended; secrets are prompted or read from env
```

Remote mode is thin. It verifies the bundle, uses system OpenSSH to copy the bundle and connect,
detects the target OS (`uname`, or `$env:OS` on Windows), copies the matching payload with `scp`,
and runs `tiqr install --local` there over `ssh -t`, so `sudo` and prompts work. All install
logic therefore exists once, in local mode.

System OpenSSH ships with Windows 10+ and Linux. Using it means the customer's keys,
agent, `known_hosts` and jump hosts all work, and host-key checking stays OpenSSH's job. Windows
targets need the OpenSSH Server feature, available on Windows Server 2019 and later. Where a
customer can't enable it, they copy the bundle over and use `--local`. WinRM is deliberately not
supported: it would add a second transport, NTLM/Kerberos handling and different firewall rules.

### What local mode does

1. Check prerequisites: OS version, admin rights, free disk space, and that the port is free.
2. Create a service account: system user `tiqr` on Linux, a virtual service account on Windows.
   Never root or LocalSystem.
3. Unpack the payload into a versioned release folder and point `current` at it.
4. Write the configuration (see [Configuration](#configuration)) and run `tiqr setup` as the
   service account, which generates the signing key **on the server** and initializes the
   database.
5. Optionally set up TLS (see [Frontend and backend](#frontend-and-backend)).
6. Register and start the service. On Linux, open the firewall port if `ufw` or `firewalld` is
   active; on Windows, add a `New-NetFirewallRule`.
7. Create the first admin account interactively, then poll `http://<ip>:<port>/api/health`
   (`https://` with TLS)
   until it reports the installed version.

### Server layout

| | Linux (systemd) | Windows (service) |
|---|---|---|
| Program | `/opt/tiqr/releases/<version>/`, `/opt/tiqr/current` symlink | `C:\Program Files\TiQR\releases\<version>\`, `current` directory junction |
| Config | `/etc/tiqr/tiqr.env`, `root:tiqr 0640` | `C:\ProgramData\TiQR\tiqr.env`, ACL: SYSTEM, Administrators, service account |
| Data (DB, key, PDFs, backups) | `/var/lib/tiqr/`, `tiqr:tiqr 0700` | `C:\ProgramData\TiQR\data\`, same ACL |
| Logs | journald | Rotated files under `C:\ProgramData\TiQR\logs\` |
| Service | `tiqr.service` unit | [WinSW](https://github.com/winsw/winsw) wrapper, since a plain console executable can't answer the Service Control Manager |

The Linux unit runs `ExecStart=/opt/tiqr/current/tiqr serve` as `User=tiqr` with
`EnvironmentFile=/etc/tiqr/tiqr.env`. The default port 7102 needs no privilege; a site that picks
one below 1024, such as 443, adds `AmbientCapabilities=CAP_NET_BIND_SERVICE` rather than running
as root. The unit also sets `NoNewPrivileges`, `ProtectSystem=strict`,
`ReadWritePaths=/var/lib/tiqr`, `ProtectHome` and `PrivateTmp`.

Admin commands on the server run as the service account against the same configuration, for
example `sudo -u tiqr /opt/tiqr/current/tiqr user add ...`. The installer drops a small
`tiqr-admin` wrapper that does this.

## Configuration

The installer collects, then writes `tiqr.env`:

| Setting | Source |
|---|---|
| Bind address and port (`TIQR_HOST`, `TIQR_PORT`), for example `10.0.0.5:7102` | The target IP the customer gave; port defaults to 7102 |
| Data folder (`TIQR_HOME`), `TIQR_DB`, `TIQR_OUT` | Fixed by the server layout |
| `TIQR_BIOSTAR_*` block and `TIQR_BIOSTAR_REQUIRED=true` | Prompted; the password is never written to an answers file or logged |
| `TIQR_BIOSTAR_VERIFY_TLS` | Prompted, defaulting to `true` for installs. The library's `false` default suits development only |
| `TIQR_DEFAULT_TZ` | Prompted, defaulting to the server's zone |
| TLS certificate and key paths (`TIQR_TLS_CERT`, `TIQR_TLS_KEY`) | Optional; customer-provided or installer-generated |
| `TIQR_SERVER_PRINTING` | Prompted: whether operators may print on the server's printer |

`TIQR_SECRET_KEY` is generated on the server by `tiqr setup` and never leaves it. The installer
never reads it back. `TIQR_HOME` must reach the process as a real environment variable, through the unit's
`Environment=` or `EnvironmentFile=` or the Windows service definition. TiQR finds its `.env`
files through it, so a `.env` file cannot set it. With it set, data and config stay put while
release folders change.

Reconfiguring is `tiqr install --reconfigure`. It edits `tiqr.env`, restarts the service and
runs the health check. A hand edit followed by a service restart works too.

## Frontend and backend

`tiqr serve` serves:

- `/api/...`: the JSON API over `TicketService`.
- `/api/health`: version and readiness, without authentication. The installer and upgrades use
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

```text
tiqr-install --host 10.0.0.5 --upgrade      # or --local --upgrade on the server
```

1. Verify `SHA256SUMS.sig` and every checksum. Refuse the upgrade on any mismatch.
2. Unpack the new release beside the current one. Nothing running changes yet.
3. Stop the service and back up the database with SQLite's online backup API to
   `backups/<timestamp>-<old version>.db`.
4. Run schema migrations with the new binary: `tiqr setup` applies them. Every other command,
   `tiqr serve` included, refuses an outdated schema, so a skipped step fails loudly.
5. Repoint `current`, start the service, and wait for `/api/health` to report the new version.
6. If any step after 3 fails: stop, restore the backup, repoint `current` to the old release, and
   start again. Keep the last two releases and a bounded number of backups.

Downgrades past a schema change are refused. Updates are offline by design, from a bundle
delivered by download or USB, because many sites have no internet access. An optional "update
available" check can come later. It is never needed to run.

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
  `TIQR_SYNC_INTERVAL` and `TIQR_CLEANUP_INTERVAL`. Run **one** server process: the schedule,
  the login limits and the lock that keeps runs apart are per process.
- **Authentication.** Server-side sessions in SQLite with `HttpOnly` cookies, a CSRF token on
  every write, `Origin` checks, and login rate limiting; see [Web API](README.md#web-api).
- **Backups.** The database is now the customer's production record and holds the never-reused
  BioStar ID range. Schedule the same online backup the upgrade uses, and document restoring it.

## Security risks

Risks specific to shipping compiled code to third parties, most important first:

1. **Compiled is not secret.** The current PyInstaller builds hand over recoverable source.
   Nuitka raises the cost but does not stop a determined reader. Don't rely on obscurity for
   anything, and keep the EULA's reverse-engineering terms explicit.
2. **The customer is root on the box.** They can read the database, config, BioStar password
   and process memory, and they can patch out any license check. Design for that: a license file
   signed with Ed25519 (private key only in your release pipeline, public key in the binary) is
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
3. **Installer, local mode.**
   - Linux: systemd unit, service user, layout, firewall, TLS generation, `tiqr setup`, first
     admin, health check.
   - Windows: WinSW, virtual account, ACLs, firewall rule.
   - Test on throwaway VMs: Ubuntu 22.04 and 24.04, Windows Server 2022 and 2025.
4. **Installer, remote mode.** OS detection, `scp` and `ssh -t` into local mode, and the
   interactive wizard plus the `--answers` file.
5. **Web (`apps/web`).** Scaffold SvelteKit with the static adapter following
   [apps/web/README.md](apps/web/README.md). Add a locked CI job that builds it and copies
   `build/` into the api package before compiling.
6. **Releases and upgrades.**
   - Bundle assembly, `SHA256SUMS`, Ed25519 signing, Authenticode and `THIRD-PARTY-NOTICES` in
     the Executables workflow.
   - `--upgrade` with backup, migrations and rollback.
   - Optionally, the license file check.
