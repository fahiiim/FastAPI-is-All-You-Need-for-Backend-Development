# Dependency Injection and Resource Ownership

Dependency injection means a callable declares what it needs and another component supplies those values. FastAPI implements this at the request boundary: it inspects dependency callables, builds a graph, resolves sub-dependencies, validates their inputs, caches results for the request by default, and passes results to the endpoint.

The feature is useful for request context, authentication, authorization, database sessions, service construction, and reusable policy. It is not a reason to hide all application control flow behind `Depends`.

## 1. The smallest useful dependency

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

app = FastAPI()


async def require_api_version(
    x_api_version: Annotated[str, Header(alias="X-API-Version")],
) -> str:
    if x_api_version != "2026-01-01":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported API version",
        )
    return x_api_version


ApiVersion = Annotated[str, Depends(require_api_version)]


@app.get("/reports")
async def list_reports(api_version: ApiVersion) -> list[dict[str, str]]:
    return []
```

FastAPI, not application code, calls `require_api_version` for the route. The reusable `Annotated` alias keeps the endpoint signature readable while preserving the result type for static tools.

Do not call a dependency-decorated endpoint as though FastAPI will inject arguments:

```python
# Wrong: direct Python calls do not resolve Depends.
result = await list_reports()
```

Extract reusable behavior into an ordinary function or service, then let both the route and other Python code call that behavior explicitly.

## 2. Dependencies form a graph

A dependency can depend on other dependencies:

```python
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    tenant_id: str


async def bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    scheme, separator, credential = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credential


async def current_principal(
    token: Annotated[str, Depends(bearer_token)],
) -> Principal:
    claims = await verify_token(token)
    return Principal(user_id=claims.subject, tenant_id=claims.tenant_id)


async def active_principal(
    principal: Annotated[Principal, Depends(current_principal)],
) -> Principal:
    if not await user_is_active(principal.user_id):
        raise HTTPException(status_code=403, detail="inactive account")
    return principal


ActivePrincipal = Annotated[Principal, Depends(active_principal)]
```

FastAPI orders the graph so each prerequisite is available before its consumer. If two branches require `current_principal`, its result is normally reused within that request.

Graph design should reflect real policy steps. Ten layers named `get_current_active_verified_paid_user` are hard to reason about. Prefer a small identity dependency followed by explicit, action-oriented authorization.

## 3. Per-request caching

Dependency results are cached per request by default. Reusing a session dependency should therefore provide the same session object to repositories and services participating in one request:

```python
async def endpoint(
    service: Annotated[OrderService, Depends(get_order_service)],
    audit: Annotated[AuditWriter, Depends(get_audit_writer)],
) -> None:
    # If both builders depend on get_session, they normally share its result.
    await audit.record_service_ready(service)
```

Caching is not process-wide application caching. It ends with the request.

Set `use_cache=False` only when repeated resolution is intentional:

```python
FreshNonce = Annotated[str, Depends(generate_nonce, use_cache=False)]
```

Disabling caching on resource dependencies can create multiple sessions or clients and break atomicity. Treat it as an exceptional behavior and test the graph.

## 4. Function, callable-object, and class dependencies

Any callable with an inspectable signature can be a dependency.

### Function dependency

Use a function for a focused operation:

```python
from typing import Annotated

from fastapi import Query


def pagination(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: Annotated[str | None, Query(max_length=500)] = None,
) -> PageRequest:
    return PageRequest(limit=limit, after=after)
```

### Callable object

A configured callable is useful for parameterized policy:

```python
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status


@dataclass(frozen=True, slots=True)
class RequirePermission:
    permission: str

    async def __call__(
        self,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        allowed = await principal_has_permission(principal, self.permission)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="permission denied",
            )
        return principal


CanRefund = Annotated[
    Principal,
    Depends(RequirePermission("orders:refund")),
]
```

The `RequirePermission` instance lives at module scope, so it must be immutable or concurrency-safe. The `__call__` execution and returned principal are request-scoped.

### Class constructor

Passing a class to `Depends` calls its constructor for resolution. This can group request inputs:

```python
class CommonFilters:
    def __init__(
        self,
        q: str | None = None,
        limit: int = 50,
    ) -> None:
        self.q = q
        self.limit = min(max(limit, 1), 100)


