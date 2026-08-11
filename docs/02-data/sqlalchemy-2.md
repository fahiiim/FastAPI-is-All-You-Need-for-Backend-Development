# SQLAlchemy 2.x in FastAPI

SQLAlchemy has two closely related APIs:

- Core builds SQL expressions around tables, columns, and connections.
- The ORM maps rows to Python objects and adds an identity map, relationship management, and a unit-of-work flush process.

Both use the same SQL expression language in SQLAlchemy 2.x. Modern ORM queries use `select()`, not the legacy `Query` style. The ORM does not remove the need to understand SQL, transaction boundaries, or query plans.

## Choose Core, ORM, or both

Use the ORM when object identity, relationships, and change tracking make domain code clearer. Use Core for reporting projections, bulk operations, database-specific statements, and places where materializing full entities adds no value. A codebase can use both through the same session and transaction.

The choice is per operation, not necessarily per application:

```python
from sqlalchemy import func, select

stmt = (
    select(Order.status, func.count().label("order_count"))
    .where(Order.tenant_id == tenant_id)
    .group_by(Order.status)
)
rows = (await session.execute(stmt)).mappings().all()
```

This is an ORM-aware statement returning mappings rather than `Order` instances. It is a better fit for a summary endpoint.

## Typed declarative models

SQLAlchemy 2.x uses `Mapped[T]` and `mapped_column()` to connect Python typing to mapped attributes.

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="customers_tenant_email_uq"),
        UniqueConstraint("tenant_id", "id", name="customers_tenant_id_id_uq"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    orders: Mapped[list[Order]] = relationship(
        back_populates="customer",
        cascade="save-update, merge",
        lazy="raise",
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="orders_customer_tenant_fk",
            ondelete="RESTRICT",
        ),
        CheckConstraint("total_amount >= 0", name="orders_total_nonnegative"),
        Index("orders_tenant_created_id_idx", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="orders", lazy="raise")
```

Python annotations describe expected Python values. Database constraints remain authoritative. A migration, not `Base.metadata.create_all()`, should change a deployed schema.

Points worth reviewing in real models:

- Use explicit lengths when they communicate a domain or interoperability limit. PostgreSQL does not execute `varchar(n)` faster than `text` merely because it is shorter.
- Prefer database `server_default` for values that must exist regardless of the writer. A Python `default` runs only through SQLAlchemy.
- Decide delete behavior in both the foreign key and ORM relationship. `delete-orphan` is appropriate only when the child cannot exist independently.
- Avoid putting password hashes, secrets, or large binary fields in `__repr__`.
- An index in a mapping is still a schema change and must be represented by Alembic.

The composite customer foreign key is deliberate defense in depth: an order cannot reference a customer from another tenant even if application authorization fails. The redundant-looking parent uniqueness constraint is required as the target of that composite foreign key.

## Engine and session responsibilities

An `Engine` owns database connectivity and a pool. A `Session` is a mutable unit of work with an identity map and one transaction at a time. It is not a global repository and it is not a cache shared across requests.

### Synchronous configuration

```python
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
    pool_timeout=5,
)

SessionFactory = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=True,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    with SessionFactory() as session:
        yield session
```

A synchronous route or dependency is appropriate when the driver is synchronous. FastAPI runs ordinary `def` path operations and dependencies in a thread pool. Do not call a blocking driver directly from `async def`, because it blocks the event loop.

### Asynchronous configuration

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
    pool_timeout=5,
)

AsyncSessionFactory = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    autoflush=True,
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session
```

Use a URL and driver that actually support asyncio, such as the configured PostgreSQL async dialect. Async database access improves request concurrency when requests spend time waiting on the database. It does not make a slow query faster and can expose the database to more simultaneous work.

One request or independent task gets one session. `Session` is not thread-safe and `AsyncSession` is not safe to share among concurrent asyncio tasks. If `asyncio.gather()` launches three independent database tasks, each needs its own session, and they cannot participate in one ordinary database transaction.

Create engines during application setup and dispose them during lifespan shutdown. Pool size is per process, so account for every server worker and replica.

## Querying with `select()`

### One entity

```python
from sqlalchemy import select

stmt = select(Order).where(
    Order.tenant_id == tenant_id,
    Order.id == order_id,
)
order = await session.scalar(stmt)
```

`scalar()` returns the first column of the first row or `None`. It does not assert uniqueness. When duplicate results would indicate a defect, use:

```python
order = (await session.scalars(stmt)).one_or_none()
```

`one()` and `one_or_none()` fail on multiple rows. `first()` silently accepts them and, unlike old `Query.first()`, does not automatically add `LIMIT 1` to a 2.x `Select` statement.

