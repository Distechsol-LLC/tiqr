# TiQR Core

> TiQR Core is made with
> - **[Python](https://python.org)**
> - **[SQLite](https://sqlite.org)**
> - **[ReportLab](https://www.reportlab.com)**
>
> and holds the domain: tickets, storage, the BioStar X integration, and QR and PDF output. It has no HTTP or terminal code, so the CLI and the API both drive it through `TicketService`.

## Install
```sh
uv python install 3.14
uv sync --locked
```
## Develop
### Lint and Format (Ruff)
```sh
uv run ruff check --fix .
uv run ruff format .
```
### Type Check (Pyright)
```sh
uv run pyright
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
