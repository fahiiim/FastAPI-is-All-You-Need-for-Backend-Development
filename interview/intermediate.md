# Intermediate Interview Questions

Intermediate answers should connect FastAPI features to session lifecycle, concurrency, testing, and deployment behavior.

## 1. When should a FastAPI endpoint use `async def`?

### Short answer

Use `async def` when the request path awaits non-blocking I/O through async clients. Keep a synchronous path synchronous when its libraries block. CPU-heavy or durable work belongs in processes or workers, not on the event loop.

### Deeper explanation

An event loop switches tasks when a coroutine awaits. A blocking database driver or `requests.get()` does not yield, so it stalls other coroutines in that process. Async improves concurrency, not single-request CPU speed.

### Practical example

An endpoint using `AsyncSession` and an async HTTP client can await both. A legacy PDF renderer can be offloaded to a bounded thread pool; a ten-minute render should be a queued job.

### Senior-level discussion

The concurrency budget includes downstream pools, provider limits, memory per request, and timeouts. Unbounded `gather()` can overload a dependency faster than synchronous code.

### Common follow-ups

- How does FastAPI run a normal `def` route?
- Is `AsyncSession` safe to share across tasks?
- What happens on cancellation?

## 2. Explain SQLAlchemy session lifecycle

### Short answer

A session is a mutable unit-of-work and identity-map boundary. Create one per request or job, use it for one sequential transaction flow, commit at the application boundary, roll back on failure, and close it deterministically.

### Practical example

A `yield` dependency provides the session. Repositories use it but do not commit independently, allowing an order update and outbox insert to commit together.

### Senior-level discussion

Do not share a session across threads or concurrent async tasks. Long transactions occupy pool connections and retain locks or snapshots. `expire_on_commit` and lazy loading affect whether mapping after commit triggers more I/O.

## 3. How do you prevent N+1 queries?

Define the data needed for the use case and choose an eager-loading or explicit projection strategy in the query. Inspect SQL and test query count on critical paths.

`selectinload` often fits collections; `joinedload` may fit a small many-to-one relationship but can multiply rows for collections. The choice depends on cardinality and pagination. Serializing an ORM graph with lazy relationships is not a loading strategy.

## 4. Where should transactions begin and end?

The application use case normally owns the transaction because it knows which operations form one business action. Repositories should not hide commits. The route maps the result to HTTP after the transaction outcome is known.

External calls cannot join the SQL transaction. Use a state machine or transactional outbox rather than holding locks while calling a provider.

## 5. How does FastAPI dependency caching work?

Within one request, FastAPI reuses the result of the same dependency callable and parameter set by default. This allows several dependencies to share one session or principal. `use_cache=False` requests another evaluation.

Cleanup for a `yield` dependency runs according to the dependency and response lifecycle. Streaming and background behavior deserve explicit tests if cleanup timing matters.

## 6. Middleware or dependency for authentication?

A dependency is usually the better FastAPI boundary when routes declare authentication requirements and OpenAPI must describe them. Middleware can establish coarse connection or request context across all routes. Resource-level authorization belongs after the resource is identified, usually in a dependency or application policy.

Whichever path is chosen, avoid querying the user twice and distinguish authentication from authorization.

## 7. Access tokens and refresh tokens

Access tokens are short-lived credentials presented to resource endpoints. Refresh tokens obtain new access tokens and have longer-lived security state. Rotation detects replay by invalidating a token family when an already-used refresh credential reappears.

Store refresh tokens hashed if the server needs comparison, bind them to a session or device record, and make revocation and logout semantics explicit. A JWT access token is not automatically revoked when a user logs out.

## 8. How do you hash passwords?

Use a maintained password-hashing library with an adaptive algorithm such as Argon2id, a per-password salt, and a calibrated work factor. Store the encoded hash, never reversible encryption. Rehash after successful login when policy changes.

Rate-limit login, avoid user-enumeration detail, and treat password reset as a separate credential flow.

## 9. How would you test a FastAPI dependency?

Unit-test its underlying function where possible. For route wiring, use `app.dependency_overrides` in a tightly scoped fixture and clear overrides after the test. Keep some API tests with real authentication and database dependencies so overrides do not hide wiring errors.

