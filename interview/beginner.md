# Beginner Interview Questions

Beginner questions establish whether the candidate understands the request path and can build a correct small API. Good answers are precise without pretending that every endpoint needs enterprise architecture.

## 1. What is FastAPI?

### Short answer

FastAPI is a Python ASGI framework for HTTP APIs. It uses Python type annotations with Pydantic for validation and serialization, provides dependency injection, and generates an OpenAPI contract from route definitions.

### Deeper explanation

FastAPI handles routing and framework integration. Starlette supplies much of the ASGI web layer, while Pydantic validates and serializes typed data. An ASGI server such as Uvicorn accepts connections and calls the application.

### Practical example

A typed `item_id: int` path parameter is parsed before the route runs. An invalid value produces a validation response instead of entering business logic.

### Senior-level discussion

Automatic OpenAPI is useful only if response models, errors, and authentication schemes are modeled honestly. Framework throughput does not compensate for slow queries or blocking provider calls.

### Common follow-ups

- What is ASGI?
- How is FastAPI related to Starlette and Pydantic?
- What does the ASGI server do?

## 2. What is an API?

### Short answer

An API is a contract through which one component requests behavior or data from another. An HTTP API defines request methods, targets, headers, bodies, responses, errors, authentication, and compatibility expectations.

### Practical example

`POST /orders` with a JSON body can create an order and return 201 with a `Location` header. The implementation may change while the public contract remains compatible.

### Common follow-ups

- What makes an API public or internal?
- What is backward compatibility?

## 3. What is REST?

### Short answer

REST is an architectural style centered on resources, representations, a uniform interface, stateless requests, caching constraints, and layered components. A JSON endpoint is not automatically RESTful.

### Practical example

Prefer `PATCH /orders/{id}` to an action-shaped `/updateOrder` when the operation is a partial update to the order resource. An explicit action endpoint can still be clearer for a domain transition such as `POST /orders/{id}/cancellation`.

### Senior-level discussion

Purity is less important than a consistent contract. Some workflows fit command-style APIs better. Explain idempotency and resource state either way.

## 4. What is ASGI?

### Short answer

ASGI is the interface between Python asynchronous web servers and applications. Its event-based model supports HTTP, WebSockets, lifespan, and concurrent I/O.

### Deeper explanation

Uvicorn sends ASGI events to the FastAPI application. Middleware and routers ultimately participate in this call chain. ASGI allows async work, but blocking code can still stall an event loop.

### Common follow-ups

- How does ASGI differ from WSGI?
- Does ASGI make CPU work faster?

## 5. What does Pydantic do in FastAPI?

### Short answer

Pydantic validates untrusted input into typed Python data and serializes output according to declared models. FastAPI uses those models for request handling and OpenAPI schemas.

### Practical example

An `EmailStr` field validates shape, while a database unique constraint still decides whether an email is already registered. Transport validation does not replace business rules or database constraints.

### Common follow-ups

- What changed in Pydantic v2?
- Why not use a SQLAlchemy model as the request body?

## 6. Explain path, query, and body parameters

Path parameters identify a resource within the route, query parameters modify selection or representation, and the request body carries a representation or command payload.

```http
PATCH /users/42?notify=true
Content-Type: application/json

{"display_name":"Ada"}
```

Here `42` is a path parameter, `notify` is a query parameter, and the JSON object is the body. Sensitive credentials should not go in the query string because URLs are widely logged and cached.

## 7. What is a response model?

A response model defines and validates the shape FastAPI serializes to the client. It documents the output and can prevent internal fields from leaking.

Use a dedicated response schema that omits password hashes, internal flags, and provider metadata. Do not rely on returning an ORM object and hoping serialization chooses safe fields.

## 8. What is dependency injection?

### Short answer

Dependency injection supplies a function with collaborators or request-derived values from outside. FastAPI resolves declared dependencies, caches them within a request by default, and supports cleanup dependencies with `yield`.

### Practical example

A session dependency opens one database session, yields it to a route, and closes it in `finally`. Authentication dependencies can parse a bearer token and return a principal.

### Senior-level discussion

Dependencies are well suited to transport concerns and resource lifecycle. Hidden writes inside a `get_*` dependency make ordering and tests difficult. Business workflows should remain explicit.

### Common follow-ups

- How do dependency overrides help tests?
- When does a dependency run more than once?

## 9. What happens when a request enters FastAPI?

The reverse proxy accepts or forwards the connection, the ASGI server builds request events, middleware wraps the application, routing selects an operation, dependencies resolve, request data validates, the route calls application code, and FastAPI serializes the result. Response middleware then runs on the way out.

