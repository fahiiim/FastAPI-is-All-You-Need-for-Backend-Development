# FastAPI Framework, Routing, and OpenAPI

FastAPI is an ASGI framework for HTTP APIs. It uses Python type annotations to declare request inputs, Pydantic to validate and serialize data, Starlette for the web layer, and OpenAPI to describe the resulting contract. Those features reduce glue code, but production quality still depends on deliberate boundaries, status semantics, authorization, resource ownership, and failure handling.

## 1. Install and run a minimal application

Create and activate an isolated environment, then install a locked version compatible with the project. The standard installation includes the FastAPI command and common optional dependencies:

```bash
python -m pip install "fastapi[standard]"
```

For a lean deployment, install `fastapi` plus only the selected ASGI server and feature dependencies. Record the resolution in a lock file rather than installing an unbounded latest version during every deployment.

Create `app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(
    title="Orders API",
    version="1.0.0",
    summary="Order capture and retrieval",
)


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}
```

Run a development server with reload:

```bash
fastapi dev app/main.py
```

Run without development reload:

```bash
fastapi run app/main.py
```

The import string and worker topology vary by deployment. Reload watches source files and is a development feature. Do not use it in production.

By default, the generated OpenAPI schema is available at `/openapi.json`, Swagger UI at `/docs`, and ReDoc at `/redoc`. In production, decide whether documentation endpoints are public, authenticated at a gateway, served separately, or disabled. Hiding documentation is not an access control.

## 2. The application is an ASGI callable

`FastAPI()` creates an ASGI application. An ASGI server such as Uvicorn calls it with connection scope, receive, and send channels. FastAPI builds on Starlette's request handling and adds type-driven validation, dependency resolution, and OpenAPI generation.

Create the app in one composition module. Routers should not import the global app object, and domain services should not know that FastAPI exists.

```python
from fastapi import FastAPI

from app.api.orders import router as orders_router


def create_app() -> FastAPI:
    application = FastAPI(title="Orders API", version="1.0.0")
    application.include_router(orders_router, prefix="/api/v1")
    return application


app = create_app()
```

An application factory makes composition explicit and helps tests create an app with selected settings or dependency overrides. Avoid dynamic route registration after the application starts serving requests.

## 3. Path operations declare contracts

A decorator registers a path template and HTTP method. The function is called only after routing, dependency resolution, and input validation succeed.

```python
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Path, Query, status
from pydantic import BaseModel, Field

app = FastAPI()


class OrderCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=100)


class OrderView(BaseModel):
    id: UUID
    product_id: UUID
    quantity: int
    status: str


@app.post(
    "/orders",
    response_model=OrderView,
    status_code=status.HTTP_201_CREATED,
    tags=["orders"],
    summary="Create an order",
)
async def create_order(payload: OrderCreate) -> OrderView:
    # A real route delegates to a service and persists the order.
    return OrderView(
        id=UUID("a066c370-e785-4fea-bffc-321218c195e4"),
        product_id=payload.product_id,
        quantity=payload.quantity,
        status="pending",
    )


@app.get("/orders/{order_id}", response_model=OrderView)
async def get_order(
    order_id: Annotated[UUID, Path(description="Public order identifier")],
    include: Annotated[
        set[str] | None,
        Query(description="Optional related representations"),
    ] = None,
) -> OrderView:
    return OrderView(
        id=order_id,
        product_id=UUID("de5e9400-bdf0-453a-bc47-68cf8195e55f"),
        quantity=1,
        status="pending",
    )
```

The function signature determines input sources by convention:

- A name present in the path template is a path parameter.
- A scalar parameter not in the path is normally a query parameter.
- A Pydantic model is normally a JSON request body.
- `Path`, `Query`, `Header`, `Cookie`, `Body`, `Form`, and `File` make the source and constraints explicit.

Use `Annotated` so the Python type remains the main annotation and FastAPI metadata stays attached to it.

### Route order and collisions

Routes are evaluated in registration order where patterns overlap. Register a fixed path before a variable path:

