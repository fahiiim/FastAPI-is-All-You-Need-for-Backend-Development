# Common Backend Mistakes

The mistakes below are grouped by where they tend to appear, not by who is allowed to make them. Experienced engineers still create basic failure modes when moving quickly.

## Beginner mistakes

### Business logic in route functions

**Why it hurts:** HTTP parsing, policy, SQL, and provider calls become one unit that is difficult to test or reuse.

**Better:** keep the route as a transport adapter and move a real workflow into a use-case function. Do not add a pass-through service when no workflow exists.

### Reusing one schema for requests, responses, and database rows

**Why it hurts:** writable fields leak into responses, database-only columns become required input, and password hashes can be serialized.

**Better:** use purpose-specific request and response schemas. Map deliberately at boundaries.

### Returning 200 for every outcome

**Why it hurts:** clients cannot distinguish creation, validation, conflict, absence, or authorization failure without parsing custom strings.

**Better:** use HTTP semantics consistently and document an error envelope.

### Catching `Exception` in every route

**Why it hurts:** programming errors become misleading 400 responses and lose useful diagnostics.

**Better:** raise typed application errors and map expected errors centrally. Let unexpected errors reach a last-resort 500 handler and error tracking.

### Treating CORS as authentication

**Why it hurts:** CORS constrains participating browsers. Non-browser clients can still call the API.

**Better:** authenticate and authorize every protected operation. Configure exact browser origins separately.

### Committing `.env`

**Why it hurts:** Git history preserves credentials after the file is deleted.

**Better:** commit `.env.example`, load real secrets through the environment or a secret manager, scan commits, and rotate any exposed secret.

### Trusting an uploaded filename

**Why it hurts:** filenames can contain path traversal, collisions, control characters, or misleading extensions.

**Better:** generate object keys, keep the display name as metadata, inspect content, limit size, and scan before parsing.

### Using `async def` everywhere

**Why it hurts:** a blocking database driver or HTTP library stalls the event loop.

**Better:** use an async stack end to end for non-blocking I/O, or keep the route synchronous. Queue long and CPU-heavy work.

## Intermediate mistakes

### Sharing a SQLAlchemy session

**Why it hurts:** sessions hold mutable transaction and identity-map state and are not safe across concurrent tasks.

**Better:** one `Session` per thread or `AsyncSession` per task, usually one per request or job, with deterministic cleanup.

### Letting repositories commit

**Why it hurts:** an application service cannot combine multiple writes atomically and tests cannot identify the transaction boundary.

**Better:** repositories flush when identifiers are needed; the use case or unit of work commits once.

### Checking uniqueness only in application code

**Why it hurts:** concurrent requests can both pass the check.

**Better:** preserve the friendly pre-check if useful, but enforce a unique constraint and translate its violation.

### Lazy-loading during response serialization

**Why it hurts:** serialization triggers hidden queries, creates N+1 behavior, or fails after an async session closes.

**Better:** define the loading plan in the query and map to a response DTO before leaving the data boundary.

### Offset pagination on a hot, large feed

**Why it hurts:** large offsets get slower and inserts shift positions between requests.

**Better:** seek by a deterministic cursor whose columns match an index.

### Retrying every provider error

**Why it hurts:** validation errors never recover and simultaneous retries amplify an outage.

**Better:** retry selected transient failures with a deadline, bound, exponential backoff, and jitter. Ensure writes are idempotent.

### Sending email or processing files in `BackgroundTasks`

**Why it hurts:** web-process termination loses work and task volume competes with requests.

**Better:** create a durable job and use a worker when delivery matters or work is substantial.

### Treating JWT as encrypted or revocable by default

**Why it hurts:** signed claims are readable by the holder and remain valid until expiry unless a revocation design exists.

**Better:** keep sensitive data out, use short lifetimes, validate issuer/audience/algorithm/time claims, and design refresh rotation or revocation for the threat model.

### Broad dependency overrides in tests

**Why it hurts:** a fake authentication dependency can make every permission test pass while production wiring is broken.

**Better:** use overrides narrowly, keep authorization tests against real policy, and include wiring-level API tests.

