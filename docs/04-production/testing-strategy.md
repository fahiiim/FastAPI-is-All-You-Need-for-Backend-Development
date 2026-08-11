# Testing Strategy

A useful test suite is a risk-control system. It should detect incorrect business behavior, unsafe authorization, broken data constraints, incompatible API changes, and integration failures quickly enough that engineers trust and run it. Test count and line coverage are weak substitutes for choosing the right boundaries.

FastAPI makes HTTP tests convenient, but a suite made entirely of route tests is slow to diagnose and often misses worker, database, and provider semantics. Build a portfolio: many focused domain tests, enough database and adapter integration tests, HTTP contract tests at the application boundary, and a small number of deployed end-to-end checks.

## What each test level proves

| Level | Runs | Primary value | Typical exclusions |
|---|---|---|---|
| Unit | Domain/service code in memory | Business rules, edge cases, fast feedback | Network, real database, ASGI stack |
| Component | FastAPI app plus selected fakes | Routing, validation, dependency wiring, error contract | Real external providers |
| Integration | Real PostgreSQL, Redis, broker, or HTTP fake | SQL, constraints, transactions, serialization, protocol assumptions | Entire deployed system |
| Contract | Provider/consumer schemas or OpenAPI | Compatibility between independently changed systems | Full business workflow |
| End-to-end | Deployed entry point and dependencies | Critical system wiring and operator confidence | Exhaustive edge cases |

The shape is not a rigid pyramid. Database-heavy applications may need many repository integration tests because mocking SQLAlchemy would prove little. Keep the slowest and least deterministic tests narrowly focused on risks that cheaper tests cannot cover.

## Organize tests around application boundaries

One workable structure is:

```text
tests/
  conftest.py
  factories/
    users.py
    orders.py
  unit/
    domain/
    services/
  component/
    api/
  integration/
    repositories/
    redis/
    messaging/
    providers/
  contract/
  e2e/
```

Mirror domain modules where that aids discovery, but do not duplicate the application tree mechanically. Name a test after behavior:

```python
def test_cancelling_a_shipped_order_is_rejected() -> None: ...


def test_order_owner_cannot_read_another_tenants_order() -> None: ...
```

Those names survive refactoring better than `test_cancel_order_service_method`.

## Make the application constructible

An application factory lets tests provide settings and adapters without importing a process-global application that has already opened pools.

```python
from fastapi import FastAPI


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(lifespan=build_lifespan(resolved))
    app.state.settings = resolved
    install_middleware(app)
    install_error_handlers(app)
    app.include_router(api_router, prefix="/v1")
    return app


app = create_app()
```

Tests can construct a new application where isolation matters. Session-scoped app fixtures are faster but make leaked dependency overrides and state more dangerous.

## pytest fixtures are a dependency graph

Fixtures should provide resources and tear them down. Keep hidden global behavior small. Prefer the narrowest scope that gives acceptable performance.

```python
# tests/conftest.py
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://test:test@localhost/test_app",
        public_base_url="http://testserver",
        signing_key="test-only-key-that-is-long-enough-0001",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # The context manager runs application lifespan startup and shutdown.
    with TestClient(app) as test_client:
        yield test_client
```

Avoid an autouse fixture that silently mocks half the system. It becomes difficult to understand which production behavior a test exercises.

### Parameterization

Use parameterization to make a behavioral matrix explicit:

```python
import pytest


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        ("admin", 200),
        ("support", 200),
        ("member", 403),
    ],
)
def test_export_permissions(
    client: TestClient, token_for_role: TokenFactory, role: str, expected_status: int
) -> None:
    response = client.post(
        "/v1/exports",
        headers={"Authorization": f"Bearer {token_for_role(role)}"},
    )
    assert response.status_code == expected_status
```

Keep the matrix readable. A cross-product with dozens of poorly named cases is harder to review than focused tests.

## TestClient versus AsyncClient

Use `TestClient` for synchronous test functions that only need to call the ASGI application. It runs the asynchronous app behind a synchronous interface. Current Starlette releases prefer the `httpx2` transport for `TestClient`; plain `httpx` remains temporarily supported but emits a deprecation warning.

Use `httpx2.AsyncClient` when the test must await async repositories, coordinate concurrency, or interact with async fixtures in the same event loop. Outbound application clients may still use HTTPX independently; the test transport choice does not require changing the production adapter.

