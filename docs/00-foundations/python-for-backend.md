# Python Foundations for Backend Engineers

Python syntax is the easy part of a backend service. The harder part is knowing which objects live for one request, which live for the process, where failures cross a boundary, and which work can safely run concurrently. FastAPI makes those choices visible because type annotations, callables, context managers, and `async` functions are part of its public programming model.

This chapter establishes the Python knowledge used throughout the handbook. Examples target Python 3.11 or newer.

## 1. Start with the execution model

A deployed Python API normally has several layers of concurrency:

1. A process manager or container starts one or more worker processes.
2. Each worker imports the application once and owns a separate Python heap.
3. An ASGI server runs an event loop in each worker.
4. The event loop interleaves asynchronous requests.
5. Synchronous route functions and dependencies may run in a thread pool.

This has immediate consequences:

- A module-level dictionary is shared by requests in one process, but not by other workers or hosts.
- Mutating global state can cause races even if a single test client looks correct.
- Restarting a worker loses in-memory state.
- Adding workers does not make a local cache or lock distributed.
- Import-time work is repeated per process and can make startup slow or fragile.

Treat process memory as an optimization or process-local coordination mechanism, never as the system of record.

## 2. Names, objects, and mutability

Python variables are names bound to objects. Assignment does not copy an object.

```python
filters = {"status": ["open"]}
other_filters = filters
other_filters["status"].append("pending")

assert filters == {"status": ["open", "pending"]}
```

This matters when defaults, cached values, test fixtures, and request-scoped data contain mutable objects. Pydantic handles model defaults deliberately, but ordinary Python functions do not:

```python
# Wrong: every call shares the same list.
def collect_error(message: str, errors: list[str] = []) -> list[str]:
    errors.append(message)
    return errors


# Correct: create state per call.
def collect_error(
    message: str,
    errors: list[str] | None = None,
) -> list[str]:
    current = [] if errors is None else errors
    current.append(message)
    return current
```

Prefer immutable values for configuration and value objects. A frozen dataclass communicates intent and prevents accidental assignment:

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str
```

`frozen=True` is not a security boundary and does not recursively freeze nested objects. It is a design constraint for application code.

## 3. Type hints are contracts for tools

Python type annotations are not runtime validation. They support editors, static analyzers, framework introspection, and human review. FastAPI and Pydantic choose to inspect them at runtime, but a regular annotated function still accepts the wrong type unless its code rejects it.

```python
def calculate_total(unit_price: int, quantity: int) -> int:
    return unit_price * quantity


# Python does not reject this call at the boundary.
unexpected = calculate_total("10", 3)
assert unexpected == "101010"
```

Validate untrusted input at system boundaries, then pass well-typed values inward. Static checking and runtime validation solve different problems.

### Model behavior, not container details

Use abstract collection types for inputs when callers do not need a specific implementation, and concrete types for return values when the implementation guarantees them.

```python
from collections.abc import Iterable, Sequence
from uuid import UUID


def unique_ids(values: Iterable[UUID]) -> list[UUID]:
    return list(dict.fromkeys(values))


def first_page(values: Sequence[str], size: int) -> list[str]:
    return list(values[:size])
```

Use `Protocol` for structural interfaces that application services depend on:

```python
from typing import Protocol
from uuid import UUID


class User(Protocol):
    id: UUID
    email: str


class UserReader(Protocol):
    async def get(self, user_id: UUID) -> User | None: ...


async def require_user(reader: UserReader, user_id: UUID) -> User:
    user = await reader.get(user_id)
    if user is None:
        raise LookupError(f"user {user_id} not found")
    return user
```

The service depends on the capability it needs, not on a SQLAlchemy class. A fake that satisfies the protocol can be used in unit tests without inheritance.

### Use `Annotated` for framework metadata

`typing.Annotated` keeps the underlying type usable by static tools while attaching metadata for FastAPI or Pydantic:

```python
from typing import Annotated

from fastapi import Query

