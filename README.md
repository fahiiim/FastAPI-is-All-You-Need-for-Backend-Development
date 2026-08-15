# FastAPI Backend Engineering

A production-focused handbook for engineers who build HTTP services with Python and FastAPI. The repository connects framework mechanics to database behavior, security boundaries, concurrency, deployment, observability, distributed systems, and technical interviews.

This is not a replacement for the FastAPI documentation. Official documentation explains the public API of the framework. This handbook concentrates on engineering decisions: where code belongs, what fails under load, which guarantees matter, and how to explain the tradeoffs.

## Start here

Choose a path based on what you need now.

| Path | Start | Outcome |
| --- | --- | --- |
| New to backend work | [Backend roadmap](resources/backend-roadmap.md) | Build foundations in Python, HTTP, SQL, FastAPI, testing, and deployment |
| Building a FastAPI service | [Framework, routing, and OpenAPI](docs/01-fastapi-core/framework-routing-and-openapi.md) | Understand the framework before choosing an application structure |
| Improving an existing service | [Production checklist](resources/production-checklist.md) | Find gaps in security, reliability, data access, and operations |
| Choosing an architecture | [Backend project structure](backend-project-structure.md) | Select a structure that matches the system's size and rate of change |
| Preparing for interviews | [Interview guide](interview/README.md) | Practice from fundamentals through senior production scenarios |
| Building an AI API | [Production AI APIs](docs/05-ai-backends/production-ai-apis.md) | Design streaming, queued, measured, and failure-aware model workloads |

## Documentation map

### Foundations

- [Python for backend engineering](docs/00-foundations/python-for-backend.md)
- [HTTP, REST, and API design](docs/00-foundations/http-rest-api-design.md)

### FastAPI core

- [Framework, routing, and OpenAPI](docs/01-fastapi-core/framework-routing-and-openapi.md)
- [Request and response lifecycle](docs/01-fastapi-core/request-response-lifecycle.md)
- [Pydantic and validation](docs/01-fastapi-core/pydantic-validation.md)
- [Dependency injection](docs/01-fastapi-core/dependency-injection.md)
- [Async and concurrency](docs/01-fastapi-core/async-concurrency.md)
- [Middleware, errors, files, tasks, and WebSockets](docs/01-fastapi-core/middleware-errors-and-io.md)

### Data engineering

- [Relational databases](docs/02-data/relational-databases.md)
- [SQLAlchemy 2.x](docs/02-data/sqlalchemy-2.md)
- [Alembic and transactions](docs/02-data/alembic-and-transactions.md)
- [Querying, pagination, and performance](docs/02-data/querying-pagination-and-performance.md)

### Security

- [Authentication and tokens](docs/03-security/authentication-and-tokens.md)
- [Authorization and multi-tenancy](docs/03-security/authorization-and-multitenancy.md)
- [Application security](docs/03-security/application-security.md)

### Production engineering

- [Configuration, logging, and errors](docs/04-production/configuration-logging-and-errors.md)
- [Caching, Redis, and rate limiting](docs/04-production/caching-redis-and-rate-limiting.md)
- [Queues, workers, and scheduling](docs/04-production/queues-workers-and-scheduling.md)
- [Integrations, webhooks, and resilience](docs/04-production/integrations-webhooks-and-resilience.md)
- [Testing strategy](docs/04-production/testing-strategy.md)
- [Containers and deployment](docs/04-production/containers-and-deployment.md)
- [Performance and scalability](docs/04-production/performance-and-scalability.md)
- [Observability](docs/04-production/observability.md)

### Architecture and system design

- [Backend project structure](backend-project-structure.md)
- [Architecture patterns](architecture/architecture-patterns.md)
- [Production architecture](architecture/production-architecture.md)
- [Distributed systems](architecture/distributed-systems.md)
- [System design case studies](architecture/system-design-case-studies.md)

### AI backends

- [Production AI APIs](docs/05-ai-backends/production-ai-apis.md)
- [RAG and document ingestion](docs/05-ai-backends/rag-and-ingestion.md)

### Decision guides

- [Async and execution models](decision-guides/async-and-execution-models.md)
- [Caching, Redis, and rate limits](decision-guides/caching-redis-rate-limits.md)
- [Background tasks, queues, Kafka, and WebSockets](decision-guides/jobs-messaging-and-realtime.md)
- [Persistence and service architecture](decision-guides/persistence-and-architecture.md)

### Field references

- [Backend roadmap](resources/backend-roadmap.md)
- [Common mistakes](resources/common-mistakes.md)
- [Glossary](resources/glossary.md)
- [Production checklist](resources/production-checklist.md)
- [Source catalog](resources/sources.md)

## Practical examples

The examples are intentionally progressive. Each has its own dependency file and README.

| Example | Main ideas |
| --- | --- |
| [Basic CRUD](examples/basic-crud/README.md) | Routes, schemas, SQLite, errors, API tests |
| [Production API](examples/production-api/README.md) | Feature modules, SQLAlchemy, authentication boundary, migrations, integration tests |
| [Distributed API](examples/distributed-api/README.md) | PostgreSQL, Redis, Celery, idempotent jobs, Docker Compose |
| [AI API](examples/ai-api/README.md) | Provider boundary, SSE, queued work, usage accounting, cancellation |

The larger examples are reference implementations, not universal templates. Copy decisions only after understanding the assumptions recorded in each example.

## Learning principles

Each major chapter moves through four questions:

1. What guarantee or problem is involved?
2. How does FastAPI participate in the solution?
3. What changes in a production service?
4. What tradeoff should an engineer be able to defend?

Examples use current FastAPI, Pydantic v2, and SQLAlchemy 2.x conventions. Synchronous code is used where it is the honest execution model. `async def` is reserved for code paths that await non-blocking I/O.

## Sources and maintenance

Claims tied to a framework API, protocol, or security standard link to authoritative documentation. The [source catalog](resources/sources.md) records the primary references and their scope. Examples avoid pinning a transient model name or cloud product detail unless the choice matters to the lesson.

Run the repository checks before publishing a change:

```bash
python tools/check_docs.py
npm ci --ignore-scripts
npm test
(cd examples/basic-crud && pytest)
(cd examples/production-api && pytest)
(cd examples/ai-api && pytest)
```

The documentation site can be previewed with MkDocs:

```bash
python -m pip install -r requirements-docs.txt
npm ci --ignore-scripts
npm run serve:docs
```

## Contributing

Corrections and production postmortem lessons are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the citation, example, terminology, and review rules.

## License

Code and documentation are available under the [MIT License](LICENSE).
