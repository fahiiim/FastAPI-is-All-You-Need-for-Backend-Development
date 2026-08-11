# Advanced Interview Questions

Advanced questions test whether the candidate can reason about overlapping transactions, resource saturation, retries, and evidence from production systems.

## 1. Your async API is slow under concurrency. What do you inspect?

### Short answer

Break latency into event-loop delay, application time, pool wait, query time, provider time, serialization, and proxy time. Check whether any blocking work runs on the loop and whether downstream capacity is smaller than request concurrency.

### Deeper explanation

Async code can queue invisibly at a database pool, HTTP client pool, semaphore, thread pool, or provider. More concurrent coroutines increase throughput only until a constrained resource saturates. Past that point, queueing raises tail latency.

### Practical example

Trace one slow endpoint. If SQL execution takes 20 ms but connection acquisition takes 800 ms, adding Redis or changing JSON serialization misses the problem. Inspect transaction duration and total connections across replicas before increasing the pool.

### Senior-level discussion

Compare p50, p95, and p99, event-loop lag, in-flight requests, pool wait, database saturation, and timeouts. Apply admission control so overload fails predictably rather than consuming every resource.

### Common follow-ups

- How do you detect blocking event-loop work?
- Why can a larger pool make the database slower?
- Where would you enforce concurrency limits?

## 2. Explain transaction isolation using a booking example

At Read Committed, each statement can observe a new committed snapshot. Two transactions can both read available capacity and then try to reserve. A unique or exclusion constraint, row lock, atomic conditional update, or Serializable transaction must protect the invariant.

Repeatable Read gives a stable transaction snapshot in PostgreSQL but can still require retry when writes conflict. Serializable detects executions that cannot be ordered safely and aborts one transaction. The application must retry the entire transaction with a bound and only if its external effects are safe.

## 3. How do you prevent lost updates?

Options depend on contention and user semantics:

- an atomic update with a predicate, such as decrementing stock only when stock is positive;
- pessimistic locking with `SELECT ... FOR UPDATE` for a short transaction;
- optimistic concurrency with a version column and 409 on mismatch;
- Serializable isolation with transaction retry.

Reading, modifying in Python, and writing without a version or lock loses an overlapping update.

## 4. How should connection pools be sized?

### Short answer

Size from the database's total connection budget, number of application processes, workload concurrency, query duration, and acceptable pool wait. Count web, worker, migration, and administrative connections together.

### Practical example

Ten replicas with four processes and a pool of 20 can attempt 800 base connections before overflow. If PostgreSQL safely supports 200 for this workload, the local-looking setting is impossible.

### Senior-level discussion

Connections are not throughput by themselves. Too many active queries increase CPU, I/O, memory, and lock contention. A pooler may reduce connection setup and backend count but does not repair slow transactions.

## 5. How do you diagnose N+1 queries in an async API?

Capture SQL statements per request, identify a count that grows with result rows, and find lazy relationship access during mapping or serialization. Reproduce with realistic cardinality. Choose projection, `selectinload`, `joinedload`, or a separate aggregate query based on shape.

Async ORM access may fail instead of quietly lazy-loading, which is useful pressure to make loading explicit. Test query bounds for important endpoints without coupling every test to an exact harmless query count.

## 6. What is the transactional outbox pattern?

### Short answer

Write application state and an outgoing event record in the same database transaction. A separate publisher reads unpublished outbox rows, sends them, and marks progress. This closes the crash gap between commit and publish.

### Deeper explanation

Publishing can still duplicate if the process crashes after the broker accepts the event but before the outbox row is marked. Consumers need idempotency or inbox deduplication. The outbox provides eventual delivery, not exactly-once end-to-end effects.

### Common follow-ups

- How do you order events per aggregate?
- How are old outbox rows cleaned?
- What happens if publish succeeds but marking fails?

## 7. What does at-least-once delivery mean for a worker?

The same message may be delivered more than once. A worker should use a stable operation ID, make the durable state transition conditional, and return success for an already-completed equivalent operation. A deduplication table alone needs a transaction relationship to the side effect it guards.

For an external payment, use the provider's idempotency key and persist the attempt state. Do not acknowledge before the required durable effect.

## 8. How do retry storms happen?

Retries at the load balancer, service client, SDK, and worker multiply attempts. During a dependency slowdown, synchronized retries add load, increase latency, and cause further timeouts.

Assign a retry owner where possible, use exponential backoff with full jitter, respect an end-to-end deadline, limit concurrency, and shed low-priority work. A circuit breaker can stop futile attempts but requires careful half-open behavior.

## 9. Design idempotency for `POST /payments`

