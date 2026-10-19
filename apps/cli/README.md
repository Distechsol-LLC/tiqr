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