### A collection

```python
stmt = (
    select(Order)
    .where(Order.tenant_id == tenant_id)
    .order_by(Order.created_at.desc(), Order.id.desc())
    .limit(50)
)
orders = (await session.scalars(stmt)).all()
```

Always define a deterministic order for pagination. A limit without an order has no stable meaning.

### Projection and join

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OrderSummary:
    id: UUID
    customer_email: str
    total_amount: Decimal
    created_at: datetime


stmt = (
    select(
        Order.id,
        Customer.email.label("customer_email"),
        Order.total_amount,
        Order.created_at,
    )
    .join(Customer, Customer.id == Order.customer_id)
    .where(Order.tenant_id == tenant_id)
)

summaries = [OrderSummary(**row) for row in (await session.execute(stmt)).mappings()]
```

A projection reduces selected data and prevents a response serializer from wandering through unloaded relationships. It also makes the API's data needs visible in the query.

### Core mutation with `RETURNING`

```python
from sqlalchemy import update

stmt = (
    update(Order)
    .where(
        Order.tenant_id == tenant_id,
        Order.id == order_id,
        Order.status == "pending",
    )
    .values(status="paid")
    .returning(Order.id)
)
updated_id = await session.scalar(stmt)
```

The conditional update is concurrency-safe for this state transition. The caller should distinguish a missing result according to the API's disclosure policy.

## Flush, commit, refresh, and rollback

`session.add(obj)` registers an object. A flush emits pending SQL within the current transaction. A commit first flushes and then commits. `flush()` is useful when server-generated values or foreign keys are needed before the transaction ends; it does not make data durable.

```python
async def create_order(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
    amount: Decimal,
) -> UUID:
    async with session.begin():
        order = Order(
            tenant_id=tenant_id,
            customer_id=customer_id,
            status="pending",
            total_amount=amount,
        )
        session.add(order)
        await session.flush()
        order_id = order.id

        session.add(
            OutboxEvent(
                aggregate_id=order_id,
                event_type="order.created",
                payload={"tenant_id": str(tenant_id)},
            )
        )

    return order_id
```

The service owns the transaction boundary, and the order plus outbox event commit atomically. The dispatcher later publishes the outbox row. A repository method should not call `commit()` behind its caller's back because that prevents a service from composing several writes atomically.

On an exception, `session.begin()` rolls back. If `flush()` raises, the database transaction is failed; rollback before trying to reuse the session. Keep exception translation outside the transaction context so cleanup completes first.

```python
from sqlalchemy.exc import IntegrityError

try:
    order_id = await create_order(
        session,
        tenant_id=tenant_id,
        customer_id=customer_id,
        amount=amount,
    )
except IntegrityError as exc:
    # Inspect the driver-specific constraint identifier. Translate only known cases.
    raise DuplicateResourceError from exc
```

The shown handler is intentionally incomplete: production code must identify the named constraint before reporting a duplicate. An unknown integrity error should remain a server error and be logged without sensitive values.

## Relationships and loading strategy

Relationships do not replace joins. They configure how related identities and attributes are synchronized and loaded.

Lazy loading seems convenient, but it hides I/O at attribute access and creates N+1 queries. It is especially hazardous with async sessions, where implicit I/O cannot generally occur at arbitrary attribute access. Setting `lazy="raise"` makes an unplanned load fail during development and testing.

### `selectinload` for collections

```python
from sqlalchemy.orm import selectinload

stmt = (
    select(Customer)
    .where(Customer.tenant_id == tenant_id)
    .options(selectinload(Customer.orders))
)
customers = (await session.scalars(stmt)).all()
```

This normally issues one query for customers and one or more `IN` queries for their orders. It avoids one query per customer and avoids multiplying the main result rows. Very large parent batches and composite-key limitations on some databases require attention.

### `joinedload` for a bounded scalar relationship

```python
from sqlalchemy.orm import joinedload

stmt = (
    select(Order)
    .where(Order.tenant_id == tenant_id)
    .options(joinedload(Order.customer))
)
orders = (await session.scalars(stmt)).unique().all()
```

Joined loading is often suitable for many-to-one data needed with every row. Joining a collection duplicates parent columns for each child. When joined eager loading includes a collection, call `unique()` as required by SQLAlchemy and account for result-set expansion.

Use explicit joins with `contains_eager()` only when the same join must both constrain/order the query and populate a relationship. Eager loader joins and business joins have different purposes.

### Large collections

Do not load a customer's million audit events into a Python list. Query the child table with pagination. SQLAlchemy also provides write-only relationship patterns for collections that should never be implicitly materialized.

## Response schemas and session lifetime

Pydantic response models and ORM models have different jobs. An ORM model describes persistence and identity. A response model describes an external contract and must not expose internal columns accidentally.

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    total_amount: Decimal
    created_at: datetime
```

