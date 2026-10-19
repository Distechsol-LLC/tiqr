# TiQR API

> TiQR API is made with
> - **[Python](https://python.org)**
> - **[FastAPI](https://fastapi.tiangolo.com)**
> - **[Uvicorn](https://uvicorn.dev)**
>
> and is the HTTP layer over `tiqr-core`. It serves the bundled web app from the same process, so `tiqr serve` runs both.

## Install
```sh
uv python install 3.14
uv sync --locked
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
