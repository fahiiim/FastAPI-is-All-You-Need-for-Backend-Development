# Configuration, Logging, and Error Handling

Production behavior should be controlled without editing source code, observable without attaching a debugger, and predictable when something fails. Configuration, logs, and errors are related: configuration selects behavior, logs explain what happened, and the error contract tells callers what they can do next.

## Configuration is an input to the program

Treat configuration as typed input, not as scattered calls to `os.getenv()`. A useful configuration system has these properties:

- required values fail at startup rather than during the first request;
- strings from the environment are parsed into real types;
- names and defaults are documented in one place;
- secrets are not embedded in the image, repository, or logs;
- tests can construct explicit settings without depending on a developer's machine;
- the effective non-secret configuration can be inspected during an incident.

The environment is a transport for configuration. It is not a validation system and it is not, by itself, a secret manager.

### Typed settings with Pydantic v2

`BaseSettings` lives in the separate `pydantic-settings` package. Model validators and constrained types make invalid deployments stop before accepting traffic.

```python
# app/core/config.py
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    service_name: str = "orders-api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: SecretStr
    redis_url: SecretStr | None = None
    public_base_url: AnyHttpUrl
    allowed_origins: list[AnyHttpUrl] = Field(default_factory=list)

    database_pool_size: int = Field(default=10, ge=1, le=100)
    upstream_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    signing_key: SecretStr = Field(min_length=32)

    @model_validator(mode="after")
    def production_invariants(self) -> "Settings":
        if self.environment == "production" and not self.redis_url:
            raise ValueError("REDIS_URL is required in production")
        if self.environment == "production" and self.log_level == "DEBUG":
            raise ValueError("DEBUG logging is not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

The type-ignore is limited to the construction boundary: required values arrive from settings sources, so a static checker cannot see them. Application code receives a fully validated `Settings` object.

Use the dependency where test substitution is useful:

```python
from typing import Annotated

from fastapi import Depends

SettingsDep = Annotated[Settings, Depends(get_settings)]
```

For infrastructure initialized once per process, call `get_settings()` from the application factory or lifespan function. Do not reconstruct settings for every request. Also avoid importing an eagerly constructed global settings object from dozens of modules, because import-time validation complicates tooling and tests.

### Precedence and environments

Define a deliberate precedence order. A common order, from strongest to weakest, is:

1. explicit constructor arguments in tests or scripts;
2. process environment injected by the runtime;
3. mounted secret files or a secret-provider settings source;
4. a local `.env` file used only for development;
5. safe code defaults.

Do not create separate branches such as `if production: ...` throughout the codebase. Represent the environment explicitly, but prefer capability settings such as `email_provider_enabled`, `payment_timeout_seconds`, and `json_logs`. This makes staging differences visible and testable.

Keep `.env.example` free of real credentials. A `.env` file is convenient locally, but must be ignored by Git. Never bake it into an image with `COPY . .`.

### Configuration categories

| Category | Examples | Handling |
|---|---|---|
| Static application setting | feature flags, timeout, page limit | Typed setting, deployed with the release |
| Secret | database password, signing key, API token | Secret manager or encrypted runtime secret |
| Dynamic operational control | emergency kill switch, rollout percentage | Feature flag/configuration service with audit trail |
| Tenant or user preference | locale, notification preference | Application database, not environment variables |
| Build metadata | Git SHA, build time, image digest | Inject at build/deploy time and expose in telemetry |

Environment variables are a poor fit for values that must change without a restart or differ by tenant.

## Secret management

A secret manager reduces accidental disclosure and supports access control, audit, and rotation. Examples include cloud secret stores, Vault, and orchestrator-mounted secrets. The application should receive only the secrets it needs through workload identity or a narrowly scoped role.

Key practices:

- encrypt secrets at rest and in transit;
- do not put secrets in command-line arguments, URLs, image layers, exception messages, or telemetry attributes;
- separate credentials by environment and service;
- prefer short-lived credentials and workload identity over long-lived access keys;
- establish rotation procedures before an incident;
- revoke and rotate any secret committed to Git, removing it from the latest commit is not enough;
- avoid returning a secret's raw value from `SecretStr`; call `get_secret_value()` only at the adapter boundary that needs it.

Secret rotation is a protocol, not merely replacing a value. For signing keys, accept the old and new verification keys during a transition while signing new tokens only with the new key. For database credentials, coordinate connection-pool recycling with the credential change.

## Application startup and configuration verification

Validate settings before opening the listening socket where the platform permits it. During lifespan startup, initialize shared clients and perform bounded checks that prove configuration syntax and credentials are usable. Do not make startup depend indefinitely on every optional downstream service.

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_timeout_seconds),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


def create_app() -> FastAPI:
    return FastAPI(title="Orders API", lifespan=lifespan)
```

Log a sanitized startup event with service name, environment, version, and enabled capabilities. Never serialize the entire settings model.

## Logging for machines and humans

