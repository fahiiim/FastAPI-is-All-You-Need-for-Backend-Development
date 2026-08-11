# Production API Reference

This example shows a feature-oriented FastAPI service with PostgreSQL, SQLAlchemy 2.x, Alembic, opaque bearer sessions, resource authorization, and API tests.

The example chooses synchronous SQLAlchemy deliberately. Its database driver blocks, so route functions use normal `def` and FastAPI runs them in its thread pool. An async stack would require `AsyncSession`, an async driver, and load testing that demonstrates a benefit.

## Structure

```text
app/
|-- main.py
|-- core/       # validated configuration and shared errors
|-- database/   # engine, session lifecycle, metadata
|-- identity/   # registration, login, bearer-session authentication
`-- projects/   # project API, service, schemas, and mapping
migrations/     # reviewed schema history
tests/          # API tests with dependency overrides
```

## Run with PostgreSQL

```bash
docker compose up --build
```

The API runs on `http://localhost:8000`. Compose applies migrations before starting Uvicorn. The checked-in credentials are development-only.

For a local Python process:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Request flow

1. Register with `POST /v1/auth/register`.
2. Obtain an opaque bearer token from `POST /v1/auth/login`.
3. Send `Authorization: Bearer <token>` to project routes.
4. Project queries include the authenticated owner condition, so a guessed ID cannot cross the resource boundary.

The raw session token is returned once and only its SHA-256 digest is stored. Passwords use `pwdlib`'s recommended policy. Production systems also need session revocation UI, login throttling, audit events, password reset, email verification where required, and a secret-management policy.

## Test

```bash
pytest
```

The fast API suite uses SQLite to demonstrate dependency isolation. Run a separate PostgreSQL integration suite in a real project for PostgreSQL constraints, locking, SQL, and migrations. This tradeoff is explicit rather than treating SQLite as equivalent.

## Deliberate omissions

- Email verification and password reset
- Tenant memberships beyond direct project ownership
- Cursor pagination
- Audit log and session-management UI
- PostgreSQL integration container in the test suite
- Production ingress, TLS, and telemetry exporters

Those concerns are covered in the handbook and should be added when the product requirements justify them.

[Back to examples](../../README.md#practical-examples)