Filters = Annotated[CommonFilters, Depends(CommonFilters)]
```

For public input, explicit `Query` constraints usually produce clearer validation than silently clamping an invalid value.

## 5. Resource dependencies with `yield`

A generator dependency splits acquisition from cleanup:

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
```

Code before `yield` acquires the resource. Code in `finally` or the context manager releases it whether the endpoint succeeds or raises.

### Choose the yield scope

Current FastAPI versions let a yielded dependency select its exit point:

```python
RequestSession = Annotated[
    AsyncSession,
    Depends(get_session, scope="request"),
]

FunctionSession = Annotated[
    AsyncSession,
    Depends(get_session, scope="function"),
]
```

- `scope="request"` is the default for a dependency with `yield`. Its exit code runs after the response is sent, so a streaming response can technically use the yielded resource.
- `scope="function"` runs exit code after the endpoint function returns but before the response is sent. It releases scarce resources earlier when serialization or streaming no longer needs them.

Holding a database session through a slow stream is usually expensive even though request scope permits it. Prefer loading what the response needs, mapping to an output model, and closing the session before a long transfer. If the stream deliberately queries through the session, use request scope, bound its duration, and account for the held connection.

Scope also constrains sub-dependencies so teardown order remains valid. A request-scoped dependency can require only request-scoped yielded sub-dependencies. A function-scoped dependency may use function- or request-scoped sub-dependencies. FastAPI validates incompatible graphs at startup.

Use the same pattern for a request-scoped unit of work, temporary directory, lock, or provider context. Application-wide pools and clients belong in lifespan; a dependency can retrieve them and create a short-lived scope.

### Do not swallow exceptions in teardown

```python
async def managed_resource() -> AsyncIterator[Resource]:
    resource = await acquire()
    try:
        yield resource
    except BaseException:
        await resource.rollback_if_needed()
        raise
    finally:
        await resource.close()
```

Catch `BaseException` only to guarantee cleanup or rollback across cancellation, and always re-raise unless the dependency deliberately translates a known exception. Swallowing failures can leave FastAPI without a valid response and hides the original cause.

Do not rely on a yielded request resource inside an in-process background task. Give that work an independent resource lifetime. For a response stream, select the dependency scope deliberately or acquire the streaming resource inside the iterator.

## 6. Lifetimes must be explicit

| Lifetime | Examples | Owner |
| --- | --- | --- |
| Application process | Database engine, HTTP connection pool, compiled model, metrics exporter | Lifespan |
| Request | Database session, unit of work, principal, request context | Dependency graph |
| Business operation | Transaction, idempotency claim, distributed lock | Application service or explicit unit of work |
| Message/job | Worker session, trace context, retry attempt | Worker entry point |
| Function | Pure calculations, mapped values | Local code |

A database engine is safe to share as a pool; a mutable session is not. An `AsyncClient` is designed for connection reuse; per-request authorization headers should be passed on each request or through a request-scoped adapter, not mutated globally.

When an object has mutable state, ask whether concurrent requests can touch the same instance. Module-level dependency objects and lifespan state are shared within a worker.

## 7. Build services at the edge

FastAPI dependencies make a useful composition root:

```python
from typing import Annotated

from fastapi import Depends, Request


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session


class PaymentGateway:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client


class OrderService:
    def __init__(
        self,
        orders: OrderRepository,
        payments: PaymentGateway,
    ) -> None:
        self._orders = orders
        self._payments = payments


def get_order_repository(session: SessionDep) -> OrderRepository:
    return OrderRepository(session)


def get_payment_gateway(request: Request) -> PaymentGateway:
    return PaymentGateway(request.app.state.payment_client)


def get_order_service(
    orders: Annotated[OrderRepository, Depends(get_order_repository)],
    payments: Annotated[PaymentGateway, Depends(get_payment_gateway)],
) -> OrderService:
    return OrderService(orders, payments)


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
```

