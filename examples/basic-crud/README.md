# Basic CRUD API

This example is intentionally small. It demonstrates HTTP semantics, separate request and response schemas, a request-scoped SQLAlchemy session, deterministic pagination, and API tests.

SQLite keeps the first run self-contained. Move to the [production API](../production-api/) before copying a structure for a growing service.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
uvicorn app.main:app --reload
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Open `http://127.0.0.1:8000/docs` or call:

```bash
curl -i -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Read the lifecycle chapter"}'
```

## Test

```bash
pytest
```

Tests replace the file database with one isolated in-memory SQLite engine. The override changes resource acquisition, not route behavior.

## Boundaries

- `schemas.py` defines the HTTP representations.
- `models.py` defines the SQL table mapping.
- `db.py` owns engine and session lifecycle.
- `main.py` owns the HTTP contract and this example's small amount of application logic.

For a larger domain, move state transitions into a service or use-case module. Do not add layers only to forward calls.

[Back to examples](../../README.md#practical-examples)
