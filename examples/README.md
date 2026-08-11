# Reference Applications

The examples increase one kind of complexity at a time. They are not four competing project templates.

| Example | Persistence | Execution | Identity | Primary lesson |
| --- | --- | --- | --- | --- |
| [Basic CRUD](basic-crud/) | SQLite | Synchronous request path | None | HTTP, schemas, sessions, API tests |
| [Production API](production-api/) | PostgreSQL | Synchronous request path | Opaque bearer session | Modules, migrations, authorization, integration boundary |
| [Distributed API](distributed-api/) | PostgreSQL and Redis | HTTP plus Celery workers | Demonstration API key | Outbox, jobs, duplicate delivery, progress |
| [AI API](ai-api/) | PostgreSQL | SSE plus durable workers | Demonstration API key | Provider boundary, usage, cancellation, streamed and queued work |

## How to read an example

Start with its README and identify the source of truth, transaction owner, authentication boundary, and failure model. Then inspect the tests before the route implementation. The tests show which guarantees the example claims.

Each README lists deliberate omissions. A missing feature is not silently presented as production-complete. The handbook chapters explain how requirements such as multi-tenancy, full observability, TLS, backups, or a separate test database change the design.

## Running examples

Install each example in its own virtual environment because every package intentionally uses the top-level module name `app`.

```bash
cd examples/basic-crud
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
pytest
```

The production and distributed examples include Compose environments. Development credentials in those Compose files are local-only and must never be copied to a deployed environment.

## Adapting code

Copy an engineering decision only with its assumptions. For example:

- SQLite schema creation is acceptable in the first tutorial, not a production migration workflow.
- The production API uses sync SQLAlchemy intentionally; async is not a maturity level.
- Redis progress in the distributed API is replaceable; PostgreSQL remains authoritative.
- SSE in the AI API improves incremental delivery but does not replace its durable job path.

[Back to documentation map](../README.md)
