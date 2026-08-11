# Middleware, Errors, Request Context, and I/O

Middleware wraps every request before routing and every response after routing. That makes it appropriate for protocol-wide concerns such as trusted hosts, CORS, request context, timing, and coarse observability. The same reach makes middleware risky: one unbounded body read, broad exception catch, or misplaced authentication rule affects every endpoint, including errors and streams.

## 1. The ASGI middleware model

An ASGI application is called with three values:

- `scope`: connection metadata such as protocol type, path, method, and headers.
- `receive`: an async callable that supplies request or connection events.
- `send`: an async callable that emits response or connection events.

Middleware is itself an ASGI application that calls another ASGI application. On the inbound path, outer middleware runs first. Response events travel outward in reverse order.

With repeated `app.add_middleware(...)` calls, each newly added middleware becomes the outermost user middleware. A declarative Starlette `middleware` list is evaluated top to bottom. Do not mix those mental models without checking the resulting stack.

```text
outer request-id middleware
  -> CORS middleware
    -> error middleware
      -> router and endpoint
    <- error response
  <- CORS headers
<- request-id header and final timing
```

The configured order decides whether an error response contains CORS and request-ID headers, and whether timing includes inner queueing and serialization. Write tests for normal responses, framework 404/405 responses, validation errors, expected exceptions, and unhandled failures.

## 2. Function middleware for simple HTTP concerns

FastAPI's decorator style is convenient when the middleware can work with `Request` and a complete `Response`:

```python
from time import perf_counter

from fastapi import FastAPI, Request, Response

app = FastAPI()


@app.middleware("http")
async def add_process_time(
    request: Request,
    call_next,
) -> Response:
    started = perf_counter()
    response = await call_next(request)
    duration = perf_counter() - started
    response.headers["Server-Timing"] = f"app;dur={duration * 1000:.1f}"
    return response
```

Type the `call_next` callable in a shared module if strict checking is required. Keep middleware state local to the call. An instance attribute such as `self.started_at` would be overwritten by concurrent requests.

`Server-Timing` reveals performance information to callers. Expose only metrics approved for the public boundary; internal detailed timings belong in telemetry.

## 3. Prefer pure ASGI middleware for protocol control

Starlette's `BaseHTTPMiddleware` offers a request-response dispatch API, but pure ASGI middleware gives direct, streaming-safe control and avoids documented limitations around context-variable propagation. Use pure ASGI for request IDs, body limits, streaming instrumentation, and reusable infrastructure.

### Request ID middleware

```python
from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id")
        request_id = (
            incoming
            if incoming is not None and SAFE_REQUEST_ID.fullmatch(incoming)
            else uuid4().hex
        )
        token = request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
```

Register it with `app.add_middleware(RequestIdMiddleware)` or wrap the ASGI application deliberately based on the required error coverage.

Request IDs solve reference and log-correlation problems. They do not provide distributed parent-child timing; W3C `traceparent` and a tracing system solve that. A service may carry both.

### Trust policy for incoming IDs

Choose one policy:

- A trusted edge replaces external IDs and the app accepts only the edge value.
- The app accepts a bounded safe caller value and records that it is external.
- The app always generates a new local ID and stores an accepted upstream ID separately.

Never accept arbitrary length or control characters. Do not make an ID an authorization decision. Return the effective value to callers when it is safe so support can correlate a failure.

## 4. Structured request logging

Log structured fields rather than interpolated paragraphs:

```python
logger.info(
    "http_request_completed",
    extra={
        "request_id": request_id_var.get(),
        "method": method,
        "route": route_template,
        "status_code": status_code,
        "duration_ms": round(duration_seconds * 1000, 2),
    },
)
```

Useful fields include method, route template, status, duration, response size, trace ID, deployment version, and a policy-approved tenant or actor identifier. Avoid:

- Raw authorization, cookie, or API-key headers.
- Full query strings containing tokens or personal data.
- Request and response bodies by default.
- Raw paths as metric labels.
- User IDs, request IDs, or exception messages as metric labels.
- Duplicate stack traces at every layer.

Log completion in a `finally` path so exceptions are visible. If headers have not started, an exception handler determines the final status. A low-level logging middleware may need to record an exception outcome separately from an HTTP status when the server's outer error middleware creates the eventual response.

## 5. CORS is a browser permission protocol

