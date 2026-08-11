# Scenario-Based Interview Questions

For incident questions, separate investigation from redesign. State what you would observe before prescribing a component. For system questions, state assumptions and the failure contract.

## Scenario 1: Latency rises under traffic

> The FastAPI API receives 50,000 requests per minute. Response time rose from 100 ms to 3 seconds. How do you investigate?

### Short answer

Confirm the time window, affected routes, status classes, and latency distribution. Correlate traffic and deploy changes, then decompose latency with traces and saturation metrics: event-loop lag, in-flight requests, worker utilization, database pool wait, query time, cache behavior, provider calls, and proxy queueing. Mitigate load while finding the first saturated resource.

### Investigation path

1. Compare p50, p95, and p99 by route template and replica.
2. Check error and timeout changes, not latency alone.
3. Inspect application concurrency, CPU, memory, event-loop lag, and thread-pool queue.
4. Split database time into pool acquisition and SQL execution.
5. Inspect database CPU, I/O, locks, active queries, and query fingerprints.
6. Inspect downstream connection pools, rate limits, and retry counts.
7. Compare current and previous deploy, configuration, traffic mix, and payload size.

### Senior-level discussion

At 833 requests per second, concurrency depends on service time and fan-out. Three-second latency implies roughly 2,500 in-flight requests if arrivals continue, which can cause a feedback loop. Apply admission limits, shed optional work, or roll back before every pool is consumed. Add capacity only after the bottleneck and database connection budget are understood.

### Common follow-ups

- What if CPU is low everywhere?
- How do you detect coordinated omission in the load test?
- Would you add Redis?

## Scenario 2: Database CPU is 95 percent

> Database CPU is at 95 percent but application CPU is 20 percent. What do you investigate?

### Short answer

Find which SQL fingerprints consume total database time and calls. Inspect plans, scanned rows, sort spills, indexes, lock churn, transaction duration, and recent traffic or schema changes. Correlate the queries to routes and jobs.

### Deeper explanation

Low application CPU is expected when the application mostly waits on SQL. Common causes are N+1 calls, a missing or unusable index, changed selectivity, a large offset, an unbounded background query, or too many concurrent connections. More API replicas can make the database overload worse.

### Practical response

Cancel or throttle a runaway job if safe, reduce admission to an expensive endpoint, and capture the plan with production-like parameters. Fix the query or index, then validate total time and tail latency under load. Do not add an index without considering write cost and whether the query can use its leading columns.

## Scenario 3: Expensive AI operation times out

> An endpoint performs an expensive AI operation and users time out. How do you redesign it?

### Short answer

If the result is needed interactively and fits a bounded deadline, stream it with SSE and expose cancellation. If it may take minutes or must survive disconnects, create a durable job, return 202 with a status URL, and process it in a capacity-limited worker or provider background mode.

### Deeper explanation

Persist job status, prompt and model version, provider request ID, token usage, cancellation intent, result, and a sanitized error. Use an idempotency key for creation. Queue messages carry the job ID, and duplicate delivery must not duplicate cost or notification.

### Senior-level discussion

Set per-tenant budgets and workload concurrency before starting provider work. Use bounded retries inside a deadline, signed idempotent completion webhooks, and usage reconciliation. SSE improves perceived latency but does not make work durable.

## Scenario 4: Database connections are exhausted

> Requests intermittently fail with pool timeouts after increasing Uvicorn workers.

### Short answer

Calculate total possible connections across replicas and processes, then inspect pool wait and transaction duration. The worker increase multiplied pools and likely exceeded the database budget or exposed slow transactions.

### Investigation path

- Verify one session per request and close on every path.
- Find idle-in-transaction and long-running transactions.
- Check whether streaming routes hold sessions unnecessarily.
- Count web, worker, scheduler, migration, and administrative pools.
- Inspect query latency and lock waits.
- Reduce pool or worker concurrency and shed load while fixing the cause.

### Senior-level discussion

A pooler can reduce backend connection overhead but cannot make unlimited concurrent queries cheap. Size the full fleet, keep transactions short, and alert on pool acquisition latency before timeouts.

