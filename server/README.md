# M-Group Server

Minimal FastAPI and SQLAlchemy skeleton for M-Group Platform. P1 intentionally contains no
models, routers, services, database tables, or migration revisions.

## Requirements

- Python 3.11 or newer
- pip

## Create a virtual environment and install

Run these commands from the repository root:

```bash
cd server
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
cp .env.example .env
pip install -e ".[dev]"
```

The example DATA_KEY is a valid 32-byte base64 development value. Replace all development
credentials and cryptographic secrets before using this server outside local development.

## Run the server

From the `server/` directory with the virtual environment active:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

Interactive API documentation is enabled by default for local development. Set
`ENABLE_API_DOCS=false` to disable OpenAPI, Swagger UI, and ReDoc.

## Alembic

The Alembic environment loads `DATABASE_URL` from `app.config` and uses
`app.db.Base.metadata` as target metadata:

```bash
alembic -c alembic.ini current
alembic -c alembic.ini upgrade head
```

P1 deliberately includes no migration revision and declares no tables. Consequently,
Alembic has no `head` revision to apply until the first schema phase adds a real migration.
Do not add a no-op migration merely to manufacture a head; that would violate the P1 scope.

## Lint

```bash
ruff check .
```
