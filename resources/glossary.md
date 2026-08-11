# Backend Engineering Glossary

Definitions are intentionally compact. Follow the linked chapters for implementation and tradeoffs.

**ACID:** Atomicity, consistency, isolation, and durability, a set of transaction properties. Consistency here means preserving declared database rules, not the distributed-systems meaning.

**API key:** A credential that identifies a caller or integration. Store server-side keys hashed when they need only comparison, scope them, rotate them, and never put them in URLs.

**ASGI:** Asynchronous Server Gateway Interface, the Python interface between async-capable web servers and applications. FastAPI is an ASGI application.

**Authentication:** Establishing which principal is making a request.

**Authorization:** Deciding whether an authenticated or anonymous principal may perform an action on a resource.

**Backpressure:** A mechanism that slows or rejects producers when consumers cannot keep up, preventing unbounded buffers.

**Cache:** A derived copy kept to reduce latency or origin work. Its design includes key, freshness, invalidation, capacity, and failure behavior.

**CAP theorem:** In the presence of a network partition, a distributed system cannot guarantee both linearizable consistency and availability for every request. It is not a general instruction to pick two properties during normal operation.

**Circuit breaker:** A state machine that stops sending requests to an unhealthy dependency for a period, then probes recovery. It complements, rather than replaces, deadlines and admission control.

**Connection pool:** A bounded set of reusable connections. Pool sizing is a capacity decision across all processes, not only one application instance.

**Concurrency:** Multiple tasks make progress during overlapping time. Concurrency does not require simultaneous CPU execution.

**Correlation ID:** An identifier propagated across related service and job boundaries so events can be connected. It may differ from the request ID generated at each hop.

**CORS:** Cross-Origin Resource Sharing, an HTTP-header protocol by which browsers decide whether frontend code from one origin may read a response from another. It is not API authentication.

**CSRF:** Cross-Site Request Forgery, where a browser sends an authenticated request chosen by another site. Cookie-authenticated state changes need appropriate defenses such as SameSite policy and CSRF tokens.

**Cursor pagination:** Pagination that seeks after an ordered tuple from the previous result rather than skipping a numeric offset.

**Dependency injection:** Supplying a function or object with its collaborators from outside. FastAPI also uses dependencies to resolve request-scoped inputs and manage resources.

**Distributed lock:** Coordination that grants a time-limited claim across processes. Lease expiry and stale holders make it unsuitable as a casual correctness primitive.

**Distributed system:** Components communicate across failure-prone networks and cannot assume a shared clock, atomic memory, or simultaneous availability.

**Event loop:** A scheduler that runs ready coroutines and resumes them when awaited operations complete.

**Eventual consistency:** Replicas or derived views may temporarily disagree but converge when updates and retries complete.

**Idempotency:** Applying the same operation more than once has the same intended effect as applying it once. An idempotency key usually needs a scope, request fingerprint, state, result, and retention window.

**Isolation level:** The anomalies a database transaction may observe when transactions overlap. PostgreSQL implements specific behaviors for Read Committed, Repeatable Read, and Serializable.

**JWT:** JSON Web Token, a compact claims format commonly signed as a JWS. A signed JWT is not encrypted, not automatically revocable, and not an authorization policy by itself.

**Liveness check:** A signal that the process should be restarted because it cannot make progress.

**Load balancer:** A component that distributes connections or requests across healthy targets, sometimes terminating TLS and applying routing policy.

**Message queue:** A system that stores messages for consumers and provides delivery and acknowledgement semantics. Consumers must match those semantics with idempotent effects.

**Middleware:** Code that wraps an ASGI application and can inspect or transform requests and responses. Ordering and streaming behavior matter.

**Migration:** A versioned change to database schema or data. Safe production migrations account for old and new application versions running together.

**Multi-tenancy:** Serving multiple customers or organizations while enforcing data, configuration, quota, and sometimes compute isolation.

**N+1 query:** One query loads a collection, then one additional query is executed for each result, causing latency and database load to grow with result count.

**OAuth 2.0:** An authorization framework through which a client obtains scoped access to a resource server. It is not itself a user identity protocol; OpenID Connect adds an identity layer.

**Observability:** The ability to investigate a system's internal behavior from outputs such as logs, metrics, and traces.

**ORM:** Object-relational mapper, a layer that maps relational rows and operations to program objects. It does not remove the need to understand SQL and transactions.

**Parallelism:** Work executes simultaneously on multiple CPU cores or compute devices.

**Principal:** The authenticated entity on whose behalf a request acts, such as a user, service, or API-key owner.

**Readiness check:** A signal that a process is prepared to receive traffic for its advertised responsibilities.

**Request ID:** An identifier for one request at one service hop, used in responses, logs, and traces.

**REST:** An architectural style based on resources, representations, a uniform interface, stateless requests, cache constraints, and layered components. JSON over HTTP is not automatically REST.

**Reverse proxy:** A server in front of applications that can terminate TLS, route traffic, enforce size limits, buffer responses, and set trusted forwarding headers.

**RPC:** Remote Procedure Call, an interaction modeled around invoking an operation rather than manipulating a resource representation.

**RBAC:** Role-Based Access Control, where roles group permissions. Resource and tenant conditions still require policy beyond a role name.

**Saga:** A distributed workflow expressed as local transactions plus messages and compensating actions. Compensation is domain-specific and may not restore the exact prior world.

**Serialization:** Converting application data into a transport or storage representation. Deserialization reverses the process and is a trust boundary.

**SQL injection:** Untrusted input changes the structure of a SQL command. Parameterized queries prevent data from being interpreted as SQL syntax.

**Stateless service:** A service where any suitable replica can handle the next request because durable session state is external or carried by the request. A process still has caches and connections, so stateless does not mean no state exists.

**Structured logging:** Logs emitted as named fields with consistent types, enabling queries without parsing prose.

**Trace:** A causally connected set of spans that represents work across process and service boundaries.

**Transaction:** A unit of database work that commits atomically or rolls back. External API calls do not join a normal database transaction.

**Unit of work:** A boundary that tracks changes and commits them as one transaction. SQLAlchemy `Session` implements important unit-of-work behavior.

**WebSocket:** A persistent full-duplex protocol established through an HTTP handshake. Applications own authentication, message schemas, backpressure, and reconnect state.

**Webhook:** An HTTP callback sent when an event occurs. Receivers verify signatures, acknowledge quickly, deduplicate, and process asynchronously when needed.

**Worker:** A process that consumes jobs or events outside the web request path.

**WSGI:** Web Server Gateway Interface, the synchronous Python interface that predates ASGI. It does not natively model WebSockets or async application calls.

**XSS:** Cross-Site Scripting, where untrusted content executes as script in a browser. Output encoding, safe rendering, and content security policy are relevant defenses.

[Back to documentation map](../README.md)