## Scenario 5: Duplicate payment after a timeout

> The client timed out, retried `POST /payments`, and the customer was charged twice.

### Short answer

Stop or gate the endpoint, reconcile provider records, and implement a durable idempotency contract scoped to the account and operation. Forward a stable key to the provider and treat a timeout as ambiguous, not failed.

### Deeper explanation

Claim the key under a unique constraint with a canonical request hash. A repeated matching request returns the stored or pending result; a different payload returns 409. Persist payment attempts and use provider lookup or webhooks to resolve unknown outcomes.

### Senior-level discussion

No amount of client-side button disabling solves network ambiguity. Define compensation and customer support flows, audit affected charges, and test a crash after provider success but before local persistence.

## Scenario 6: Cross-tenant data leak

> One tenant receives another tenant's cached project response.

### Short answer

Treat this as a security incident: disable the cache path, contain exposure, preserve evidence, notify the response team, and identify affected principals and records. The likely root is a cache key missing tenant or permission scope.

### Deeper explanation

Audit every data path, including database filters, cache keys, object storage, search index, jobs, and exports. Fix the key and invalidation, but also enforce tenant scope in repository interfaces and consider database row-level security as defense in depth.

### Senior-level discussion

Add cross-tenant negative tests that run against real cache and persistence adapters. Avoid logging sensitive leaked content during investigation. Key schema version, tenant, principal-policy version, resource, and representation dimensions where they affect authorization.

## Scenario 7: Celery job sends duplicate emails

> A worker sometimes sends the same email twice even though the task was acknowledged.

### Short answer

Assume at-least-once delivery. Give the notification a stable ID, persist its send state, and use a provider idempotency feature if available. Make the handler return success when the same logical send is already complete.

### Deeper explanation

A worker can send successfully and crash before acknowledgement or local state update. If the provider lacks idempotency, exact prevention may be impossible across the network boundary. Reconcile provider message IDs and design product tolerance.

### Senior-level discussion

Outbox solves creation of the send command, not exactly-once provider delivery. Measure duplicate rate, distinguish marketing from security mail, and choose stronger controls for high-impact messages.

## Scenario 8: Migration locks a large table

> A deployment adds a column and index. Writes stop for several minutes.

### Short answer

Mitigate by stopping or cancelling the blocking migration when safe, roll back application admission if required, and inspect the lock graph. Redesign the migration based on exact PostgreSQL version and operation behavior.

### Deeper explanation

Use expand-contract. Add compatible schema, create large indexes with the appropriate online mechanism, backfill in bounded batches, validate constraints separately, and remove old schema later. Set lock timeouts so a migration fails instead of waiting behind traffic and then blocking everything.

### Senior-level discussion

Test on production-scale data and monitor replication lag, I/O, lock wait, and application errors. A schema rollback may not undo partially transformed data safely, so write forward-recovery steps before deployment.

## Scenario 9: Redis outage causes database collapse

> Redis fails. The cache falls back to PostgreSQL, which then becomes unavailable.

### Short answer

The cache failed open without protecting the origin. Shed load, serve stale data where allowed, and restore Redis while limiting fallback concurrency.

### Deeper explanation

Add per-key request coalescing, TTL jitter, stale-while-revalidate, and an origin admission budget. Precompute or retain a local stale snapshot for critical reference data. Not every cache needs the same outage behavior.

### Senior-level discussion

Capacity-plan the origin for a chosen cache-loss fraction or explicitly degrade features. A cache should improve capacity, not make an ordinary dependency outage cascade into total failure.

## Scenario 10: WebSocket memory grows continuously

> A chat service's memory grows with connection count and does not fall after clients leave.

### Short answer

Inspect per-connection tasks, outbound queues, subscription cleanup, retained message history, and disconnect exception paths. Bound queues and ensure every connection deregisters and cancels child tasks in `finally`.

### Deeper explanation

Slow clients often cause unbounded queued messages. Choose a policy: drop replaceable presence events, disconnect lagging clients, or apply upstream backpressure. Use heap profiles and connection lifecycle metrics to prove which objects remain referenced.

### Senior-level discussion