```python
from collections.abc import AsyncIterator

import httpx2
import pytest
from fastapi import FastAPI


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    # ASGITransport does not own application lifespan. Run it explicitly.
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client


@pytest.mark.anyio
async def test_create_order(async_client: httpx2.AsyncClient) -> None:
    response = await async_client.post(
        "/v1/orders",
        json={"sku": "SKU-42", "quantity": 2},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SKU-42"
```

Do not put `TestClient` inside an `async def` test. Also do not assume an ASGI transport runs lifespan automatically. Missing lifespan hides initialization bugs and leaks pools.

## Dependency overrides

FastAPI exposes `app.dependency_overrides`, mapping the original dependency callable to its replacement. Override at a boundary you own, such as identity, clock, repository, or provider port.

```python
from collections.abc import Iterator

import pytest


@pytest.fixture
def authenticated_user(app: FastAPI) -> Iterator[User]:
    user = User(id="user_test", tenant_id="tenant_a", roles={"member"})

    async def override_current_user() -> User:
        return user

    app.dependency_overrides[get_current_user] = override_current_user
    try:
        yield user
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

Always remove an override. A leaked override can make later authorization tests pass for the wrong reason. Prefer a fresh app or a fixture with `finally` over resetting a shared dictionary by convention.

An override replaces the dependency and its subdependencies. That is useful for component tests, but means the test no longer exercises token parsing or database session setup. Keep separate tests for those boundaries.

## Unit-test business behavior without FastAPI

Business services should accept explicit collaborators and return domain values or raise domain errors.

```python
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class FakeClock:
    now_value: datetime

    def now(self) -> datetime:
        return self.now_value


async def test_expired_quote_cannot_be_accepted() -> None:
    quote = Quote(expires_at=datetime(2026, 1, 1, tzinfo=UTC))
    service = QuoteService(
        repository=InMemoryQuoteRepository(quote),
        clock=FakeClock(datetime(2026, 1, 2, tzinfo=UTC)),
    )

    with pytest.raises(QuoteExpired):
        await service.accept(quote.id)
```

Inject clocks, ID generators, and ports. Patching `datetime.now()` throughout the standard library is brittle.

In-memory repositories can be useful for domain logic, but they are not evidence that SQL constraints, locking, relationship loading, or transaction isolation work. Run the same behavioral contract against both in-memory and SQL adapters where semantic equivalence matters.

## Database testing with PostgreSQL

If production uses PostgreSQL, use PostgreSQL for integration tests. SQLite differs in typing, constraints, JSON, concurrency, locking, and SQL syntax. It is appropriate only when the application truly supports it as a target or when a test intentionally does not rely on database semantics.

### Isolation options

1. **Transaction per test**: fast, then roll back. Requires the session to join an outer test transaction correctly.
2. **Truncate tables**: realistic commits, but slower and careful ordering is needed.
3. **Schema/database per worker**: strong isolation for parallel tests, with higher setup cost.
4. **Ephemeral container per suite or worker**: close to production and reproducible.

Run real migrations to create the test schema. `metadata.create_all()` can conceal a broken or missing Alembic migration.

### Async SQLAlchemy transaction fixture

SQLAlchemy 2.x can join a session to an outer connection transaction with savepoints. This lets application code call `commit()` while the test still rolls everything back.

```python
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)


@pytest.fixture
async def db_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as session:
        yield session


@pytest.fixture
def override_db_session(
    app: FastAPI, db_session: AsyncSession
) -> Iterator[None]:
    async def override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)
```

Test this fixture itself with endpoints that commit and roll back. Transactional test patterns can mask after-commit hooks, connection-pool behavior, and multi-connection concurrency. Put those cases in tests using real committed transactions and cleanup.

### What repository tests should exercise

- unique, foreign-key, check, and exclusion constraints;
- explicit transaction commit and rollback behavior;
- concurrent updates and optimistic version conflicts;
- row locks and isolation assumptions;
- pagination stability and ordering tie-breakers;
- eager-loading behavior and query count where N+1 is a risk;
- timezone and numeric precision;
- migrations both from an empty database and from a representative previous version.

Assert observable behavior rather than SQLAlchemy implementation details unless the SQL plan or query count is itself the risk.

## Factories and test data

Factories should produce valid defaults and make relevant differences explicit:

```python
from dataclasses import replace
from decimal import Decimal


def an_order(**overrides: object) -> Order:
    base = Order(
        id="ord_test",
        tenant_id="tenant_a",
        status=OrderStatus.PENDING,
        total=Money(Decimal("25.00"), "USD"),
    )
    return replace(base, **overrides)