### Mocking SQLAlchemy query chains

**Why it hurts:** mocks reproduce assumptions rather than database behavior.

**Better:** unit-test policy without SQLAlchemy and integration-test queries against the actual database engine.

### Caching without an invalidation story

**Why it hurts:** stale data becomes a correctness incident, and permission changes may not take effect.

**Better:** define owner, key dimensions, freshness, invalidation, stampede control, and outage behavior before adding the cache.

### Unbounded file reads

**Why it hurts:** one upload can exhaust worker memory or occupy connections indefinitely.

**Better:** limit at the proxy and application, stream to bounded storage, and enforce decompressed-size and parser limits.

## Experienced-engineer mistakes

### Splitting services before defining module boundaries

**Why it hurts:** the result is a distributed monolith with synchronous call chains and shared data.

**Better:** enforce capability ownership in a modular monolith first. Extract when ownership, release, isolation, or scaling pressure is demonstrated.

### Assuming exactly-once delivery

**Why it hurts:** acknowledgements, process crashes, and network uncertainty create duplicates even when the broker offers strong features.

**Better:** make effects idempotent, deduplicate at a durable boundary, and reconcile state.

### Publishing an event after commit without an outbox

**Why it hurts:** a crash between database commit and publish loses the event.

**Better:** write the state change and outbox row in one transaction, then publish asynchronously.

### Holding transactions open during provider calls

**Why it hurts:** locks and pool connections remain occupied during unpredictable latency, while the external action is still not atomic with SQL.

**Better:** shorten the transaction and model the external step as a state machine or outbox-driven operation.

### Increasing the connection pool before diagnosing

**Why it hurts:** more connections can increase database contention and exceed server limits.

**Better:** measure pool wait, query latency, transaction duration, database CPU and I/O, then size total connections across every process.

### High-cardinality telemetry

**Why it hurts:** metric systems become expensive or unusable when labels include request IDs, users, paths with identifiers, or exception messages.

**Better:** use bounded route templates and status classes in metrics. Put high-cardinality correlation fields in logs and traces.

### Logging complete request bodies

**Why it hurts:** credentials, personal data, prompts, and files enter long-lived systems with broad access.

**Better:** log metadata and allowlisted fields, redact at the source, and make sensitive-content logging an explicit controlled mode.

### Running incompatible migrations during deployment

**Why it hurts:** old and new application versions overlap while the schema satisfies only one.

**Better:** use expand, migrate, contract. Add compatible columns or tables, backfill, switch reads and writes, then remove old schema later.

### Retry storms

**Why it hurts:** every layer retries simultaneously during an outage and multiplies traffic.

**Better:** assign one retry owner where possible, apply global admission control, jitter retries, cap attempts, and use circuit breaking or load shedding.

### Distributed locks without fencing

**Why it hurts:** a paused holder can continue after its lease expires and race with a new holder.

**Better:** use source-of-truth constraints or a monotonic fencing token when stale holders can cause damage.

### Health checks that lie

**Why it hurts:** a liveness check tied to a database outage restarts every process, while a shallow readiness check sends traffic to an uninitialized process.

**Better:** liveness checks process health, readiness checks ability to serve required work, and dependency checks use short independent budgets.

### Autoscaling on CPU only

**Why it hurts:** I/O-bound APIs saturate pools or queues while CPU stays low.

**Better:** scale from a mix of request concurrency, latency, queue age, pool saturation, throughput, and workload-specific capacity.

### Building a generic platform too early

**Why it hurts:** abstractions encode guesses, hide important library features, and make normal changes require framework work.

**Better:** standardize measured repetition. Keep escape hatches and document the guarantee each shared component provides.

## Incident questions

When reviewing a mistake, ask:

1. Which guarantee did the team assume?
2. Which component actually owned that guarantee?
3. What signal would have detected the problem earlier?
4. Can a constraint or state machine prevent recurrence?
5. Does the fix introduce a new failure mode under retry, concurrency, or deploy overlap?

[Back to documentation map](../README.md) | [Production checklist](production-checklist.md)