The service constructor is ordinary Python. It does not contain `Depends`, import the application, or look up global state. That keeps it usable in workers, scripts, and unit tests.

Do not create an interface and factory for every three-line class automatically. Introduce boundaries around domain behavior, external systems, persistence, nondeterminism, and test seams that genuinely matter.

## 8. Transaction ownership

There are two common designs.

### Service-owned transaction

```python
class TransferService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def transfer(self, command: TransferCommand) -> Transfer:
        async with self._session.begin():
            source = await load_account_for_update(self._session, command.source_id)
            target = await load_account_for_update(self._session, command.target_id)
            transfer = apply_transfer(source, target, command.amount)
            self._session.add(transfer)
        return transfer
```

The transaction is visible where the atomic business operation is coordinated. This is a strong default.

### Unit-of-work dependency

A dependency can yield a unit of work and commit or roll back afterward. It reduces repetition but can make commit timing implicit and may incorrectly treat the whole HTTP request as one transaction. If adopted, endpoints must clearly signal success, services must not independently commit, and streaming or background work must not outlive the unit of work.

Never commit unconditionally in dependency teardown. If response mapping fails after a write but before the dependency sees the intended outcome, implicit policies can produce surprising results. Document and test the exact convention.

## 9. Authentication and authorization

Dependencies are well suited to authentication because credentials are request inputs and the result is reusable request context. Use FastAPI security helpers when OpenAPI should describe schemes and scopes.

Authorization needs more than a role check:

```python
async def editable_order(
    order_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    service: OrderServiceDep,
) -> Order:
    order = await service.get(order_id, tenant_id=principal.tenant_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if not service.can_edit(principal, order):
        raise HTTPException(status_code=403, detail="permission denied")
    return order


EditableOrder = Annotated[Order, Depends(editable_order)]
```

The query is tenant-scoped before returning data. The policy evaluates subject, action, resource, and context. Global role labels alone do not prevent cross-tenant access.

Avoid loading the same resource again in the endpoint. Dependency caching applies to dependency call results, not to arbitrary duplicated repository calls, so return the authorized resource when that improves clarity.

## 10. Dependency placement levels

Dependencies can be attached at several levels:

- Parameter level, when the endpoint uses the returned value.
- Decorator level, when only the side effect or guard matters.
- Router level, for a coherent group of operations.
- Application level, for a true global policy.

```python
router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_staff_principal)],
)
```

Use global dependencies sparingly. Health endpoints, docs, callbacks, or public routes may need different policy. A giant application-wide dependency can also make tests and startup probes unexpectedly require production infrastructure.

## 11. Error translation

A dependency may raise `HTTPException` for an expected HTTP boundary failure such as missing authentication. Infrastructure adapters should raise typed application or infrastructure exceptions rather than return `None` for every failure.

Keep translation close to the boundary that understands both sides:

- Token parse failure to `401` in authentication dependency.
- Permission denial to `403` or deliberate `404` in authorization dependency.
- Domain conflict to `409` in an exception handler or route adapter.
- Unexpected database or provider failure to a controlled 500-class response at the application exception boundary.

Do not catch `Exception` in a dependency and turn every bug into `401`. That masks outages and makes debugging misleading.

## 12. Testing with dependency overrides

FastAPI exposes `app.dependency_overrides` for test composition:

```python
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient


async def override_session() -> AsyncIterator[AsyncSession]:
    async with test_session_factory() as session:
        yield session


app.dependency_overrides[get_session] = override_session
try:
    with TestClient(app) as client:
        response = client.get("/orders")
        assert response.status_code == 200
finally:
    app.dependency_overrides.clear()
```

Override the exact callable used in `Depends`, not a new wrapper with the same behavior. Clear overrides so one test cannot contaminate another. A fixture that creates a fresh app per test group is often easier to reason about.