```

Avoid one giant fixture graph that creates a company, twenty users, and fifty orders for every test. Minimal data makes failures comprehensible.

Use randomized data carefully. Randomness finds edge cases only if the seed is printed and failures reproduce. Property-based testing tools such as Hypothesis are preferable to ad hoc random loops because they generate and shrink examples systematically.

## Mocking external boundaries

Mock where the code looks up the name, or better, inject a protocol implementation. Do not mock internal methods merely to make a test pass after every refactor.

```python
from dataclasses import dataclass, field


@dataclass
class StubPaymentGateway:
    result: AuthorizationResult
    calls: list[str] = field(default_factory=list)

    async def authorize(self, *, operation_id: str, **_: object) -> AuthorizationResult:
        self.calls.append(operation_id)
        return self.result
```

For HTTP adapters, HTTPX `MockTransport` can exercise real request construction and response parsing:

```python
import httpx


def provider_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Idempotency-Key"] == "op_123"
    return httpx.Response(200, json={"id": "pay_7", "state": "approved"})


transport = httpx.MockTransport(provider_handler)
client = httpx.AsyncClient(transport=transport, base_url="https://provider.test")
```

Close clients in fixtures. Add a smaller suite against a sandbox or provider-compatible fake to catch assumptions the mock cannot know.

`monkeypatch` is useful for environment variables and legacy globals. Prefer explicit dependency injection in new code. If patching is required, patch the symbol imported by the module under test, not necessarily its original definition.

## Authentication and authorization tests

Authentication tests should cover:

- missing, malformed, expired, not-yet-valid, wrongly signed, and wrong-audience tokens;
- key rotation and unknown key IDs;
- revoked sessions or refresh tokens;
- correct 401 challenge behavior without credential leakage.

Authorization tests need a subject-resource-action matrix:

| Subject | Same tenant | Own resource | Action | Expected |
|---|---|---|---|---|
| member | yes | yes | read | allow |
| member | yes | no | read | policy-specific |
| member | no | no | read | deny or concealed 404 |
| support | yes | no | read | allow with audit |
| admin | yes | no | delete | allow if explicit permission |

Do not stop at role checks. Test object ownership, tenant scope, disabled accounts, field-level restrictions, and enumeration resistance. Verify both status and absence of data leakage.

Component tests may override identity. Separate security integration tests must exercise actual bearer parsing, signature verification, and security dependencies.

## Background job tests

Test the function that performs work separately from its Celery or broker wrapper. Then test queue-specific behavior:

- message contains only the versioned fields expected;
- transient failures retry and permanent failures do not;
- the same message delivered concurrently produces one business effect;
- worker death after the effect but before acknowledgement is safe;
- task time limit and cancellation leave recoverable state;
- exhausted retries reach a visible terminal state;
- outbox publication and inbox deduplication work with real transactions;
- scheduler failover or duplicate firing is harmless.

Celery eager mode bypasses serialization, process separation, and broker acknowledgement. Treat it as a convenience for component tests, not proof of distributed behavior.

## Cache and rate-limit tests

For caching, cover hit, miss, corrupt payload, expiry, invalidation after commit, Redis timeout, and concurrent stampede. Assert database load remains bounded under concurrent misses where single-flight behavior is promised.

For rate limits, test boundary timing with an injected clock or isolated Redis, atomic concurrent requests, identity scoping, correct 429 metadata, and the configured Redis failure policy. Avoid real sleeps; advance a fake clock or use Redis keys with controlled expiration in an integration suite.

## Webhook tests

Use exact raw byte fixtures. Cover valid, invalid, stale, missing, and rotated signatures; oversized bodies; duplicate event IDs arriving concurrently; out-of-order object versions; unknown event types; durable receipt before 2xx; and replay after a processing bug is fixed.

Outbound webhook tests should cover DNS and TLS failure, timeout after receiver success, redirects to private addresses, response-size limits, stable event IDs across attempts, retry classification, exhaustion, and manual replay.

## API contract tests

Assert more than status codes:

- response schema and media type;
- stable error code and safe detail;
- required headers such as `Location`, `ETag`, `WWW-Authenticate`, and `Retry-After`;
- pagination order and cursor behavior;
- idempotency replay and mismatched-payload conflict;
- unknown fields according to the compatibility policy;
- OpenAPI contains documented security and error responses.

Snapshot tests are useful for OpenAPI and large stable documents, but review diffs. Do not update snapshots automatically merely because CI failed.

For independently deployed consumers and providers, use schema compatibility checks or consumer-driven contracts. A mock written only by the consumer can agree with the consumer while both disagree with production.

## Concurrency and race testing

Many production defects require overlap. Coordinate tasks with barriers rather than hoping they race:

```python
import asyncio


