# Topic Drills

Use these prompts for rapid practice. Each answer should include the mechanism, one failure mode, and one practical example.

## Python

1. What guarantee does a context manager provide, and how does a `yield` dependency resemble one?
2. What is the difference between an iterator, generator, coroutine, and async generator?
3. Why are mutable default arguments dangerous?
4. When would you use a `Protocol` instead of an abstract base class?
5. How do exception chaining and `raise ... from exc` help operations?
6. What does cancellation do at an `await` point?
7. When do threads help despite the GIL?
8. Why can process pools be expensive?
9. What belongs in `pyproject.toml`?
10. How do circular imports reveal dependency-direction problems?

## HTTP and API design

1. Which HTTP methods are safe? Which are idempotent?
2. What does 401 mean compared with 403?
3. When is 409 more useful than 422?
4. What should a 201 response contain?
5. How do ETag and `If-Match` support optimistic concurrency?
6. Why should credentials not appear in a query string?
7. How does `Content-Type` differ from `Accept`?
8. What does `Vary: Origin` protect in a CORS response?
9. How do you version an API without breaking old clients?
10. When is an action resource clearer than CRUD?
11. How do you model a long-running operation?
12. What belongs in an idempotency-key record?

## FastAPI and Pydantic

1. How does route declaration order create conflicts?
2. What happens when request validation fails?
3. Why use response models when Python already has return annotations?
4. How does dependency caching affect a database session?
5. When should a dependency use `yield`?
6. Why should the application object be created in a factory or composition root?
7. How do lifespan and module import differ?
8. How do background tasks interact with response completion?
9. Why is reading a streaming response body in middleware risky?
10. How do you expose multiple authentication schemes in OpenAPI?
11. What does `model_validate(..., from_attributes=True)` do?
12. When should a Pydantic validator not query a database?

## Databases and SQLAlchemy

1. Why does a foreign key need an index on some query paths even though it enforces integrity without one?
2. How does column order affect a composite B-tree index?
3. What anomalies can occur at Read Committed?
4. What is MVCC?
5. What is an idle-in-transaction connection?
6. How does an identity map affect repeated loads?
7. What is autoflush and when can it surprise you?
8. Compare `joinedload` and `selectinload`.
9. Why can lazy loading break in async code?
10. Why should a repository not commit by default?
11. When is a savepoint useful in a test or transaction?
12. How do you inspect an execution plan safely?
13. Why does offset pagination slow down?
14. What makes a cursor stable?
15. Why must Alembic autogeneration be reviewed?

## Authentication and security

1. Why is password hashing deliberately slow?
2. What claims must a resource server validate in a JWT?
3. Why is a signed JWT not secret?
4. What is refresh-token replay detection?
5. Session cookie or bearer token: what changes in the threat model?
6. What is CSRF and when does SameSite help?
7. Why is wildcard CORS incompatible with credentialed browser requests?
8. How should API keys be stored and rotated?
9. How does RBAC differ from resource-level authorization?
10. Where can tenant scope be lost?
11. How do parameterized queries stop SQL injection?
12. How do you handle an uploaded archive safely?
13. Which forwarding headers can be trusted?
14. How would you respond to a committed secret?

## Testing

1. What is the difference between a unit and integration test in your service?
2. When is a fake better than a mock?
3. Why should PostgreSQL queries be tested on PostgreSQL?
4. How do dependency overrides hide security bugs?
5. How do you isolate database tests without masking commit behavior?
6. What should a migration test prove?
7. How do you test duplicate webhook delivery?
8. How do you test timeout and cancellation behavior?
9. What belongs in a contract test for a provider adapter?
10. Why can 100 percent line coverage still miss the main risks?
11. How do you make factories produce valid but varied data?
12. What must a load test observe besides client latency?

## Caching, jobs, and messaging

1. What is cache-aside?
2. What causes a cache stampede?
3. When should a cache fail open?
4. Why can invalidation after commit still race?
5. What does at-least-once delivery require from handlers?
6. When is `BackgroundTasks` sufficient?
7. What is the difference between a command and an event?
8. Why does an outbox still permit duplicate messages?
9. How do acknowledgement timing and visibility timeout interact?
10. When is Kafka justified over a task queue?
11. How do you prevent a poison message from blocking progress?
12. How do you make a scheduled job idempotent?

## Deployment and observability

1. Why should a container run as non-root?
2. What belongs in a multi-stage Docker build?
3. How do Uvicorn process count and pool size interact?
4. What is graceful termination?
5. Why should liveness not depend naively on PostgreSQL?
6. What is the trusted proxy boundary?
7. How does response buffering affect SSE?
8. What does an immutable artifact promotion model provide?
9. How do logs, metrics, and traces differ?
10. Why are user IDs poor metric labels?
11. What is a service-level objective?
12. Which signals reveal pool saturation?
13. What makes an alert actionable?
14. How do you correlate an HTTP request with a worker job?

## Architecture and system design

1. When does a service layer earn its cost?
2. When is a repository only indirection?
3. What is a bounded context?
4. Why is a modular monolith often a strong default?
5. What evidence justifies a microservice extraction?
6. How do synchronous call chains affect availability?
7. What is a compensating action?
8. How do you define data ownership between services?
9. How do you migrate a boundary without a flag day?
10. What is backpressure and where can it be applied?
11. How do you estimate concurrency from traffic and latency?
12. What would you degrade first during overload?
13. How do you design tenant fairness?
14. Which architecture decision deserves an ADR?
15. When should two services be merged?

## AI backends

1. When is SSE better than WebSockets for model output?
2. Why does streaming not make a model job durable?
3. How do you account for provider work after client disconnect?
4. What needs to be versioned with a prompt?
5. How do you prevent unbounded model cost?
6. Why is model output untrusted input?
7. Which fields belong in an AI job record?
8. How do you isolate bulk ingestion from interactive chat?
9. Where must RAG authorization filters apply?
10. How do you re-embed without a mixed index?
11. How do you evaluate retrieval separately from generation?
12. What lineage is needed to delete a document fully?

[Back to interview guide](README.md) | [Scenario questions](scenario-based.md)
