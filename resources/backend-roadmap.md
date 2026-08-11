# Backend Engineering Roadmap

This roadmap is ordered by dependency, not by novelty. Move forward when you can build and explain the checkpoint, not when you have read every link.

```text
Python
  -> HTTP
  -> REST and API contracts
  -> FastAPI and Pydantic
  -> SQL and PostgreSQL
  -> SQLAlchemy and migrations
  -> Authentication and authorization
  -> Testing
  -> Containers and deployment
  -> Redis and background jobs
  -> Observability and performance
  -> Architecture and system design
```

## Stage 1: Python for services

Learn:

- functions, classes, modules, imports, exceptions, and context managers;
- type hints, protocols, dataclasses, and generics at a practical level;
- iterators, generators, and resource cleanup;
- virtual environments, package metadata, and dependency locking;
- `asyncio`, coroutines, tasks, and cancellation;
- logging and testable code boundaries.

Checkpoint: write a typed command-line program that reads configuration, calls an HTTP API with timeouts, validates a response, and reports structured errors. Unit-test it without calling the network.

Do not move on while exceptions, imports, or context managers remain mysterious. FastAPI uses all three in normal request handling.

Read: [Python for backend engineering](../docs/00-foundations/python-for-backend.md).

## Stage 2: HTTP

Learn:

- request method, target, headers, and body;
- response status, headers, and body;
- safe and idempotent methods;
- media types and content negotiation;
- cache validators, cookies, bearer credentials, and CORS;
- proxies, TLS, DNS, connection reuse, and deadlines.

Checkpoint: design an API for a task list. Explain why create returns 201, how a client updates one field, what happens on duplicate creation, and which errors return 400, 401, 403, 404, 409, 422, or 429.

Read: [HTTP, REST, and API design](../docs/00-foundations/http-rest-api-design.md).

## Stage 3: FastAPI and Pydantic

Learn:

- application construction and lifespan;
- routing, path/query/header/body input, and response models;
- `APIRouter`, dependencies, middleware, and exception handlers;
- Pydantic v2 validation, configuration, serialization, and validators;
- OpenAPI as a contract, not only an interactive page;
- sync versus async endpoint behavior.

Checkpoint: build a memory-backed API with explicit schemas, conditional not-found errors, pagination parameters, one dependency, an exception handler, and API tests. Explain the request lifecycle from socket to serialized response.

Read: [FastAPI core](../docs/01-fastapi-core/framework-routing-and-openapi.md) and run [Basic CRUD](../examples/basic-crud/).

## Stage 4: SQL and PostgreSQL

Learn:

- tables, rows, data types, keys, constraints, joins, and aggregates;
- normalization and deliberate denormalization;
- B-tree indexes and composite index ordering;
- transactions, MVCC, isolation, locks, and deadlocks;
- query plans and `EXPLAIN`;
- connection and statement limits.

Checkpoint: design users, projects, and memberships with database-enforced uniqueness and foreign keys. Write joins and pagination queries. Demonstrate a race that a unique constraint prevents.

Read: [Relational databases](../docs/02-data/relational-databases.md).

## Stage 5: SQLAlchemy and Alembic

Learn:

- SQLAlchemy 2.x mappings and `select()`;
- session and identity-map lifecycle;
- relationship loading and N+1 behavior;
- sync and async session constraints;
- transaction ownership and nested transactions;
- migration autogeneration, review, expand-contract rollout, and recovery.

Checkpoint: replace the memory store with PostgreSQL. Add a migration, integration tests, one relationship with an intentional loading strategy, and a transaction that changes two records atomically. Prove sessions close after exceptions.

Read: [SQLAlchemy 2.x](../docs/02-data/sqlalchemy-2.md) and [Alembic and transactions](../docs/02-data/alembic-and-transactions.md).

## Stage 6: Identity and security

Learn:

- password hashing and credential storage;
- session cookies versus bearer tokens;
- OAuth2 roles and flows;
- short-lived access tokens and refresh-token rotation;
- API-key hashing and lifecycle;
- RBAC, permissions, resource policy, and tenant boundaries;
- common web and API threats.