```python
@app.get("/users/me")
async def current_user() -> dict[str, str]:
    return {"id": "current"}


@app.get("/users/{user_id}")
async def user_by_id(user_id: str) -> dict[str, str]:
    return {"id": user_id}
```

If the variable route is registered first, `me` can be treated as `user_id`. Prefer identifiers with constrained types such as UUID where possible, but do not rely on validation to repair an ambiguous route table.

Register each method and path combination once. Duplicate registrations can leave one handler unreachable while still producing confusing schema or test behavior.

## 4. Path and query parameters

Path parameters identify a resource. Query parameters filter, sort, paginate, search, or modify representation choices.

```python
from typing import Annotated, Literal

from fastapi import APIRouter, Query

router = APIRouter(prefix="/orders", tags=["orders"])

SortOrder = Literal["created_at", "-created_at", "total", "-total"]


@router.get("")
async def list_orders(
    status: Annotated[list[str] | None, Query()] = None,
    sort: Annotated[SortOrder, Query()] = "-created_at",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: Annotated[str | None, Query(max_length=500)] = None,
) -> dict[str, object]:
    return {
        "items": [],
        "page": {"limit": limit, "next": None},
        "filters": {"status": status, "sort": sort, "after": after},
    }
```

Keep query complexity bounded. A syntactically valid filter can still cause an expensive join, full table scan, or unbounded response. Maintain an allow-list of supported filters and sorts, enforce page limits, and create indexes for real access patterns.

Avoid query boolean traps. Clients may encode values differently, so use FastAPI's parsed boolean contract and document it rather than testing raw strings yourself.

## 5. Request bodies

Pydantic models are a strong default for JSON request bodies:

```python
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Body
from pydantic import BaseModel, ConfigDict, Field


class AddressInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line1: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")


class ShipmentCreate(BaseModel):
    destination: AddressInput
    service: Literal["standard", "express"]
    dispatch_after: datetime | None = None


@router.post("/{order_id}/shipments", status_code=201)
async def create_shipment(
    order_id: str,
    payload: Annotated[ShipmentCreate, Body()],
) -> dict[str, str]:
    return {"order_id": order_id, "service": payload.service}
```

An input schema establishes transport shape. It does not prove that an order exists, that the caller owns it, that express service is available, or that inventory is reserved. Those checks belong in authorization, services, and authoritative stores.

Do not accept one broad model for create, update, database persistence, and public output. Separate models make writable and visible fields explicit.

### Partial updates

For a custom JSON partial update, inspect which fields were supplied:

```python
from pydantic import BaseModel, ConfigDict, Field


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
    biography: str | None = Field(default=None, max_length=500)


@router.patch("/profiles/{profile_id}")
async def patch_profile(profile_id: str, payload: ProfilePatch) -> dict[str, object]:
    changes = payload.model_dump(exclude_unset=True)
    # `display_name: null` remains present; an omitted field does not.
    return {"id": profile_id, "changes": changes}
```

Document whether this is a private partial-object format, JSON Merge Patch, or JSON Patch. They are not interchangeable.

## 6. Headers and cookies

Header names are case-insensitive. FastAPI converts underscores in Python parameter names to hyphens by default.

```python
from typing import Annotated

from fastapi import Cookie, Header

RequestId = Annotated[
    str | None,
    Header(alias="X-Request-ID", min_length=8, max_length=128),
]


@router.get("/{order_id}/context")
async def order_context(
    order_id: str,
    request_id: RequestId = None,
    session: Annotated[
        str | None,
        Cookie(alias="__Host-session", max_length=4096),
    ] = None,
) -> dict[str, bool | str | None]:
    return {
        "order_id": order_id,
        "has_request_id": request_id is not None,
        "has_session": session is not None,
    }
```

Do not echo authentication cookies or authorization headers. Treat caller-supplied request IDs as untrusted input, or replace them at a trusted edge. Cookie attributes are set on the response, not on the `Cookie` parameter used to read them:

```python
from fastapi import Response


@router.post("/sessions", status_code=204)
async def create_session(response: Response) -> None:
    token = "opaque-server-generated-value"
    response.set_cookie(
        key="__Host-session",
        value=token,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=3600,
    )
```