Use a real PostgreSQL test instance for behavior that depends on PostgreSQL constraints, isolation, or SQL.

## 10. `TestClient` or `AsyncClient`?

Use `TestClient` for straightforward synchronous tests against the ASGI app. Current Starlette releases prefer its `httpx2` transport. Use `httpx2.AsyncClient` with ASGI transport when the test itself awaits async fixtures or needs async concurrency behavior. Lifespan handling must be explicit in either setup.

The client choice does not decide test scope. Both can exercise a fully wired API or a heavily overridden unit-style test.

## 11. What belongs in a service layer?

A service or use-case function coordinates business policy, repositories, integrations, and a transaction for one application operation. It should not know HTTP exceptions or construct global clients.

Do not add a service that simply calls `repository.get()` for every route. Use the layer when it creates a useful business and test boundary.

## 12. When is a repository useful?

Use one when persistence queries need domain names, loading or lock rules are reusable, or application code needs a port independent of SQLAlchemy mappings. Avoid a generic CRUD repository that hides `select()` without hiding complexity.

Repositories do not make databases interchangeable for free. SQL semantics, constraints, and query needs still shape the application.

## 13. How should configuration work?

Load environment-supplied values into a typed settings object at startup, validate required and mutually dependent fields, and inject the settings or derived clients. Commit safe defaults and an `.env.example`, not secrets.

Avoid reading the environment throughout business code. A deployment should fail clearly before receiving traffic if essential configuration is invalid.

## 14. What should logging middleware record?

Record timestamp, level, service, environment, request ID, trace ID, route template, method, status, and duration. Add principal or tenant references only under the data policy. Never make raw URLs, request bodies, tokens, or exception messages metric labels.

Streaming responses require timing definitions: headers sent, first byte, and stream completion are different events.

## 15. When should you use Redis?

Use Redis for measured shared low-latency or expiring state such as a cache, rate-limit counter, session, or short-lived idempotency result. Define source of truth, key scope, TTL, invalidation, memory policy, and outage behavior.

An indexed PostgreSQL query may be simpler and fast enough. Redis adds a network and operational dependency.

## 16. `BackgroundTasks` or Celery?

Use `BackgroundTasks` for short best-effort work that may be lost with the process. Use a durable queue and workers when work must survive restart, retry, schedule, scale independently, or expose job state.

Queue delivery can duplicate. Handlers need idempotency, bounded retries, acknowledgement policy, and dead-letter handling.

## 17. How do you make a webhook receiver reliable?

Read the raw body, verify signature and timestamp, persist the provider event ID under a unique constraint, acknowledge quickly, and process asynchronously. Make the state transition idempotent. Retain enough metadata for replay and audit without logging secrets.

The sender will retry on timeouts, so doing slow work before acknowledgement increases duplicates.

## 18. What makes a Docker image production-ready?

Use an immutable, reproducible, minimal image; install only runtime dependencies; run as non-root; copy code with intentional cache layers; handle signals; expose a health contract; and keep secrets outside the image. A multi-stage build is useful when compilation tools are not needed at runtime.

One container can run one application process when the orchestrator handles replication. Worker count still depends on deployment and workload, not a copied formula.

## 19. Readiness or liveness?

Liveness answers whether the process is stuck and should restart. Readiness answers whether it should receive traffic. A database outage should not necessarily fail liveness and trigger a restart storm. Startup can have its own probe while migrations or model loading completes.

## 20. How do you handle pagination?

Validate a bounded page size and deterministic order. Offset pagination is simple for small stable sets. Cursor pagination is better for large changing feeds when it seeks through an index on a unique ordering tuple.

Never fetch the entire table and slice in Python. Return navigation metadata that matches the consistency guarantees the API can provide.

## Practical exercise

Add authenticated project membership to a FastAPI application. Implement:

- one request-scoped session;
- a policy that prevents cross-project reads;
- a cursor-paginated activity endpoint;
- a transaction that writes an activity row with the change;
- API tests using a real PostgreSQL test database;
- a container and readiness endpoint.

Explain which tests may use overrides and which should exercise real wiring.

[Previous: Beginner](beginner.md) | [Back to guide](README.md) | [Next: Advanced](advanced.md)
