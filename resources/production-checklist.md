# Production Readiness Checklist

This checklist is a review prompt, not proof of safety. For each checked item, point to configuration, code, a test, a dashboard, or an operational procedure.

## API contract

- [ ] Routes use resource-oriented names or clearly documented RPC actions.
- [ ] Methods, success statuses, and error statuses match the operation semantics.
- [ ] Request and response schemas are separate where writable and readable fields differ.
- [ ] Maximum body, field, collection, and upload sizes are enforced.
- [ ] Pagination has a deterministic order and an index-supported query.
- [ ] Error responses have stable machine codes and do not leak internals.
- [ ] OpenAPI exposes intended public routes and hides internal callbacks.
- [ ] Versioning and deprecation behavior are documented.
- [ ] Idempotent create or command operations define key scope, conflict behavior, and retention.

## Identity and authorization

- [ ] Authentication distinguishes invalid, expired, revoked, and absent credentials without leaking sensitive detail.
- [ ] Passwords use a current adaptive password hash with calibrated cost.
- [ ] Access tokens validate algorithm, signature, issuer, audience, and time claims.
- [ ] Refresh tokens rotate or otherwise have a documented replay response.
- [ ] API keys are scoped, hashed at rest where applicable, auditable, and rotatable.
- [ ] Resource-level authorization runs before protected data or side effects.
- [ ] Tenant scope is mandatory in every persistence and cache path.
- [ ] Administrative actions require explicit permissions and audit events.
- [ ] Browser cookie flows address CSRF; CORS uses explicit trusted origins.

## Data and transactions

- [ ] Primary keys, foreign keys, uniqueness, checks, and nullability encode invariants.
- [ ] Query plans were reviewed for critical or high-volume paths.
- [ ] Composite indexes match equality filters, range conditions, and ordering.
- [ ] One request or job owns one session and closes it on success and failure.
- [ ] Application use cases own commit; repositories do not commit unexpectedly.
- [ ] Transactions do not remain open during slow external calls.
- [ ] Deadlocks and serialization failures have bounded retry where the operation is safe.
- [ ] N+1 behavior is prevented and tested for bounded query counts where important.
- [ ] Migrations follow backward-compatible expand and contract phases.
- [ ] Backups have tested restore procedures and defined recovery objectives.

## Async and capacity

- [ ] Async routes call non-blocking libraries, or blocking work is deliberately offloaded.
- [ ] CPU-heavy or long-running work is isolated from web processes.
- [ ] Every network call has connect and operation timeouts.
- [ ] Fan-out and concurrency are bounded per dependency.
- [ ] Total database connections across all processes fit the server budget.
- [ ] Server and proxy timeouts align with the public deadline.
- [ ] Graceful shutdown stops admission, drains bounded work, and closes resources.

## Caching and resilience

- [ ] Every cache documents source of truth, key dimensions, TTL, and invalidation.
- [ ] Cache keys include tenant, permission, schema, and filter dimensions where needed.
- [ ] Stampede behavior is bounded.
- [ ] Redis outage behavior is decided separately for cache, limiter, session, and idempotency use.
- [ ] Retries target selected transient failures, use jitter, and stay inside a deadline.
- [ ] Retry ownership across caller, proxy, SDK, and worker does not amplify traffic.
- [ ] Circuit breakers or load shedding protect dependencies where measured failure justifies them.
- [ ] External writes use provider idempotency or an application state machine.

## Jobs, messages, and webhooks

- [ ] Durable work has a job record and an explicit state machine.
- [ ] Queue handlers tolerate duplicate delivery.
- [ ] Acknowledgement occurs after the durable effect required by the contract.
- [ ] Retry count and delay are bounded; poison work reaches a dead-letter path.
- [ ] Job status, cancellation intent, progress, and failure code are observable.
- [ ] Database state and outbound messages use an outbox or documented reconciliation.
- [ ] Webhook signatures cover the raw body and are verified before processing.
- [ ] Webhook event IDs are deduplicated durably.
- [ ] Scheduled jobs have unique logical run IDs and do not assume a single trigger.

## Files and integrations

- [ ] Upload limits exist at the edge and application.
- [ ] File signature, content type, checksum, and ownership are verified.
- [ ] Files are scanned and risky parsers are isolated.
- [ ] Object keys are generated; user filenames are treated as display metadata.
- [ ] Provider credentials never reach clients or logs.
- [ ] Provider responses are validated and errors map to stable application errors.
- [ ] Integration contract tests cover timeout, invalid data, duplicate response, and outage behavior.

## Deployment

- [ ] The artifact is immutable and promoted between environments.
- [ ] Container runs as a non-root user with a read-only filesystem where practical.
- [ ] Production dependencies are minimal and pinned through a reproducible process.
- [ ] Secrets are injected at runtime and absent from images, Git, and build logs.
- [ ] Readiness, liveness, and startup checks have distinct meanings.
- [ ] Trusted proxy hops and forwarded headers are configured explicitly.
- [ ] TLS policy and certificate renewal are owned and monitored.
- [ ] Deployments overlap old and new versions safely.
- [ ] Rollback steps include schema and worker compatibility.
- [ ] CI runs documentation, test, static, dependency, and image checks.

## Observability

- [ ] Logs are structured and include request, trace, route, status, and duration fields.
- [ ] Sensitive fields and request bodies are redacted by default.
- [ ] Metrics cover traffic, errors, latency, and saturation.
- [ ] Database pool wait, query latency, queue age, and worker failures are visible.
- [ ] Metric labels are bounded; IDs and raw URLs do not become labels.
- [ ] Trace context crosses HTTP, database, queue, and provider boundaries.
- [ ] Alert thresholds correspond to user impact or resource exhaustion.
- [ ] Dashboards distinguish symptom metrics from suspected causes.
- [ ] Runbooks include investigation, mitigation, rollback, and escalation.

## Testing and recovery

- [ ] Unit tests cover domain policy and state transitions.
- [ ] Integration tests use the production database engine for important query behavior.
- [ ] API tests cover validation, authentication, authorization, and serialization.
- [ ] Failure tests cover timeouts, duplicates, partial effects, and dependency outages.
- [ ] Migration tests exercise upgrade from a realistic previous schema.
- [ ] Load tests use representative data and verify latency distributions and saturation.
- [ ] Restore, replay, and reconciliation procedures have been exercised.
- [ ] One person can follow the deployment and incident runbooks without tribal knowledge.

## AI workload additions

- [ ] Input and output token or media limits are enforced before work starts.
- [ ] Model and prompt versions are recorded with each result.
- [ ] Provider concurrency, rate, and cost budgets are enforced centrally enough for the deployment.
- [ ] Streams have terminal success and failure events; incomplete streams are detectable.
- [ ] Long generation uses a durable job or provider background contract.
- [ ] Model output, tool arguments, and generated markup are treated as untrusted.
- [ ] Retrieval applies tenant and resource policy inside every query.
- [ ] Document, chunk, embedding, and index lineage supports deletion and re-indexing.
- [ ] Quality and retrieval evaluations gate changes.
- [ ] Usage estimates reconcile against provider records.

[Back to documentation map](../README.md) | [Common mistakes](common-mistakes.md)