Cookie authentication requires a CSRF design for state-changing browser requests. Cookie flags complement authentication and authorization; they do not implement them.

## 7. Forms and file uploads

HTML forms use `application/x-www-form-urlencoded` or `multipart/form-data`, not JSON. Multipart parsing requires `python-multipart` when it is not already included by the selected FastAPI installation.

```python
from typing import Annotated

from fastapi import File, Form, HTTPException, UploadFile


@router.post("/{order_id}/documents", status_code=201)
async def upload_document(
    order_id: str,
    category: Annotated[str, Form(max_length=50)],
    document: Annotated[UploadFile, File(description="PDF evidence")],
) -> dict[str, str | int | None]:
    if document.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="PDF content is required")

    first_chunk = await document.read(64 * 1024)
    await document.seek(0)
    return {
        "order_id": order_id,
        "category": category,
        "filename": document.filename,
        "first_chunk_size": len(first_chunk),
    }
```

`UploadFile` uses a spooled file interface and avoids forcing the entire upload into one `bytes` value. That does not make uploads safe by itself. Production controls include:

- Request limits at the reverse proxy and application boundary.
- Streaming to durable object storage rather than buffering full content.
- A byte-count limit while reading, even if `Content-Length` is present.
- File signature inspection rather than trusting the extension or declared media type.
- Generated storage keys rather than caller-supplied paths.
- Malware scanning and quarantine when required.
- Timeouts, cleanup for partial uploads, authorization, and per-tenant quotas.

JSON and files cannot occupy one request as two different content types. Put structured fields into form parts, encode a documented JSON form part, or use a multi-step workflow with a presigned object-storage upload.

## 8. Response models are an output boundary

FastAPI uses a return annotation or `response_model` to generate schema, serialize values, validate output, and filter undeclared fields.

```python
from pydantic import BaseModel, ConfigDict


class InternalUser:
    def __init__(self, user_id: str, email: str, password_hash: str) -> None:
        self.id = user_id
        self.email = email
        self.password_hash = password_hash


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str


@app.get("/users/{user_id}", response_model=UserView)
async def get_user(user_id: str) -> InternalUser:
    return InternalUser(user_id, "person@example.com", "never-return-this")
```

The response model filters `password_hash`. Still, do not build responses by dumping arbitrary ORM entities and hoping filtering catches every secret. Construct deliberate output models, add regression tests, and review schema changes.

If response validation fails, it is a server bug and normally produces a 500-class response rather than telling the client its request was invalid. Monitor these failures.

For endpoints that return a `Response` directly, FastAPI does not perform ordinary model serialization. Use this intentionally for streaming, files, redirects, or specialized media types, and document responses explicitly in the decorator where client generation matters.

### Status and response headers

Use decorator metadata for a fixed success status:

```python
from fastapi import Response, status


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(order_id: str) -> Response:
    # Delete through a service, with authorization and idempotent semantics.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

For creation, return a `Location` header. For conditional operations, consider `ETag`. Do not send content with `204` or rely on a body for semantics already represented by the status.

## 9. Organize routes with `APIRouter`

Routers group operations, metadata, and dependencies without creating nested ASGI applications.

```python
# app/api/orders.py
from fastapi import APIRouter, Depends

from app.api.dependencies import require_active_user

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(require_active_user)],
    responses={404: {"description": "Order not found"}},
)


@router.get("")
async def list_orders() -> list[dict[str, str]]:
    return []
```

```python
# app/main.py
from fastapi import FastAPI

from app.api.orders import router as orders_router

app = FastAPI()
app.include_router(orders_router, prefix="/api/v1")
```

A common production layout has one router per cohesive feature, not one router for every database table. Keep handlers thin: translate transport input, call a use case, translate its result or error, and attach HTTP metadata.

Router-level dependencies are useful for a shared requirement such as authentication. Resource-level authorization still needs the loaded resource and action, and therefore often belongs in a parameterized dependency or service call.

Mounting a sub-application is different from including a router. A mounted app has a separate OpenAPI document and middleware stack boundary. Use it when that isolation is deliberate.

## 10. OpenAPI is a product artifact

FastAPI generates OpenAPI from application, route, dependency, and Pydantic metadata. The schema drives interactive documentation, client generation, contract review, and sometimes gateway configuration.

Treat these fields as stable API surface:

- Paths and methods.
- Parameter names, locations, requiredness, constraints, and formats.
- Request and response schemas.
- Security schemes and requirements.
- Status-specific response definitions.
- `operationId` values when generated clients use them.
- Deprecation and descriptions.

Add examples that communicate business meaning without containing real credentials or personal data:

```python
from pydantic import BaseModel, ConfigDict, Field


class RefundCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "amount_minor": 1299,
                    "reason": "duplicate",
                }
            ]
        }
    )

    amount_minor: int = Field(gt=0, description="Amount in the currency minor unit")
    reason: str = Field(min_length=1, max_length=200)
```

Descriptions should document units, timezone semantics, whether enum values can grow, authorization rules, and behavior that types cannot express.

### Stable operation identifiers

Generated `operationId` values can change when function names or router structure changes. If client SDKs depend on them, assign them deliberately:

```python
@router.get(
    "/{order_id}",
    operation_id="getOrder",
    response_model=OrderView,
)
async def get_order_by_id(order_id: str) -> OrderView:
    return await order_reader.get(order_id)
```

Enforce uniqueness in CI. An OpenAPI snapshot or compatibility check can flag accidental breaking changes before deployment.

### Customize documentation endpoints

```python
app = FastAPI(
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)
```

Setting a docs URL to `None` disables that UI. Setting `openapi_url=None` also disables schema-based documentation endpoints. If documentation needs authentication, enforce it at a trusted gateway or serve a protected custom route. Do not assume an unlinked URL is private.

`include_in_schema=False` hides an operation from OpenAPI but does not prevent access. Use it for operational endpoints only when omission is intentional, and secure the endpoint independently.

## 11. Lifespan owns application-wide resources

Use a lifespan async context manager for resources shared by the process, such as HTTP client pools, database engines, and model state:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI, Request
from httpx import AsyncClient


class AppState(TypedDict):
    payments: AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
    async with AsyncClient(
        base_url="https://payments.example",
        timeout=5.0,
    ) as payments:
        yield {"payments": payments}


app = FastAPI(lifespan=lifespan)


@app.get("/payment-provider/health")
async def provider_health(request: Request) -> dict[str, bool]:
    client = request.state.payments
    return {"client_ready": client is not None}
```

Startup happens once per worker process. Keep startup bounded by timeouts and fail fast when a required resource cannot initialize. Shutdown should stop accepting work, allow an appropriate drain period, and close resources. Test through a client context that executes lifespan; merely importing the app does not exercise it.

Do not combine `lifespan` with legacy startup and shutdown event handlers and expect both styles to run. Prefer the lifespan mechanism for new applications.

## 12. Background tasks are in-process response callbacks

`BackgroundTasks` schedules work to run after the response has been sent by the application:

```python
import logging

from fastapi import BackgroundTasks, status

audit_logger = logging.getLogger("orders.audit")


def write_audit_record(order_id: str) -> None:
    # Small illustrative operation. Production audit delivery needs durability.
    audit_logger.info("order_acknowledged", extra={"order_id": order_id})


@router.post("/{order_id}/acknowledgements", status_code=status.HTTP_200_OK)
async def acknowledge_order(
    order_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    background_tasks.add_task(write_audit_record, order_id)
    return {"status": "acknowledged"}
```

These tasks run in the web process. They are not durable, do not survive a crash or forced deployment, consume worker capacity, and lack the delivery and retry controls of a queue. They are suitable for short, best-effort follow-up work. Use a durable outbox and worker system when the task is important, expensive, retryable, scheduled, or must scale independently.

Do not pass a request-scoped database session into background work. Dependency cleanup may close it, and its transaction lifetime should not extend invisibly after the response.

## 13. WebSockets are long-lived, stateful connections

WebSockets support bidirectional messages over one upgraded connection:

```python
from typing import Annotated

from fastapi import (
    Cookie,
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)

app = FastAPI()


@app.websocket("/ws/notifications")
async def notifications(
    websocket: WebSocket,
    session: Annotated[str | None, Cookie()] = None,
) -> None:
    if session is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            if len(message) > 4_096:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                return
            await websocket.send_json({"received": message})
    except WebSocketDisconnect:
        # Remove process-local subscriptions and release resources.
        return
```

Authentication must be completed before trusting messages, and authorization must be checked for each channel or action. Browsers do not allow arbitrary `Authorization` headers in the native WebSocket constructor, so cookie or short-lived ticket designs are common. Validate `Origin` when browser cross-site connections matter.

At scale, a process-local connection list reaches only one worker. Use a broker or pub/sub layer to fan out events across workers, define per-connection queue limits, handle slow consumers, send heartbeats if infrastructure requires them, and bound message size and rate. Persist important messages separately if clients need replay or delivery guarantees.

Use ordinary HTTP for request-response operations, Server-Sent Events for one-way server streams with browser reconnection semantics, and WebSockets when full duplex communication is genuinely required.

## 14. Common mistakes

| Mistake | Production consequence | Better design |
| --- | --- | --- |
| Business logic in route functions | Hard to test, reuse, or transact | Delegate one use case to a service |
| One input/output/ORM model | Mass assignment and data leakage | Separate transport and persistence models |
| `async def` around blocking clients | Event loop stalls | Use async clients or deliberate thread offload |
| Unlimited `UploadFile` reads | Memory, disk, or worker exhaustion | Enforce layered size and time limits while streaming |
| `BackgroundTasks` for durable work | Tasks disappear during crashes and deploys | Use an outbox and external worker |
| Router dependency as all authorization | Object ownership is never checked | Perform action and resource-level authorization |
| Hiding a route from OpenAPI for security | Endpoint remains callable | Enforce authentication and authorization |
| Returning arbitrary ORM objects | Lazy I/O and secret exposure | Map to explicit response models |
| Per-request HTTP client creation | No effective connection reuse | Create a client pool in lifespan |
| Process-local WebSocket registry only | Cross-worker messages disappear | Add shared pub/sub and bounded local queues |

## Interview prompts

1. **What does FastAPI infer from a function signature?** Parameter sources and requiredness, validation constraints, dependency graph, response schema where declared, and OpenAPI metadata. It does not infer business authorization or transaction correctness.
2. **Why use `response_model` if the service already returns a dictionary?** It establishes and documents an output boundary, validates the server result, serializes it, and filters undeclared fields. Deliberate mapping is still preferable for sensitive models.
3. **When would you mount an app instead of include a router?** When a separate ASGI application, middleware boundary, or OpenAPI document is intended. Routers are better for composing one API.
4. **Why not create an `AsyncClient` inside every route?** That discards connection pooling and repeats setup. A process-wide client belongs in lifespan, while request-specific headers and deadlines can still be applied per call.
5. **What happens if a background task fails?** The response has already been sent, and the in-process task has no durable retry guarantee. Critical work belongs in a durable job architecture.
6. **What changes when WebSockets run on four workers?** Connections and in-memory subscriptions are partitioned across processes. Cross-worker delivery requires a shared backplane, and deploys need connection draining or reconnection behavior.
7. **Why might generated OpenAPI be a release artifact?** Client SDKs, contract tests, gateways, and consumers depend on it. Schema diffing reveals compatibility changes that code review can miss.

## Sources

- [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/)
- [FastAPI path parameters](https://fastapi.tiangolo.com/tutorial/path-params/)
- [FastAPI query parameters](https://fastapi.tiangolo.com/tutorial/query-params/)
- [FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/)
- [FastAPI header parameters](https://fastapi.tiangolo.com/tutorial/header-params/)
- [FastAPI cookie parameters](https://fastapi.tiangolo.com/tutorial/cookie-params/)
- [FastAPI form data](https://fastapi.tiangolo.com/tutorial/request-forms/)
- [FastAPI request files](https://fastapi.tiangolo.com/tutorial/request-files/)
- [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/)
- [FastAPI bigger applications and `APIRouter`](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [FastAPI metadata and documentation URLs](https://fastapi.tiangolo.com/tutorial/metadata/)
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)