PageSize = Annotated[int, Query(ge=1, le=100)]
```

Named aliases reduce repeated constraints, but avoid hiding business meaning inside a large web of aliases.

## 4. Functions, callables, and dependency boundaries

Functions are objects. They can be passed to constructors, returned from factories, wrapped by decorators, and inspected by FastAPI. This is the basis of dependency injection.

Use keyword-only arguments when positional calls would be ambiguous:

```python
from datetime import datetime


def schedule_report(
    report_id: str,
    *,
    run_at: datetime,
    notify: bool = True,
) -> None:
    scheduler.enqueue(report_id=report_id, run_at=run_at, notify=notify)
```

Keep pure computation separate from I/O. Pure functions are deterministic, cheap to test, and safe to run without application infrastructure:

```python
from decimal import Decimal, ROUND_HALF_UP


def calculate_tax(subtotal: Decimal, rate: Decimal) -> Decimal:
    return (subtotal * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

The route can parse input, a service can coordinate database and payment work, and this function can own the calculation. A route that contains all three concerns becomes difficult to reuse and test.

### Decorators need restraint

Decorators are useful for cross-cutting behavior, but they can hide control flow and break FastAPI's signature inspection. Preserve metadata with `functools.wraps`:

```python
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def audited(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        # Emit a structured audit event here.
        return function(*args, **kwargs)

    return wrapper
```

For authentication, transactions, and request-scoped resources, explicit dependencies or middleware are usually clearer than custom route decorators.

The example wrapper is synchronous. A decorator for an async callable needs an async wrapper that awaits the wrapped function; otherwise it observes coroutine creation rather than completion.

## 5. Exceptions define failure boundaries

Raise exceptions when a function cannot honor its contract. Catch them where the caller can add context, compensate, retry safely, or translate them into another boundary's error model.

```python
class DomainError(Exception):
    """Base class for expected business failures."""


class InsufficientStock(DomainError):
    def __init__(self, *, sku: str, available: int) -> None:
        super().__init__(f"insufficient stock for {sku}")
        self.sku = sku
        self.available = available
```

A domain service can raise `InsufficientStock`; the HTTP layer can map it to `409 Conflict`. The domain should not raise `HTTPException`, because that couples business code to one transport.

Avoid these patterns:

```python
async def hidden_failure() -> object | None:
    try:
        return await provider.call()
    except Exception:
        return None  # Hides programming errors, cancellation, and provider failures.
```

```python
try:
    await charge_card()
except TimeoutError:
    await charge_card()  # May create a duplicate charge.
```

Catch the narrowest useful exception. Preserve the cause when translating:

```python
try:
    record = await gateway.fetch(reference)
except GatewayTimeout as exc:
    raise ProviderUnavailable(reference=reference) from exc
```

Log an exception once at the boundary that owns reporting. Logging and re-raising at every layer produces duplicate events without new information.

## 6. Context managers own resource lifetime

Files, database sessions, locks, and network clients need deterministic cleanup. Context managers express acquisition and release as one unit.

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient


@asynccontextmanager
async def provider_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        base_url="https://provider.example",
        timeout=5.0,
    ) as client:
        yield client
```

An application-wide connection pool should usually be created during lifespan startup and closed during shutdown. A database session or transaction normally belongs to one request or use case. Distinguish the lifetime of the pool from the lifetime of a checked-out connection.

Cleanup must run on errors and cancellation. Do not rely on garbage collection to return scarce resources promptly.

## 7. Iterators, generators, and streaming

An iterable can produce values lazily instead of holding all of them in memory:

```python
from collections.abc import Iterator


def batches(values: list[str], size: int) -> Iterator[list[str]]:
    if size < 1:
        raise ValueError("size must be positive")
    for start in range(0, len(values), size):
        yield values[start : start + size]
```

Lazy production does not automatically make an HTTP response memory-safe. A serializer might materialize the iterable, a database result may retain a connection, and a slow client can hold resources for a long time. Streaming endpoints need explicit limits, cancellation handling, timeouts, and observability.

An async generator can model a resource dependency with teardown:

```python
from collections.abc import AsyncIterator