Convert while required attributes are loaded. Returning a detached ORM object with an unloaded relationship can fail after the session closes. Worse, serialization inside an open session may produce invisible queries. A deliberate projection or explicit loader strategy makes cost predictable.

`expire_on_commit=False` is common for request-scoped async sessions because reading expired attributes could require implicit I/O after commit. It also means the object may hold stale values. Refresh explicitly when the database changes a value that the response needs.

## Sync versus async decision

Choose one coherent stack per request path:

| Concern | Synchronous SQLAlchemy | Async SQLAlchemy |
| --- | --- | --- |
| Driver wait | Worker thread blocks | Event loop can schedule other tasks |
| Ecosystem | Broadest compatibility | Requires async-compatible driver and integrations |
| Query speed | Determined mainly by database and SQL | Same |
| Session safety | One thread/task at a time | One task at a time |
| Best fit | Existing sync stack, modest concurrency, blocking dependencies | High concurrent I/O with an end-to-end async path |

Do not convert an application to async to repair missing indexes, N+1 queries, lock waits, or pool exhaustion. Those are different problems.

## Common failure modes

**A global session**

Requests leak transaction and identity-map state into one another. Use one session per request or independent job.

**Commit in every repository method**

A service cannot atomically combine operations. Repositories may flush; the use-case boundary should commit.

**Implicit lazy loads during serialization**

Latency and query count depend on which fields the serializer touches. Use projections, explicit eager loaders, and `lazy="raise"` in sensitive paths.

**Catching an exception and continuing without rollback**

After a failed flush, the session transaction remains unusable until rollback.

**One session shared across `asyncio.gather()`**

Concurrent state changes corrupt the unit-of-work contract. Give each independent task a separate session or keep operations sequential in one transaction.

**Unbounded `.all()`**

The application loads an arbitrary result set into memory. Paginate, stream with care, or aggregate in SQL.

**Using ORM cascade as the only integrity policy**

Bulk SQL and non-ORM writers bypass object cascades. Define database foreign-key actions according to the actual ownership rule.

**Logging SQL with sensitive parameters**

Debug echo can disclose tokens, email addresses, and personal data. Use controlled SQL observability and parameter redaction.

## Testing SQLAlchemy code

Test query behavior against the real database dialect. SQLite differs from PostgreSQL in types, constraints, locking, isolation, and SQL features.

Useful integration tests include:

- a service commits all writes on success and none on failure;
- known constraint errors map to the intended domain/API error;
- tenant criteria appear in every scoped query;
- relationships needed by a response are explicitly loaded;
- list endpoints execute within a query-count budget;
- two sessions exercise concurrency and locking behavior;
- sync and async fixtures close every session and dispose their test engine.

Capture SQL with SQLAlchemy events in a focused query-count assertion. Avoid asserting an exact SQL string unless SQL generation itself is the contract; harmless compiler changes make those tests brittle.

## Interview discussion

**What is the difference between an engine, connection, transaction, and session?**

The engine is the connectivity and pooling facade. A connection is one checked-out database connection. A transaction groups operations on a connection. An ORM session adds an identity map and unit of work, and coordinates a transaction. A session is short-lived mutable state, not a singleton.

**What is the difference between `flush()` and `commit()`?**

Flush synchronizes pending ORM changes to SQL inside the current transaction. Commit makes the transaction durable and ends it. A flushed row can still be rolled back.

**Why prefer `select()` in SQLAlchemy 2.x?**

It unifies Core and ORM statement construction, makes result shapes explicit, and is the supported modern query style. A strong answer also explains `execute()`, `scalars()`, mappings, and cardinality methods.

**How do you fix N+1?**

Measure query count, understand the response shape, then choose a projection, explicit join, `selectinload`, or `joinedload`. The choice depends on relationship cardinality and result size. Loading every relationship eagerly can be worse than N+1.

**Why is `AsyncSession` not safe to share?**

It proxies mutable session and transaction state tied to a connection. Concurrent tasks would interleave stateful operations. Async support removes thread blocking during I/O; it does not make a transaction stateless.

## Authoritative references

- [SQLAlchemy 2.0 unified tutorial](https://docs.sqlalchemy.org/en/20/tutorial/)
- [SQLAlchemy ORM mapping styles](https://docs.sqlalchemy.org/en/20/orm/mapping_styles.html)
- [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [SQLAlchemy ORM querying guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/)
- [SQLAlchemy relationship loading techniques](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
- [SQLAlchemy asyncio extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [SQLAlchemy connection pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