Checkpoint: authenticate a user, authorize a tenant-scoped resource, rotate a refresh credential, and test revoked, expired, cross-tenant, and insufficient-permission cases. Write a threat model for the login and file-upload paths.

Read: [Authentication](../docs/03-security/authentication-and-tokens.md), [authorization](../docs/03-security/authorization-and-multitenancy.md), and [application security](../docs/03-security/application-security.md).

## Stage 7: Testing

Learn:

- unit, integration, API, contract, and system-test scopes;
- pytest fixtures and factory patterns;
- FastAPI dependency overrides;
- `TestClient` and an async ASGI client such as `httpx2.AsyncClient`;
- isolated PostgreSQL state and transaction cleanup;
- when to fake, mock, or run a real dependency.

Checkpoint: make the test suite fail if authorization is removed, a transaction partially commits, the provider times out, or a duplicate webhook is processed twice. Run it from a clean checkout.

Read: [Testing strategy](../docs/04-production/testing-strategy.md).

## Stage 8: Containers and deployment

Learn:

- image layers, multi-stage builds, non-root users, and immutable artifacts;
- environment injection and secret management;
- Uvicorn processes, worker count, graceful shutdown, and lifespan;
- reverse proxy behavior, TLS termination, trusted headers, and timeouts;
- liveness, readiness, migration, and rollback behavior;
- CI gates and artifact promotion.

Checkpoint: containerize the service, run PostgreSQL locally with Compose, deploy the same image to a test environment, fail readiness when required dependencies are unavailable, and demonstrate a rollback-safe schema change.

Read: [Containers and deployment](../docs/04-production/containers-and-deployment.md).

## Stage 9: Redis and background jobs

Learn:

- cache-aside, TTL, invalidation, stampede, and outage policies;
- token-bucket rate limiting;
- at-least-once task delivery and idempotent handlers;
- acknowledgements, retries, dead letters, and scheduling;
- RabbitMQ-style queues and Kafka-style retained logs;
- transactional outbox and inbox deduplication.

Checkpoint: add one measured cache with a documented freshness window and one durable job with status, cancellation, bounded retry, and duplicate-delivery tests. Explain behavior during a Redis or broker outage.

Read: [Caching and Redis](../docs/04-production/caching-redis-and-rate-limiting.md) and [queues and workers](../docs/04-production/queues-workers-and-scheduling.md).

## Stage 10: Observability and performance

Learn:

- structured logs, request IDs, metrics, traces, and exemplars;
- latency distributions, throughput, saturation, and error budgets;
- database pool and query diagnosis;
- load testing, profiling, and capacity estimates;
- cardinality control and data redaction;
- incident triage from symptoms to bottleneck.

Checkpoint: instrument one request across HTTP, database, and worker boundaries. Build a dashboard for request latency, errors, traffic, saturation, pool wait, queue age, and job failures. Use a load test to find one bottleneck and verify an improvement.

Read: [Observability](../docs/04-production/observability.md) and [performance](../docs/04-production/performance-and-scalability.md).

## Stage 11: Architecture and system design

Learn:

- transaction boundaries and invariants;
- feature modules, service layers, repositories, ports, and adapters;
- modular monolith and service extraction criteria;
- consistency, idempotency, queues, and failure recovery;
- capacity, data partitioning, caching, and migration strategy;
- security and observability as design inputs.

Checkpoint: design a payment or notification system. State requirements and SLOs, API and data model, consistency boundaries, duplicate handling, scaling path, failure recovery, authorization, metrics, and explicit tradeoffs. Defend why each component exists.

Read: [Backend project structure](../backend-project-structure.md) and [system design case studies](../architecture/system-design-case-studies.md).

## Suggested portfolio sequence

1. Basic CRUD with deliberate HTTP semantics.
2. Multi-user project API with PostgreSQL, migrations, and authorization.
3. File-processing API with object storage, durable jobs, and idempotency.
4. Production service with containers, CI, metrics, tracing, and load-test evidence.
5. RAG or AI API with usage accounting, streaming, queued work, and retrieval evaluation.

For every project, write a short architecture decision record, a threat model, an operations runbook, and one account of a failure you induced and diagnosed. Those artifacts demonstrate engineering judgment better than a long dependency list.

[Back to documentation map](../README.md)