Scope the key to the authenticated account and operation. Store key, canonical request hash, state, response, and expiry under a unique constraint. The first request claims the key. A matching completed request returns the stored response; a different payload returns 409; an in-progress request returns the documented pending behavior.

Pass a stable idempotency key to the payment provider. Persist the local payment state and reconcile ambiguous timeouts by querying the provider. Do not simply cache 201 in Redis and assume it is the source of truth.

## 10. How do you invalidate a cache safely?

### Short answer

Define the database as source of truth, invalidate only after commit, include permission and schema dimensions in keys, and accept a documented staleness window. Use an outbox or versioned key when a crash between commit and delete matters.

### Deeper explanation

Delete-after-commit can race with a reader that fetched old data just before commit and writes it after deletion. Versioned keys or carefully designed write-through behavior avoid this class. Stampede control and Redis outage policy are separate decisions.

## 11. How would you implement distributed rate limiting?

Use an atomic token-bucket or sliding-window operation in a shared store, keyed by the real policy identity and resource. Keep coarse abuse controls at the edge and cost-aware tenant or workload controls in the application.

Define trusted proxy headers, clock assumptions, burst size, refill rate, response headers, and fail-open or fail-closed behavior. Protect the limiter itself from unbounded keys.

## 12. How do you deploy a zero-downtime database change?

Use expand, migrate, contract:

1. Add backward-compatible schema.
2. Deploy code that can work with old and new representations.
3. Backfill in bounded, restartable batches.
4. Switch reads and writes, then verify.
5. Remove old columns or constraints in a later deployment.

Avoid table rewrites or long validation locks in peak traffic. Autogenerated migration text must be reviewed against PostgreSQL behavior and deployment overlap.

## 13. What should an observability design include?

Logs provide detailed events, metrics show aggregate trends and alert efficiently, and traces connect causally related operations. Propagate W3C trace context and request or correlation IDs through HTTP and messages.

Start with traffic, errors, latency, and saturation. Add pool wait, query time, queue age, retry counts, cache effectiveness, and business outcomes. Keep metric labels bounded; high-cardinality IDs belong in logs and traces.

## 14. How do you investigate high database CPU with low app CPU?

Inspect database wait events, top SQL by total time, call frequency, query plans, scanned rows, locks, temporary files, buffer hit behavior, and recent schema or traffic changes. Correlate query fingerprints to routes and deploys.

Likely causes include missing or unusable indexes, N+1 calls, expensive sorts, changed statistics, lock churn, a background job, or connection overload. Do not increase application replicas before identifying the query workload.

## 15. WebSockets across multiple FastAPI replicas

Connections live in the process that accepted them. Authenticate at handshake, track local connections, and route external events through shared pub/sub or streams. Durable chat state belongs in a database; pub/sub is only live fan-out.

Handle slow consumers with bounded buffers, disconnect and reconnect, connection drain on deploy, and sequence-based recovery if missed events matter. Sticky sessions alone do not route worker-produced events.

## 16. How do you secure a multi-tenant query path?

Derive tenant from the authenticated principal or trusted server context, never from an unchecked client claim. Require tenant scope in repository APIs, database queries, cache keys, object keys, and jobs. Composite uniqueness often includes tenant ID.

Use PostgreSQL row-level security as defense in depth when appropriate, with tests that fail if application filters are removed. Authorization also covers actions within the tenant, not only tenant matching.

## 17. What is graceful shutdown for FastAPI?

Stop accepting new work, mark readiness false, allow in-flight requests to finish within a bound, stop consumers from claiming new jobs, extend or release job leases correctly, flush critical telemetry, and close clients and pools.

The platform termination grace period must exceed the application drain budget. Long SSE or WebSocket connections need an explicit reconnect signal or termination policy.

## 18. How would you load-test an API?

State the workload mix, data distribution, arrival pattern, concurrency, warm-up, duration, and success criteria. Use production-like indexes and payloads. Observe client latency and errors alongside server saturation, database waits, pools, queues, and dependency behavior.

Avoid coordinated omission by using an arrival model that records requests that should have started during server stalls. A passing average hides tail latency and errors.

## Design exercise

Design a webhook ingestion service that receives 10,000 events per second, preserves per-account ordering, and calls a slow downstream API.

A strong discussion covers signature verification, edge limits, raw-event persistence, partition key, queue retention, idempotency, ordered consumption per account, downstream concurrency and deadline, retry and dead-letter policy, replay, tenant isolation, backpressure, metrics, and how schema versions evolve.

[Previous: Intermediate](intermediate.md) | [Back to guide](README.md) | [Next: Senior](senior.md)