async def transaction_scope() -> AsyncIterator[Transaction]:
    transaction = await begin_transaction()
    try:
        yield transaction
        await transaction.commit()
    except BaseException:
        await transaction.rollback()
        raise
    finally:
        await transaction.close()
```

The exact commit policy is an architectural choice. Some systems commit in the service so transaction boundaries remain visible; others use a unit-of-work dependency. Never let an implicit commit make a multi-step business operation partially durable.

## 8. Data structures and value choices

Backend bugs often come from choosing a convenient primitive that does not represent the domain:

- Use `Decimal` for exact decimal business values such as money. Define rounding rules explicitly.
- Use timezone-aware `datetime` values for instants. Store and transmit a documented timezone, commonly UTC.
- Use `UUID`, integer IDs, or validated opaque strings consistently. Do not expose a storage key merely because it exists.
- Use `Enum` or `Literal` for genuinely closed sets. Plan migrations when a database enum is involved.
- Use `bytes` for binary data and `str` for decoded text. Decode at a boundary with an explicit encoding.
- Use `set` for membership only when ordering and duplicates have no meaning.

Do not use floating-point equality for financial values:

```python
from decimal import Decimal

price = Decimal("19.99")
quantity = 3
total = price * quantity
```

Parse `Decimal` from a string or JSON decimal representation according to the API contract. Converting an already imprecise binary float does not restore lost precision.

## 9. Modules, packages, and imports

Imports execute module top-level code once per interpreter and cache the module object. Keep top-level work predictable:

```python
# Good: declarations are cheap and deterministic.
DEFAULT_PAGE_SIZE = 50


# Risky: network access can fail during import and is repeated by each worker.
catalog = requests.get("https://provider.example/catalog").json()
```

Use application lifespan for network clients, pools, and model loading that require cleanup or failure handling.

### Prevent circular imports

A circular import usually signals confused ownership. Common remedies are:

- Move shared protocols or value types into a lower-level module.
- Pass collaborators into services instead of importing global instances.
- Keep the application composition root in one high-level module.
- Import routers in the application factory, not application objects from routers.
- Use `TYPE_CHECKING` only for annotations when runtime imports are unnecessary.

Do not scatter local imports inside functions merely to silence the cycle. That can be a tactical escape hatch, but the dependency direction remains wrong.

## 10. Configuration and secrets

Configuration should be explicit, validated at startup, and immutable during a process lifetime unless dynamic configuration is a designed feature.

```python
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: SecretStr
    request_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Call `get_settings()` from application composition or lifespan before readiness so missing production configuration fails during startup, not on the first user request. An `.env` file is a development convenience, not a production secret store. Do not log `SecretStr` values, return settings objects from endpoints, or bake environment-specific credentials into container images. Validate cross-field invariants, such as disallowing debug mode in production, before accepting traffic.

## 11. Packaging and reproducible environments

Define dependencies and tool configuration in `pyproject.toml`. Pin direct and transitive versions through a lock file produced by the chosen package manager. A version range describes compatibility intent; a lock file records a reproducible resolution.

Separate, at minimum:

- Runtime dependencies required to serve requests.
- Development dependencies for tests, formatting, linting, typing, and documentation.
- Optional integration dependencies that not every deployment needs.

Use a supported Python minor version consistently in local development, CI, and production. Compile native dependencies for the target platform in a controlled build. Run vulnerability review and dependency updates as routine maintenance, not as an emergency-only activity.

## 12. Concurrency vocabulary

- **Synchronous** code completes one operation before continuing in that execution path.
- **Asynchronous** code can suspend at explicit await points so an event loop can run other work.
- **Concurrency** means multiple tasks make progress during overlapping time.
- **Parallelism** means work executes at the same instant on multiple cores or machines.
- **I/O-bound** work mainly waits on databases, files, or networks.
- **CPU-bound** work mainly computes and consumes processor time.

`async def` does not make blocking code asynchronous. A blocking client called inside an async route can stop that worker's event loop. Conversely, a normal `def` route is a valid choice for blocking libraries because FastAPI can run it in a thread pool. Thread pools are finite, and moving a bad call to a thread does not remove its latency or downstream load.