Across replicas, keep durable chat in a database and use pub/sub for live fan-out. Deploy drain behavior should tell clients to reconnect and remove subscriptions even when termination interrupts a socket.

## Scenario 11: Third-party outage creates retry storm

> A shipping provider slows down. Your service's traffic to it increases sixfold.

### Short answer

Multiple layers are retrying while calls stay in flight. Disable duplicate retry layers, lower concurrency, apply a circuit breaker or load shedding, and serve a documented degraded response.

### Deeper explanation

Use connect and operation timeouts shorter than the end-to-end deadline, selected retryable errors, bounded exponential backoff with jitter, and a global workload limit. Queue non-interactive operations rather than holding request capacity.

### Senior-level discussion

Provider slowness consumes your HTTP connection pool, memory, and worker slots even before errors appear. Alert on dependency latency and in-flight work, not only failure rate. Test recovery so half-open probes do not restart the storm.

## Scenario 12: Search returns stale RAG sources

> A RAG API answers from a superseded policy after a new version is uploaded.

### Short answer

Trace the document, extraction, chunking, embedding, active index version, retrieval filter, cache key, and answer source mapping. Verify the new version reached ready and the collection switched atomically.

### Deeper explanation

The prompt is not the first suspect. Old chunks may remain active, a cache may omit collection version, or reranking may prefer the old text. Add effective-date policy and an evaluation case for superseded documents.

### Senior-level discussion

Define an ingestion freshness SLO, immutable index versions, atomic cutover, rollback, and reconciliation for partial pipelines. Preserve old versions for audit while excluding them from ordinary retrieval.

## Scenario 13: Authentication works, authorization does not

> Every user has a valid JWT, but users can update resources they do not own.

### Short answer

JWT validation establishes a principal. It does not authorize the target resource. Load or update the resource under tenant and permission conditions, and fail before side effects.

### Practical response

Use a repository method such as `get_editable_project(principal, project_id)` or an explicit policy after a tenant-scoped load. Add negative tests for same-tenant non-owner, cross-tenant user, revoked membership, and administrator boundaries.

### Senior-level discussion

Prefer queries that include authorization conditions when this prevents leaks and races. Centralize policy vocabulary, audit high-risk decisions, and avoid putting stale role lists into long-lived tokens.

## Scenario 14: Queue backlog grows but workers are idle

> Job age rises while worker CPU and memory remain low.

### Short answer

Inspect broker delivery, routing keys, consumer subscriptions, prefetch, leases, dependency pool wait, rate limits, and jobs stuck in retry delay. Low CPU often means workers wait on I/O or do not receive the queue.

### Deeper explanation

Break job time into queue wait, claim, execution stages, and retry delay. Check a poison partition or account-ordering key that serializes too much work. Verify autoscaling uses queue age and throughput rather than CPU only.

### Senior-level discussion

Scale only after identifying the constrained stage. More consumers can overwhelm PostgreSQL or a provider. Isolate workload classes and apply admission when the backlog threatens its completion SLO.

## Scenario 15: Works locally, fails behind Nginx

> Large uploads return 413 and SSE responses arrive all at once in production.

### Short answer

The reverse proxy enforces body limits and buffers responses independently of FastAPI. Configure intentional upload limits at both layers and disable or adjust buffering for the SSE route.

### Deeper explanation

The proxy, load balancer, ASGI server, and application each have timeouts and size limits. Align them with the API contract. Do not remove upload limits; stream to bounded storage and validate actual content.

### Senior-level discussion

Test through the real ingress path. Direct ASGI tests cannot verify proxy buffering, trusted headers, TLS redirects, or maximum body behavior.

## How to score a scenario answer

A strong answer:

- establishes scope and user impact;
- names evidence and ordering of investigation;
- provides a safe mitigation before a permanent fix;
- follows the request through every relevant queue or network boundary;
- discusses duplicates, timeouts, cancellation, and deployment overlap;
- states which metric or test proves the fix;
- distinguishes an inference from a confirmed fact.

[Previous: Senior](senior.md) | [Back to guide](README.md) | [Topic drills](topic-drills.md)