Cross-Origin Resource Sharing controls whether browser JavaScript may read responses from a different origin. An origin is scheme, host, and port. CORS does not authenticate a caller, stop curl or backend services, or replace CSRF defenses.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.example.com",
        "https://admin.example.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Request-ID",
    ],
    expose_headers=["ETag", "Location", "X-Request-ID"],
    max_age=600,
)
```

When credentialed browser requests are allowed, use explicit origins, methods, and headers according to the Starlette policy. Do not combine permissive origin reflection with credentials.

### Preflight

For a non-simple cross-origin operation, the browser sends an `OPTIONS` preflight containing the intended method and request headers. CORS middleware answers according to policy. The actual route may never run if the preflight is denied.

Include CORS checks in browser-facing integration tests:

- Allowed origin and method.
- Disallowed origin.
- Credentialed request.
- Required custom header.
- Exposed response headers.
- Error response from an allowed origin.

### CORS headers on errors

If browser clients need to read error responses, CORS must wrap the component that produces those errors. Starlette recommends wrapping the entire application when global error coverage is required:

```python
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

fastapi_app = FastAPI()

# Register routes on fastapi_app before exporting the wrapped ASGI app.
app = CORSMiddleware(
    app=fastapi_app,
    allow_origins=["https://app.example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

This changes which object tests and tooling should treat as the FastAPI instance, so establish one project convention. An alternative is a carefully ordered middleware stack with tests for unhandled errors.

## 6. Security-related middleware

Starlette provides middleware for trusted hosts and HTTPS redirects:

```python
from fastapi import FastAPI
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI()
app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["api.example.com", "*.internal.example.com"],
)
```

Because the trusted-host middleware is added last here, it is the outer user middleware and rejects an invalid `Host` before redirect construction.

In many deployments the edge enforces HTTPS. Duplicate redirects at both layers can be harmless or can cause loops when forwarded scheme information is not trusted correctly. Define one authoritative topology and test it behind the actual proxy configuration.

Other security headers such as HSTS, content type sniffing policy, and frame policy may be set at the edge or application. HSTS should be enabled only when the HTTPS and subdomain implications are understood.

## 7. Authentication middleware versus dependencies

Middleware can parse a credential once and attach a principal to request scope. It works well when nearly every protocol endpoint shares one authentication mechanism and the middleware preserves correct error, WebSocket, and public-route behavior.

FastAPI security dependencies are often clearer because they:

- Apply only where declared.
- Participate in dependency injection and OpenAPI security schemes.
- Can load route-specific scopes or resources.
- Are easy to override in API tests.

Even if middleware establishes identity, object-level authorization still belongs close to the resource and action. Do not assume an authenticated request is authorized.

Avoid database transactions in global authentication middleware. It may run for health checks, documentation, unmatched paths, and preflights unless explicitly excluded, and can add a database checkout to every request.

## 8. Exception categories

Separate expected protocol outcomes from unexpected faults.

### `HTTPException`

Raise `HTTPException` at the HTTP adapter when processing should stop with a known status:

```python
from fastapi import HTTPException, status


if order is None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="order not found",
    )
```

It is an exception, not a response value. Do not return it. Do not raise it from framework-independent domain code.

### Domain and application exceptions

Define typed failures with structured attributes:

```python
class OrderStateConflict(Exception):
    def __init__(self, order_id: str, current_state: str) -> None:
        super().__init__("order state does not permit this operation")
        self.order_id = order_id
        self.current_state = current_state
```

Map them once at the HTTP boundary:

```python
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(OrderStateConflict)
async def order_state_conflict_handler(
    request: Request,
    exc: OrderStateConflict,
) -> JSONResponse:
    request_id = request_id_var.get()
    return JSONResponse(
        status_code=409,
        media_type="application/problem+json",
        content={
            "type": "https://api.example.com/problems/order-state-conflict",
            "title": "Order state conflict",
            "status": 409,
            "detail": "The order cannot be changed from its current state.",
            "instance": str(request.url.path),
            "code": "order_state_conflict",
            "request_id": request_id,
        },
    )
```

Do not put `current_state` into the public response unless exposing it is authorized and part of the contract.

### Unexpected exceptions

Unexpected errors should produce a generic 500-class response, be logged once with a stack trace and request context, and be reported to error tracking. Never return the exception text or stack trace publicly.

Avoid this route pattern:

```python
async def misleading_handler(command: Command) -> Result:
    try:
        return await service.execute(command)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

It misclassifies programming and infrastructure failures as client errors, exposes internals, destroys useful alerting, and may turn cancellation into an HTTP response.

FastAPI and Starlette already contain server-error and exception middleware. Add a broad handler only when it preserves logging, debugging behavior in development, background-task caveats, and the expected middleware ordering.

## 9. Problem Details as a stable error envelope

[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html) defines `application/problem+json`. A project can extend it with stable fields:

```python
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: AnyUrl | str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str | None = None
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None
```

Treat `type`, `code`, and extension fields as a versioned public contract. Human-readable `detail` may change and should not be the only value clients inspect.

Do not report every outcome as `200` with a private success flag. Correct HTTP status lets clients, gateways, metrics, and retry systems behave consistently.

## 10. Validation error handling

FastAPI raises `RequestValidationError` for invalid request inputs. A custom handler can map it to the project's error envelope:

```python
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_errors = [
        {
            "location": [str(part) for part in error["loc"]],
            "message": error["msg"],
            "code": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "https://api.example.com/problems/validation",
            "title": "Request validation failed",
            "status": 422,
            "code": "request_validation_failed",
            "instance": str(request.url.path),
            "request_id": request_id_var.get(),
            "errors": safe_errors,
        },
    )
```

Omitting `input` and validator context reduces accidental reflection of secrets and non-JSON-compatible objects. Review whether field locations expose internal names. Bound the number and size of returned errors for adversarial large payloads.

Changing FastAPI's default validation response means OpenAPI must also describe the new schema for relevant operations. Contract tests should compare runtime errors with documentation.

## 11. Provider and database error translation

Translate errors based on semantics, not class name alone:

- A database unique violation for a documented business key may become `409 Conflict`.
- A serialization or deadlock failure might be retried within a carefully bounded transaction policy.
- Pool exhaustion is an availability failure, not a client validation error.
- A provider `404` may mean configuration failure internally, not that the API's own resource is absent.
- A provider timeout can be ambiguous for side effects.

Keep raw SQL errors, connection strings, provider bodies, and internal identifiers out of public responses. Preserve the original exception as `__cause__` for logs and tracing.

Retries should have one owner. If the HTTP client, repository, service, gateway, and load balancer each retry, a single caller can produce a retry storm.

## 12. Rate limits and overload responses

Rate limiting can be middleware when the key is available before routing, but production policies often require route, tenant, cost, or authenticated-principal context. An edge gateway is useful for coarse IP and global controls; the application can enforce business-specific quotas.

Return `429 Too Many Requests` for a policy quota and consider `Retry-After` when a meaningful retry time exists. Use `503 Service Unavailable` for capacity or dependency unavailability rather than pretending it is a caller quota.

Process-local counters do not enforce a cluster-wide rate. A shared store or gateway needs atomic behavior and a failure policy. Decide whether limiter-store failure allows traffic, rejects traffic, or degrades to a local emergency limit.

## 13. Reading request bodies safely

`await request.body()` reads the full body into memory. `await request.json()` also parses it. That is acceptable only after a suitable size limit for small control payloads.

For streaming input:

```python
from fastapi import HTTPException, Request


async def consume_bounded_body(
    request: Request,
    *,
    maximum_bytes: int,
) -> int:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum_bytes:
            raise HTTPException(status_code=413, detail="request body is too large")
        await write_chunk_to_quarantine(chunk)
    return received
```

Once `.stream()` is consumed, later calls to `.body()`, `.form()`, or `.json()` cannot independently read it. Design one owner for the stream.

Application-only limits still allow traffic to reach the worker. Enforce a coarse limit at the trusted proxy, then a media- and tenant-specific limit in the application. Clean up partial state on timeout, disconnect, parse failure, and limit rejection.

## 14. Multipart uploads

`UploadFile` exposes a spooled file-like object and async methods:

```python
from typing import Annotated

from fastapi import File, HTTPException, UploadFile

CHUNK_SIZE = 1024 * 1024
MAXIMUM_BYTES = 25 * 1024 * 1024


async def store_upload(file: UploadFile) -> int:
    total = 0
    while chunk := await file.read(CHUNK_SIZE):
        total += len(chunk)
        if total > MAXIMUM_BYTES:
            raise HTTPException(status_code=413, detail="file is too large")
        await object_store_writer.write(chunk)
    return total


@app.post("/documents", status_code=201)
async def create_document(
    file: Annotated[UploadFile, File()],
) -> dict[str, int]:
    total = await store_upload(file)
    return {"size": total}
```

This is an ownership sketch, not a full secure uploader. A production flow should:

- Authorize before accepting expensive content.
- Generate a storage key and never trust the filename as a path.
- Inspect signatures and media policy rather than trusting `content_type`.
- Write to a temporary or quarantine object.
- Verify a checksum if the protocol supplies one.
- Scan before making content available.
- Remove incomplete content on failure.
- Store metadata transactionally or with reconciliation.
- Apply rate, count, byte, time, and tenant storage quotas.

For large files, a common design issues a short-lived presigned object-store upload, then accepts a completion command that verifies ownership, object size, checksum, and state. This keeps bulk bytes away from web workers while retaining application authorization.

## 15. File downloads

Starlette's `FileResponse` streams a file and supports appropriate file response metadata, including range handling in supported cases:

```python
from pathlib import Path

from fastapi.responses import FileResponse

EXPORT_ROOT = Path("/srv/exports").resolve()


def export_response(stored_name: str, download_name: str) -> FileResponse:
    candidate = (EXPORT_ROOT / stored_name).resolve()
    if EXPORT_ROOT not in candidate.parents:
        raise ValueError("invalid stored export path")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return FileResponse(
        path=candidate,
        media_type="text/csv",
        filename=download_name,
    )
```

Never join an untrusted filename directly to a storage root. Prefer looking up an opaque object ID in authorized metadata, then using a server-controlled storage key. Check file existence and authorization before response start.

At high volume, return a short-lived signed download URL or let an internal redirect mechanism hand delivery to a proxy or object store. The application should still authorize the user and audit access.

## 16. Streaming responses

`StreamingResponse` sends chunks from an iterator or async iterator:

```python
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse


async def csv_rows(report_id: str) -> AsyncIterator[bytes]:
    yield b"id,status\n"
    async for row in report_repository.iter_rows(report_id, batch_size=500):
        yield encode_csv_row(row)


@app.get("/reports/{report_id}.csv")
async def download_report(report_id: str) -> StreamingResponse:
    await authorize_report(report_id)
    return StreamingResponse(
        csv_rows(report_id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="report.csv"'},
    )
```

The iterator owns any resource needed while streaming. Do not depend on a request-scoped database session whose dependency teardown timing is outside the iterator's contract.

Streaming tradeoffs:

- Status and headers are sent before later chunks fail.
- Slow clients keep the producer and related resources alive.
- Compression may buffer or delay small chunks.
- Proxies can buffer unless configured for streaming.
- A database cursor or transaction can remain open for the download.
- Backpressure needs bounded queues between producer and sender.
- Disconnect and cancellation require cleanup.

For expensive reports, generate a durable object in a background worker and serve it separately. That decouples query time from client download speed.

## 17. Server-Sent Events and WebSockets

Server-Sent Events use an HTTP response stream for one-way server-to-browser events. They provide a text event format and browser reconnection behavior. WebSockets provide full duplex messages after an upgrade.

Whichever transport is used:

- Authenticate the connection and authorize each subscription.
- Validate browser origin where required.
- Limit message size, rate, and per-connection buffers.
- Define heartbeat and idle timeout behavior.
- Expect reconnects across deployments.
- Use shared pub/sub for cross-worker fan-out.
- Persist events separately if replay or delivery guarantees matter.

A live connection registry in one process cannot see clients on other workers.

## 18. Compression

Compression reduces network bytes for sufficiently large compressible responses at the cost of CPU and sometimes buffering. Do not compress already compressed media merely by habit. Measure latency and CPU.

Be careful when a compressed response contains secrets and attacker-controlled reflected data in the same context. Compression side channels have protocol-specific mitigations. Sensitive endpoints may need compression disabled or response designs that do not mix those values.

Streaming, `Content-Length`, range requests, and proxy compression can interact. Assign compression ownership to one layer and test actual response headers.

## 19. Middleware state and concurrency

Middleware objects are shared across requests within a process. Keep per-request state inside `__call__` locals, the ASGI scope, or a correctly managed `ContextVar`.

Wrong:

```python
class TimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        self.started_at = perf_counter()  # Concurrent requests overwrite it.
        await self.app(scope, receive, send)
```

Right:

```python
class TimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        started_at = perf_counter()
        await self.app(scope, receive, send)
        observe_duration(perf_counter() - started_at)
```

Configuration stored on `self` should be immutable after startup. Any shared cache, limiter, or client needs a deliberate concurrency and multi-worker design.

## 20. Testing the whole stack

Tests should cover behavior middleware can alter:

- Request ID accepted, replaced, and returned.
- Context reset between requests.
- CORS preflight and actual responses.
- CORS headers on 4xx and unhandled 5xx responses.
- Trusted host and HTTPS behavior behind the test proxy model.
- Body rejection before excessive buffering.
- Validation error schema without reflected secrets.
- Domain error mapping.
- Streaming first byte, cancellation, and cleanup.
- Upload limits and partial-object deletion.
- Header behavior for 204, files, ranges, and compression.

When `raise_server_exceptions` is enabled in a test client, an unhandled exception may be re-raised into the test instead of letting the test inspect the generated 500 response. Configure the test intentionally for the layer being verified.

## 21. Common mistakes

| Mistake | Consequence | Better choice |
| --- | --- | --- |
| Reading every body in logging middleware | Memory spikes and secret leakage | Log bounded metadata and approved fields |
| Mutable per-request middleware attributes | Cross-request data races | Use local variables or scoped context |
| `allow_origins=["*"]` with credentials | Unsafe or rejected browser policy | Enumerate trusted origins and methods |
| Treating CORS as authentication | Non-browser callers bypass it | Enforce credentials and authorization separately |
| Catching every exception as 400 | Outages look like client mistakes | Map expected typed errors and preserve 500s |
| Reflecting validation input | Tokens or personal data leak | Return sanitized locations and codes |
| Request ID used as trace ID | No parent-child distributed timing | Propagate W3C trace context and keep request reference separately |
| Trusting upload metadata | Malicious content or path traversal | Inspect content, generate keys, quarantine, and scan |
| Holding a transaction during download | Pool and lock exhaustion | Pre-generate or stream from independent storage |
| Process-local rate limit in a cluster | Inconsistent global policy | Use a gateway or atomic shared limiter |
| Critical work in `BackgroundTasks` | Lost work on crash or deploy | Use a durable outbox and worker |

## Interview prompts

1. **Why does middleware order matter?** Request handling nests inward and response handling unwinds outward. The order determines which layers see errors and which headers or context appear on every response.
2. **What is CORS protecting?** It is a browser-enforced policy controlling whether scripts from one origin can read or send certain cross-origin requests. It is not server authentication or a general network firewall.
3. **How should request IDs be handled?** Accept only bounded safe values according to a trust policy or generate a new one, bind it for logs, return the effective ID, and keep it separate from distributed trace context.
4. **Why prefer dependencies for authorization?** They can use validated route and resource context, apply only to selected operations, integrate with OpenAPI security, and are easier to test. Middleware remains useful for coarse identity establishment.
5. **How do you standardize errors without hiding bugs?** Map typed expected failures to a stable Problem Details schema, sanitize validation errors, and let unexpected failures remain 500-class with one internal stack trace.
6. **Why is upload `Content-Type` insufficient?** It is supplied by the client and may be wrong or malicious. Enforce size, inspect signatures, quarantine, scan, and authorize access.
7. **What changes after a streaming response starts?** Status and headers are committed. A later error can only terminate the stream or use an application-level stream event if the protocol defines it.
8. **Where would you enforce rate limits?** Coarse network or IP policy at the edge, and tenant, identity, route, or cost policy in an application-aware layer backed by atomic shared state when cluster-wide consistency matters.

## Sources

- [ASGI HTTP and WebSocket specification](https://asgi.readthedocs.io/en/latest/specs/www.html)
- [FastAPI middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
- [FastAPI error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [FastAPI request files](https://fastapi.tiangolo.com/tutorial/request-files/)
- [FastAPI custom responses](https://fastapi.tiangolo.com/advanced/custom-response/)
- [Starlette middleware](https://www.starlette.io/middleware/)
- [Starlette requests](https://www.starlette.io/requests/)
- [Starlette responses](https://www.starlette.io/responses/)
- [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [Fetch Standard: CORS protocol](https://fetch.spec.whatwg.org/#http-cors-protocol)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
