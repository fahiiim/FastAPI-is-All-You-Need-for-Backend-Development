# Senior Interview Questions

Senior questions rarely have one correct component diagram. A strong answer turns vague requirements into explicit guarantees, proposes the simplest design that meets them, and explains failure recovery and organizational cost.

## 1. How do you decide between a modular monolith and microservices?

### Short answer

Start with business boundaries, data ownership, team ownership, release independence, isolation, and scaling requirements. A modular monolith is the default when one deployment and local transactions meet the requirements. Extract a service when a stable boundary has demonstrated need for independent operation.

### Deeper explanation

Microservices replace in-process calls and transactions with network protocols, partial failure, compatibility management, and asynchronous consistency. They can improve autonomy and isolation, but only if data and release ownership are actually independent.

### Practical example

A CPU-heavy document conversion workload may become a separate worker deployment before the whole documents module becomes a service. That solves scaling and failure isolation without introducing a public service boundary.

### Senior-level discussion

Measure change coupling and incident blast radius. Require service identity, timeouts, tracing, deployment ownership, on-call, event contracts, and reconciliation before extraction. A shared database and coordinated release indicate a distributed monolith.

### Common follow-ups

- How do you find a bounded context?
- When would you merge services?
- Who owns shared reference data?

## 2. A service must process a payment and create an order. How do you handle consistency?

There is no ordinary atomic transaction across PostgreSQL and a payment provider. Model an order/payment state machine. Persist intent and an outbox event, call the provider with a stable idempotency key, persist the result, and reconcile ambiguous timeouts through provider lookup or webhooks.

Choose business semantics for each sequence. Authorizing payment before reserving inventory differs from reserving before authorization. Compensation may release a reservation or void an authorization; it does not pretend the world rolled back.

## 3. How do you design for 50,000 requests per minute?

### Short answer

Convert the rate to workload mix and concurrency using latency, then find the limiting resources. Validate SLO, payload, read/write ratio, cacheability, consistency, and burst. Scale stateless API replicas only after queries, pools, and downstream budgets are sound.

### Practical example

833 requests per second at 200 ms average implies roughly 167 in flight before bursts and tail latency. If each request uses two database queries for 20 ms, estimate database concurrency and calls per second, then load-test with real cardinality.

### Senior-level discussion

Add edge protection, admission limits, appropriate caching, replicas, read models, or partitioning in response to measured saturation. Plan overload behavior and degradation, not only normal capacity.

## 4. How do you design multi-tenancy?

Choose isolation from risk, customer needs, operational scale, and cost:

- shared tables with tenant keys;
- schemas per tenant;
- databases per tenant or tenant group;
- separate deployments for exceptional isolation.

Shared tables simplify fleet operations but demand mandatory query, cache, object, job, and telemetry scoping. Database-per-tenant improves isolation and restore options but creates migration and connection-fleet complexity. Hybrid placement is common.

Identity establishes tenant membership; authorization decides the resource action. Audit cross-tenant administration explicitly.

## 5. How do you reason about availability and consistency?

Name the invariant and the failure. Strong consistency may be required for a balance or unique reservation, while a search index or analytics view can lag. During a partition, a system that cannot safely verify a critical invariant may reject the operation rather than accept conflicting writes.

Do not quote CAP as "pick any two." Discuss partition behavior, read/write guarantees, recovery, and user-visible semantics for each data path.

## 6. What is your API versioning strategy?

Prefer compatible evolution: add optional fields, preserve meanings, and tolerate unknown response fields. Use contract tests and OpenAPI diffs. Introduce a new version when semantics or required shapes cannot remain compatible.

Versioning can live in paths, headers, or media types; operational clarity often makes path versioning practical. Support windows, deprecation signals, migration guides, usage telemetry, and removal authority matter more than syntax.

## 7. How do you run high-risk migrations?

Classify locks, rewrite behavior, table size, replication impact, rollback, and overlap with running binaries. Use online or low-lock operations where supported, validate constraints separately, create indexes concurrently where appropriate, and backfill in throttled resumable batches.

Test on production-scale data. Monitor lock wait, replication lag, I/O, error rate, and application behavior. The rollback may be a forward fix because reversing a partially completed data transform can be more dangerous.

## 8. How do you set SLOs for an API?

Define user-visible success and latency by endpoint or workload, then choose a measurement window and allowed error budget. Separate interactive reads from long jobs. A 202 accepted job needs enqueue availability plus completion-latency and terminal-success SLOs.