A production log is an event record. A log line should answer: what happened, to which operation, in which service instance, and with what outcome? JSON is usually preferable in production because collectors can parse fields without regular expressions. Human-readable logs remain useful locally.

### Event schema

Use stable field names across services:

```json
{
  "timestamp": "2026-08-11T09:15:02.417Z",
  "level": "INFO",
  "event": "order_created",
  "service": "orders-api",
  "environment": "production",
  "request_id": "01J...",
  "trace_id": "4bf92f...",
  "order_id": "ord_123",
  "duration_ms": 37.4,
  "http_status_code": 201
}
```

Prefer `event="payment_authorization_failed"` plus fields over interpolating an unstructured paragraph. Field names form an operational API, so change them deliberately.

### Correlation context

Use an inbound request ID if it is syntactically valid and generated by a trusted gateway, otherwise generate one. Return it in the response. A `ContextVar` makes it available to logs produced during one asynchronous request without passing it through every function.

```python
import contextvars
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if 0 < len(supplied) <= 128 else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logging.getLogger("api.access").info(
                "request_complete",
                extra={
                    "method": request.method,
                    "route": request.scope.get("route").path
                    if request.scope.get("route")
                    else "unmatched",
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_var.reset(token)
```

This illustrates context propagation, not a complete JSON formatter. In a high-throughput service, benchmark middleware choices. Pure ASGI middleware avoids some limitations and overhead of `BaseHTTPMiddleware`.

Do not use a raw URL as the metric or log route label when it contains identifiers. Record the route template, such as `/orders/{order_id}`, to avoid unbounded cardinality and sensitive data leakage.

### Log levels

| Level | Meaning | Example |
|---|---|---|
| `DEBUG` | Diagnostic detail, normally disabled in production | cache key decision, parsed provider state |
| `INFO` | Expected lifecycle or business event | deployment started, order accepted |
| `WARNING` | Degraded but handled condition | cache unavailable, one retry scheduled |
| `ERROR` | Operation failed and needs investigation | request ended in 500, job exhausted retries |
| `CRITICAL` | Service or data safety is immediately at risk | cannot initialize primary database |

An expected 404 is not automatically an error log. Repeated authentication failures may be a security signal, but logging every invalid request at `ERROR` creates noise and can be used for log amplification.

### What not to log

Redact or omit:

- passwords, access and refresh tokens, cookies, authorization headers, API keys;
- payment card data and private cryptographic material;
- full request and response bodies by default;
- sensitive query parameters and personal data not needed operationally;
- stack traces for expected domain failures;
- health-check access logs at normal request volume, unless sampled or separated.

Centralized logs need retention limits, access control, encryption, and deletion policies. Logging personal data creates another data store with compliance obligations.

### Avoid duplicate and blocking logs

Configure handlers once at the process entry point. Library modules should call `logging.getLogger(__name__)` and should not add their own handlers. Align Uvicorn access and application logs so one request is not recorded twice.

Console writes can block under backpressure. For demanding workloads, emit to stdout and let the runtime collect it, or use a bounded queue handler. Decide what happens when that queue fills. Blocking every request preserves logs but can take the service down; dropping lower-level events preserves service availability but must be measurable.

## An error model is part of the API

Separate four kinds of failure:

1. **Client input errors**: malformed JSON, invalid fields, unsupported state transition.
2. **Authentication and authorization failures**: missing identity, invalid credentials, insufficient permission.
3. **Domain errors**: inventory unavailable, order already cancelled, idempotency conflict.
4. **Infrastructure and programmer errors**: database unavailable, timeout, invariant violation, bug.

Clients need stable status codes, machine-readable codes, and safe details. Operators need the original exception, stack trace, correlation fields, dependency name, and timing. Do not satisfy the second need by leaking it into the first.

### Status code decisions

| Condition | Typical status | Notes |
|---|---:|---|
| Request syntax or semantic validation fails | 400 or 422 | Be consistent; FastAPI uses 422 for validated request data by default |
| No valid authentication | 401 | Include the appropriate `WWW-Authenticate` challenge |
| Authenticated but not permitted | 403 | Do not reveal protected resource details |
| Resource is absent | 404 | Can also conceal a resource the caller may not discover |
| Current state conflicts with operation | 409 | Duplicate unique value, version conflict, idempotency mismatch |
| Preconditions fail | 412 | Useful with ETags and conditional updates |
| Rate limit exceeded | 429 | Tell the caller when retrying is appropriate |
| Dependency temporarily prevents completion | 502, 503, or 504 | Distinguish bad upstream response, unavailability, and gateway timeout |
| Unexpected application failure | 500 | Return a generic detail and log the exception |

Do not return 200 with `{ "success": false }`. HTTP-aware clients, caches, proxies, retries, and monitoring depend on the status code.

### Domain exceptions and a single HTTP translation boundary

The domain layer should not import `HTTPException`. It should express business meaning, then the API layer translates it.