The detailed decision guide is in [Async, Concurrency, and Work Placement](../01-fastapi-core/async-concurrency.md).

## 13. A boundary-oriented service example

The following application service does not know about HTTP or a particular database library:

```python
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class RegisterUser:
    email: str


@dataclass(frozen=True, slots=True)
class RegisteredUser:
    id: UUID
    email: str


class UserRepository(Protocol):
    async def email_exists(self, email: str) -> bool: ...
    async def add(self, user: RegisteredUser) -> None: ...


class DuplicateEmail(Exception):
    """Raised when registration conflicts with the unique email invariant."""


class RegistrationService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def register(self, command: RegisterUser) -> RegisteredUser:
        normalized = command.email.strip().lower()
        if await self._users.email_exists(normalized):
            raise DuplicateEmail(normalized)

        user = RegisteredUser(id=uuid4(), email=normalized)
        await self._users.add(user)
        return user
```

The existence check improves the error message but cannot enforce uniqueness under concurrency. The database still needs a unique constraint, and the repository must translate the resulting constraint violation. This distinction between a friendly pre-check and an authoritative invariant is a recurring backend design theme.

## 14. Common mistakes and better choices

| Mistake | Why it fails | Better choice |
| --- | --- | --- |
| Mutable function defaults | State leaks between calls | Use `None`, then allocate per call |
| Module globals as durable storage | Workers and hosts do not share memory | Use a database or distributed store |
| `except Exception: pass` | Hides failures and corrupts control flow | Catch narrow exceptions and preserve causes |
| HTTP exceptions in domain services | Couples business logic to FastAPI | Translate domain errors at the API boundary |
| Network calls during import | Startup becomes slow and brittle | Acquire resources in lifespan |
| Type hints treated as validation | Untrusted data reaches business logic | Validate at boundaries with Pydantic or explicit parsers |
| Async function with blocking I/O | Stops the event loop | Use an async client, sync route, or bounded thread offload |
| One shared database session | Transactions and identity state leak across requests | Create a request or use-case scoped session |
| Blind retries | Duplicates side effects and amplifies incidents | Retry only classified, idempotent operations with limits |

## 15. Review checklist

Before accepting a Python backend change, ask:

- Are public functions and boundaries typed?
- Is untrusted input validated before domain use?
- Is mutable state scoped correctly?
- Does every acquired resource have deterministic cleanup?
- Are transaction and retry boundaries explicit?
- Does an exception retain enough context without leaking secrets?
- Can business logic run without FastAPI in a unit test?
- Could import-time behavior contact the network or mutate external state?
- Does concurrency create a race that only a database constraint or distributed primitive can resolve?
- Is blocking or CPU-heavy work placed deliberately?

## Interview prompts

1. **Why are type hints not enough for API input?** They are metadata unless code inspects and enforces them. FastAPI uses Pydantic for runtime validation, while a static checker finds different classes of errors before execution.
2. **Why is a module-level cache inconsistent with four workers?** Each worker has a different address space and therefore a different cache. Invalidation and capacity are also per process.
3. **Where should a database transaction begin and end?** Around one atomic business operation, usually in an application service or explicit unit of work. A request is not automatically the correct transaction boundary.
4. **What does dependency inversion buy a backend service?** Business code depends on required behavior rather than infrastructure details, which makes replacements and focused tests possible. It is valuable when the abstraction represents a real boundary, not when it only renames one ORM call.
5. **Why can an existence check not guarantee uniqueness?** Another transaction can insert between the check and write. An authoritative database constraint resolves that race.
6. **When is a generator dangerous in an API?** When it holds a connection, transaction, file, or large producer open while a slow or disconnected client consumes the stream.

## Sources

- [Python language reference: data model](https://docs.python.org/3/reference/datamodel.html)
- [Python typing documentation](https://docs.python.org/3/library/typing.html)
- [Python data classes](https://docs.python.org/3/library/dataclasses.html)
- [Python context manager utilities](https://docs.python.org/3/library/contextlib.html)
- [Python exceptions](https://docs.python.org/3/tutorial/errors.html)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [Python packaging: writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