Alerts should burn error budget at meaningful rates, not fire on every single error. Dependencies and internal stages get supporting objectives, but the product SLO remains the decision anchor.

## 9. A cache improves p50 but worsens p99. Why?

Possible causes include cache miss stampede, Redis pool wait, large-value serialization, synchronized expiry, cross-zone latency, failover, or fallback overload. Split metrics by hit/miss and measure cache acquisition, origin latency, value size, and rebuild concurrency.

A cache is another queueing system. Add TTL jitter, request coalescing, bounded fallback, stale-while-revalidate, or remove low-value caching based on evidence.

## 10. How do you approach a production incident?

Stabilize user impact first: rollback, disable a workload, shed load, or fail over within pre-agreed authority. Establish timeline and scope, compare changes, inspect top-level traffic/error/latency/saturation, and follow traces or query fingerprints to a constrained resource.

Keep an incident log with decisions and evidence. Afterward, identify contributing system conditions rather than one human error, add prevention or detection, and verify the action under failure.

## 11. How do you design an authorization system that can evolve?

Represent permissions as actions on resource types, then evaluate tenant membership, resource attributes, ownership, state, and delegation in policy code. Roles group permissions but are not the entire policy.

Centralize policy logic enough for consistency while keeping resource loading efficient. Cache only with policy-version and subject/resource scope. Record decisions for high-risk actions without logging sensitive resource data.

## 12. How do you prevent one customer from consuming all capacity?

Apply quotas and admission control by tenant and workload, with global protection beneath them. Use weighted queues or reserved pools for priority classes. Limit in-flight work as well as request rate because slow expensive requests consume capacity differently from cheap reads.

Expose clear 429 or queued behavior, track usage and queue age, and design support overrides with expiry and audit. Autoscaling is not a fairness mechanism.

## 13. Build or buy a platform component?

Clarify whether the component is product differentiation or undifferentiated operations, then compare capability, lock-in, compliance, failure control, staffing, integration, migration, and total cost. A managed queue may reduce broker operations but still requires application idempotency and observability.

Run a small representative evaluation with explicit exit criteria. Record what would trigger migration rather than claiming a choice is permanent.

## 14. How do you review architecture proposals?

Start with functional requirements, SLOs, scale, data sensitivity, compliance, team ownership, and constraints. Trace critical write and read paths. Mark state owners, transactions, network boundaries, duplicate paths, recovery, authorization, and observability.

Challenge components that have no requirement. Ask how deployments overlap, how data is migrated or deleted, how the system fails under dependency outage, and which assumption is least certain. Capture decisions and revisit conditions.

## 15. How would you lead an async migration of a synchronous FastAPI service?

Do not convert syntax wholesale. Measure whether concurrency is limited by blocking I/O and whether async drivers are mature for required features. Select one vertical path, introduce async clients and session lifecycle, test cancellation and pool behavior, and load-test against the sync baseline.

Running sync and async database stacks together increases connection budgets and operational complexity. A well-tuned sync service with more processes may remain simpler and sufficient. Migration success is measured throughput, latency, and resource efficiency, not the percentage of `async def` functions.

## 16. Design a safe AI feature rollout

Define the product decision and failure tolerance, then build offline evaluations, security tests, cost estimates, token and concurrency limits, provider deadlines, and a provider-independent boundary. Version prompts and models, canary by tenant, and compare quality, latency, error, and cost.

Model output is untrusted. Authorize tools, validate structured output, preserve provenance, and provide a kill switch. Long work uses jobs; streaming has terminal state and disconnect accounting. Data retention and provider policy are architecture inputs.

## 17. How do you communicate technical debt?

Describe the concrete risk or recurring cost, evidence, affected objective, remediation options, and the deadline created by growth or change. "The code is messy" is not a decision input. "Schema changes require a four-service coordinated release and caused two incidents" is.

Offer staged mitigation and define when the debt becomes urgent. Some deliberate debt is rational; record its assumption and revisit condition.

## Architecture exercise

You inherit 30 FastAPI services owned by six teams. They share one PostgreSQL cluster, deploy together, and call each other synchronously. Incidents are hard to isolate.

A strong answer does not propose 60 services. Map data and change ownership, identify cyclic calls and critical paths, establish service-level telemetry and timeouts, create module or service contracts, and choose one boundary to decouple. Consider merging services that never deploy independently. Split databases only with an ownership and migration plan. Improve release independence and incident accountability incrementally.

[Previous: Advanced](advanced.md) | [Back to guide](README.md) | [Next: Scenarios](scenario-based.md)
