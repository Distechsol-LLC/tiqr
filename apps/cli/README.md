# TiQR CLI

> TiQR CLI is made with
> - **[Python](https://python.org)**
> - **[Typer](https://typer.tiangolo.com)**
>
> and is the `tiqr` command. It is also the entry point the packaged executable runs, and `tiqr serve` starts the API.

## Install
```sh
uv python install 3.14
uv sync --locked
```
## Develop
### Show Commands
```sh
uv run tiqr --help
```
### First-Run Setup
```sh
uv run tiqr setup
```
### Start Server
```sh
uv run tiqr serve
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

### Ticket lifecycle and service keys

These match the web API and web app:

```
tiqr ticket revoke <id> --as <user> [--reason ...]       # idempotent; also removes BioStar access
tiqr ticket update <id> --as <user> [--from ...] [--until ...]
tiqr ticket reissue <id> --as <user> [--from ...] [--until ...]   # any state; this is how a ticket is edited
tiqr ticket audit <id> --as <user>
tiqr ticket batch tickets.json --as <user> [--atomic] [--idempotency-key ...]
tiqr ticket create ... [--idempotency-key ...]
tiqr ticket list --as <user>
tiqr key create <name> --scope tickets:read --as <admin>   # also: list, rotate, revoke
```

`TIQR_BATCH_MAX_SIZE` and `TIQR_IDEMPOTENCY_TTL_HOURS` apply here as they do to the API.