```python
# app/domain/errors.py
class DomainError(Exception):
    code = "domain_error"


class OrderNotFound(DomainError):
    code = "order_not_found"

    def __init__(self, order_id: str) -> None:
        super().__init__(f"Order {order_id} was not found")
        self.order_id = order_id


class VersionConflict(DomainError):
    code = "version_conflict"
```

Use an error envelope based on the current HTTP Problem Details specification:

```python
from typing import Any

from pydantic import BaseModel, ConfigDict


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    code: str
    request_id: str
    errors: list[dict[str, Any]] | None = None
```

Register centralized handlers:

```python
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_var.get()
    body = Problem(
        type=f"https://api.example.com/problems/{code}",
        title=title,
        status=status,
        detail=detail,
        instance=str(request.url.path),
        code=code,
        request_id=request_id,
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        media_type="application/problem+json",
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OrderNotFound)
    async def order_not_found(request: Request, exc: OrderNotFound) -> JSONResponse:
        return problem_response(
            request,
            status=404,
            code=exc.code,
            title="Order not found",
            detail="The requested order does not exist.",
        )

    @app.exception_handler(RequestValidationError)
    async def request_invalid(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return problem_response(
            request,
            status=422,
            code="request_validation_failed",
            title="Request validation failed",
            detail="One or more request fields are invalid.",
            errors=fields,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return problem_response(
            request,
            status=exc.status_code,
            code="http_error",
            title="HTTP request failed",
            detail=str(exc.detail),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_request_error",
            extra={"method": request.method, "path": request.url.path},
        )
        return problem_response(
            request,
            status=500,
            code="internal_error",
            title="Internal server error",
            detail="The server could not complete the request.",
        )
```

Preserve required headers, such as `WWW-Authenticate`, when adapting framework exceptions, as the example does through `exc.headers`. In a mature codebase, define explicit mappings rather than using a generic handler for all framework errors.

### Error codes are compatibility contracts

Human-readable text may change. A code such as `inventory_insufficient` should not change meaning. Document whether the operation is retryable and which fields may accompany each code. Include error schemas in OpenAPI responses for important endpoints.

Avoid exposing database constraint names or upstream vendor messages. Translate them to domain meaning. Catching every `IntegrityError` as `409` is too broad: it can hide a programming or migration error. Inspect the known constraint at the repository boundary, roll back the session, then raise a precise domain exception.

## Failure behavior

### Fail fast, degrade deliberately

- Missing primary database credentials: fail startup.
- Optional analytics sink unavailable: start, mark capability degraded, and retry out of band.
- Redis used only as a cache unavailable: bypass it with bounded database protection.
- Redis used for mandatory rate limits or distributed coordination unavailable: fail closed or reject requests according to the threat model.

There is no universal fail-open rule. Record the policy per dependency.

### Cancellation and cleanup

Timeouts and client disconnects can cancel a coroutine. Use context managers and `finally` for locks, connections, files, and tracing spans. Do not broadly catch `BaseException`; it also captures cancellation and process-control exceptions. When catching `Exception`, clean up, add context, and re-raise unless the boundary owns the failure policy.

### Common mistakes

- Calling `os.getenv()` inside business logic.
- Giving dangerous production settings convenient development defaults.
- Logging a complete settings object or request headers.
- Returning exception text and stack traces to callers.
- Catching `Exception` in every layer and repeatedly logging the same failure.
- Turning all failures into 500, or all database errors into 409.
- using user-controlled values as unbounded log keys or metric labels.
- emitting multiple access logs for one request.
- assuming `.env` is a production secret store.
- changing the error envelope independently in each router.

## Production review checklist

- Configuration is typed, validated once, and testable through injection.
- Required production values have no insecure fallback.
- Secrets are absent from Git history, images, logs, traces, and error bodies.
- Rotation and revocation procedures have been exercised.
- Logs are structured and contain service, environment, request, and trace context.
- Sensitive fields are allowlisted or redacted at source.
- Domain errors are independent of HTTP and translated centrally.
- Unexpected errors are logged once with a stack trace and return a safe response.
- Error codes and response schemas are documented and contract-tested.
- Log ingestion failure and high-volume behavior are understood.

## Interview prompts

1. Why is a typed settings object better than calls to `os.getenv()` across modules?
2. When should a service fail startup because a dependency is unavailable?
3. How would you rotate a JWT signing key without invalidating every active token at once?
4. Why should domain exceptions not inherit from FastAPI's `HTTPException`?
5. What is the difference between a request ID and a distributed trace ID?
6. How would you prevent log volume from taking down an API during an error storm?
7. When is returning 409 more accurate than returning 422?

A senior answer connects these choices to compatibility, incident response, failure isolation, and security rather than only describing library syntax.

## Further reading

- [FastAPI: Settings and Environment Variables](https://fastapi.tiangolo.com/advanced/settings/)
- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [FastAPI: Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457)
- [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- [The Twelve-Factor App: Config](https://12factor.net/config)

## Related topics

- [Observability](./observability.md)
- [Integrations, Webhooks, and Resilience](./integrations-webhooks-and-resilience.md)
- [Containers and Deployment](./containers-and-deployment.md)