@pytest.mark.anyio
async def test_only_one_idempotent_request_applies(
    service: PaymentService,
) -> None:
    start = asyncio.Event()

    async def call() -> Payment:
        await start.wait()
        return await service.charge(idempotency_key="same-key")

    tasks = [asyncio.create_task(call()) for _ in range(2)]
    start.set()
    first, second = await asyncio.gather(*tasks)
    assert first.id == second.id
    assert await service.gateway_charge_count() == 1
```

The final assertion must observe a durable effect, not only two equal response objects. Run such tests repeatedly and against the real database isolation level.

## Migrations and deployment compatibility

Migration tests should verify:

- upgrade from the oldest supported deployment schema to head;
- application reads during an expand-and-contract rollout;
- new code works before destructive cleanup;
- downgrade only when the project genuinely supports it;
- backfill is resumable, observable, and bounded;
- indexes and constraints are created with an acceptable locking plan;
- a fresh database from all migrations matches expected metadata semantically.

A migration that succeeds on an empty database can still lock a production table or fail on historical data.

## Coverage, mutation, and test quality

Use line and branch coverage to find untested areas, not as proof of correctness. Excluding impossible or generated paths is better than writing assertions that merely execute code.

Mutation testing changes conditions and values to see whether tests fail. It can reveal suites that execute lines without checking behavior. Apply it selectively to domain and security-critical modules because it is computationally expensive.

Review tests for false confidence:

- assertions only check 200;
- the mock returns exactly what production code expects without contract evidence;
- exceptions are swallowed by fixtures;
- test order changes the result;
- time, randomness, network, or locale are uncontrolled;
- a retry plugin hides a flaky test.

Quarantine is a short incident response for a flaky test, not a permanent category. Assign an owner and repair deadline.

## CI suite design

A practical pipeline often has:

1. formatting, lint, type checking, and fast unit tests;
2. component tests and migration validation;
3. integration tests with pinned service versions;
4. image build and security checks;
5. a small post-deploy smoke suite;
6. scheduled broader compatibility, load, and resilience tests.

Pin test dependency versions and update them deliberately. Parallelize isolated tests by file or database schema. Publish timing reports and address the slowest tests rather than allowing feedback to degrade unnoticed.

Do not reuse production credentials or customer data. Sanitize representative fixtures, and ensure CI logs cannot print secrets.

## Production review checklist

- Business rules have fast tests independent of FastAPI and infrastructure.
- API tests exercise validation, error schemas, headers, identity, and permissions.
- PostgreSQL-specific behavior is tested on PostgreSQL created by real migrations.
- Dependency overrides are scoped and always removed.
- Async tests explicitly run lifespan and close clients.
- Provider mocks validate real adapter requests, with separate contract coverage.
- Queues are tested for duplicate delivery and worker failure, not only eager success.
- Concurrency-sensitive invariants have coordinated race tests.
- Coverage reports guide review but do not replace meaningful assertions.
- CI isolates data, controls nondeterminism, and keeps the fast feedback path fast.

## Interview prompts

1. When would you choose `TestClient` instead of an async ASGI client?
2. Why can SQLite give false confidence for a PostgreSQL application?
3. How can a test allow application code to commit while rolling back after the test?
4. What does a FastAPI dependency override stop exercising?
5. Why is Celery eager mode insufficient for task reliability testing?
6. How would you test a race in an idempotent payment endpoint?
7. What does 90 percent line coverage fail to tell you?
8. How do contract tests differ from end-to-end tests?

## Further reading

- [FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [FastAPI: Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [FastAPI: Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
- [Starlette: TestClient](https://www.starlette.io/testclient/)
- [pytest Fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest Monkeypatching](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- [HTTPX Transports](https://www.python-httpx.org/advanced/transports/)
- [SQLAlchemy: Joining a Session into an External Transaction](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)

## Related topics

- [Queues, Workers, and Scheduling](./queues-workers-and-scheduling.md)
- [Containers and Deployment](./containers-and-deployment.md)
- [Production Architecture](../../architecture/production-architecture.md)