An important nuance is that middleware order, dependency cleanup, background tasks, and streaming responses affect exactly when work completes.

## 10. What is the difference between GET and POST?

GET retrieves a representation and is defined as safe and idempotent. POST submits data for processing and is neither safe nor idempotent by definition. GET should not create a charge or delete state. POST can be made retry-safe with an application idempotency-key contract.

## 11. PUT or PATCH?

PUT replaces the state of a resource at a target URI and is idempotent. PATCH applies a partial modification; whether a patch document is idempotent depends on its semantics. In practice, define omitted fields, explicit null, validation, and concurrency behavior clearly.

## 12. Which status codes should a CRUD API use?

- 200 for a successful read or update with a body.
- 201 for creation, ideally with `Location`.
- 204 for success without a response body.
- 400 for a malformed operation not covered by typed validation.
- 401 when valid authentication is required and absent or invalid.
- 403 when the principal is known but the action is forbidden.
- 404 when the addressed resource is unavailable to the caller.
- 409 for a state conflict such as an invalid transition or duplicate key.
- 422 for semantically invalid request data in FastAPI's conventional validation response.
- 429 when a caller exceeds a rate policy.

The exact error contract should be consistent and documented.

## 13. Why use `APIRouter`?

`APIRouter` groups related routes with a prefix, tags, dependencies, and response configuration. It lets the composition root include feature routers without putting the whole API in `main.py`.

Do not create one router per route. Group by resource or business capability.

## 14. What is middleware?

Middleware wraps the ASGI application and can observe or transform requests and responses. Common uses are request IDs, trusted-host checks, CORS, timing, and cross-cutting logging.

Middleware is a poor place for resource-level authorization because it normally does not know the loaded domain resource. Ordering and response streaming also make naive body logging unsafe.

## 15. How should errors be handled?

Raise a specific application or domain exception where the problem is understood. Map known exceptions to a stable HTTP error centrally. Unexpected exceptions should produce a generic 500 response and retain detailed diagnostics in protected logs or error tracking.

Never return a stack trace or database error to a client.

## 16. How do you connect a database to FastAPI?

Construct the engine at application startup, create one session per request through a dependency, pass the session or repository into application code, and close it deterministically. Put schema changes in migrations, not in `create_all()` during production startup.

The database URL and pool settings come from validated configuration. Tests should override the session boundary with an isolated database.

## 17. What is CRUD?

CRUD names create, read, update, and delete data operations. It is a useful starting vocabulary, not an architecture. Real domains also have transitions such as approve, reserve, publish, and refund whose rules deserve explicit use cases.

## 18. What should be tested in a simple endpoint?

Test the success response, invalid input, missing resource, authentication requirement, forbidden access, and any conflict. Assert status and response contract, and verify the intended state change. A test that only checks 200 does not establish much.

## 19. What is OpenAPI?

OpenAPI is a machine-readable description of an HTTP API. FastAPI derives it from routes, schemas, parameters, responses, and security declarations, then uses it for Swagger UI and ReDoc.

Treat the generated document as a compatibility artifact. Diff it in CI for public APIs and model error responses explicitly.

## 20. What is a lifespan handler?

A lifespan handler runs startup and shutdown logic around the application. Use it to construct and close long-lived clients, verify essential configuration, and initialize instrumentation.

Avoid network calls at module import time. Startup should be bounded, observable, and compatible with multiple worker processes.

## Rapid follow-ups

**Why are type hints valuable?** They support tools and make FastAPI's validation contract explicit, but they do not enforce runtime behavior outside a validating boundary.

**Header or cookie for authentication?** Bearer APIs commonly use the `Authorization` header. Browser sessions often use secure, HTTP-only cookies and need CSRF analysis.

**Why not return a dictionary everywhere?** Explicit response models document and filter output, produce stable OpenAPI, and catch serialization mismatches.

**What is a migration?** A reviewed, versioned change to database schema or data that can be deployed in a compatible sequence.

**What is a reverse proxy?** A server in front of the application that may terminate TLS, route traffic, enforce limits, and set trusted forwarding headers.

## Practical exercise

Design and implement `POST /projects`, `GET /projects/{id}`, and `PATCH /projects/{id}`. Requirements:

- typed request and response models;
- 201 with `Location` for creation;
- explicit not-found and conflict errors;
- an injected repository;
- tests for invalid input and unavailable resources;
- no database or provider calls directly in the route.

Be prepared to explain the request lifecycle for one test.

[Back to interview guide](README.md) | [Next: Intermediate](intermediate.md)