Use overrides for API integration tests. For service unit tests, instantiate the service with fakes directly. Testing every business rule through FastAPI makes the suite slow and couples it to transport details.

### Lifespan still matters

A test client context runs startup and shutdown behavior. If a dependency reads `app.state`, the test must either execute lifespan or construct that state deliberately. A test that imports the app and calls a handler directly is not an application lifecycle test.

## 13. Dependency overrides are not production monkey-patching

Overrides are mutable application state. Configure them before requests and isolate them to tests. Changing overrides while a process handles concurrent production requests can route one caller through another caller's dependency graph.

For runtime variants, construct a different app, use configuration-backed factories, or inject a stable router-level strategy. Do not toggle global overrides per request.

## 14. Anti-patterns

### `Depends` inside domain code

```python
# Wrong: FastAPI metadata leaks into a reusable service.
class UserService:
    def __init__(self, session: AsyncSession = Depends(get_session)) -> None:
        self._session = session
```

Instantiate services through a FastAPI factory and keep constructors ordinary.

### Service locator

```python
# Hidden dependencies, runtime keys, and global state.
mailer = container.resolve("mailer")
```

Constructor parameters make dependencies visible to readers, tests, and static tools.

### Business mutation during dependency resolution

A dependency named `charge_card` can run before another parameter fails validation. Dependencies should prepare the call or enforce policy; the endpoint's application service should coordinate business side effects.

### Too much graph

If understanding a route requires opening twelve one-line provider functions, the graph has become ceremony. Combine construction where it represents one cohesive boundary and use clear type aliases.

### Singleton mutable sessions

A global session shares transactions and identity state across requests. Store the engine or session factory globally, then create sessions per request or operation.

## 15. Design checklist

- Is each dependency's lifetime clear?
- Is process-shared mutable state concurrency-safe?
- Are generator resources always released on errors and cancellation?
- Does the endpoint receive a useful typed value, not an untyped bag?
- Are business side effects coordinated after input and policy checks?
- Is the transaction boundary visible?
- Can the service run without FastAPI?
- Does authorization include tenant, resource, and action?
- Will a background task or stream outlive a request-scoped resource?
- Do tests override the exact provider and clear global override state?
- Does the graph remain understandable without framework magic?

## Interview prompts

1. **What is FastAPI dependency caching?** A dependency result is normally reused within one request when the same dependency is needed more than once. It is not a cross-request cache.
2. **What belongs in lifespan versus a dependency?** Process-wide pools and clients belong in lifespan. Request-scoped sessions, principals, and units of work belong in dependencies. A business transaction belongs around the use case.
3. **Why avoid side effects in dependencies?** Graph resolution and validation can stop before the endpoint executes, so a side effect may occur for a rejected request. Side effects also become hidden and harder to order.
4. **How do `yield` dependencies handle errors?** Setup runs before `yield`; cleanup in `finally` runs when the scope exits. A dependency can roll back on an exception but should preserve the original error and cancellation.
5. **Should every service have a protocol?** No. Add abstractions where they represent a stable capability or infrastructure boundary and improve substitution. Empty pass-through interfaces create navigation cost without isolation.
6. **How do you test dependency-driven code?** Unit test services with direct fakes. Use `dependency_overrides` for transport integration, execute lifespan when required, and isolate override state.
7. **Why is a database session per request not automatically a transaction per request?** A session is a workspace and connection manager; transactions are explicit atomic business boundaries. A request may contain no transaction or, in unusual workflows, more than one.

## Sources

- [FastAPI dependency injection](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [FastAPI sub-dependencies and caching](https://fastapi.tiangolo.com/tutorial/dependencies/sub-dependencies/)
- [FastAPI dependencies with `yield`](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [FastAPI classes as dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/classes-as-dependencies/)
- [FastAPI parameterized dependencies](https://fastapi.tiangolo.com/advanced/advanced-dependencies/)
- [FastAPI dependencies in decorators](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-in-path-operation-decorators/)
- [FastAPI global dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/global-dependencies/)
- [FastAPI testing dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
