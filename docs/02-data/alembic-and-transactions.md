# Alembic Migrations and Transaction Boundaries

A schema migration changes the contract shared by deployed application versions, workers, reporting jobs, and the database. The SQL may be short while the operational risk is large. Alembic records ordered schema changes; it does not decide whether those changes are safe for a live workload.

A transaction answers a different question: which state changes succeed or fail as one unit? Production engineering connects the two. A migration must respect PostgreSQL locking and transaction behavior, and application transactions must remain correct while old and new schemas overlap during deployment.

## Alembic's role

Alembic stores a revision graph. Each revision contains `upgrade()` and `downgrade()` operations and identifies its parent revision. The `alembic_version` table records the database's current revision.

Typical commands are:

```bash
alembic current
alembic heads
alembic history --verbose
alembic revision --autogenerate -m "add order payment reference"
alembic upgrade head
alembic downgrade -1
alembic check
```

Run commands through the same locked dependency environment used in deployment. `head` is safe only when the repository intentionally has one head. Parallel feature branches can create multiple heads; resolve them by rebasing unpublished revisions or creating and reviewing an Alembic merge revision.

Never edit a revision that has already run in a shared environment. Add a corrective revision so the history remains reproducible.

## Configure metadata deliberately

Alembic autogeneration compares database state with SQLAlchemy metadata. The environment must import every mapped table and expose the intended metadata.

```python
# migrations/env.py, relevant parts only
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db.base import Base
from app import models  # noqa: F401, registers mapped classes

target_metadata = Base.metadata


def configure_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = context.config.get_section(
        context.config.config_ini_section, {}
    )
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(configure_migrations)

    await connectable.dispose()
```

In a real `env.py`, retain Alembic's offline-mode path as well. Do not import application startup code that connects to external services. Models should be importable without starting the FastAPI application.

Use a naming convention so constraints have stable names. Stable names make diffs, error translation, and constraint removal predictable:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)
```

Changing a naming convention after many migrations requires a planned transition. Do not cause a mass constraint rename accidentally.

## Autogenerate produces a draft

Autogenerate is useful, but it cannot infer intent. In particular, review for:

- a column or table rename represented as drop plus add;
- destructive changes and irreversible data loss;
- nullable and server-default behavior;
- type conversions that need an explicit PostgreSQL `USING` expression;
- index order, sort direction, partial predicates, expressions, and operator classes;
- constraint names and foreign-key delete behavior;
- custom types, extensions, views, functions, triggers, and row-level security policies;
- data transformations and backfill cost;
- operations that take strong table locks;
- unexpected objects from an accidental metadata import.

Autogenerate detecting a difference does not prove the operation is online-safe. Autogenerate detecting no difference does not prove the schema is correct.

### A reviewed small migration

```python
"""Add a provider payment reference.

Revision ID: 9fd82c194d71
Revises: 7a86cb0f31ab
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "9fd82c194d71"
down_revision: str | None = "7a86cb0f31ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("provider_reference", sa.Text(), nullable=True),
    )
    op.create_index(
        "payments_provider_reference_uq",
        "payments",
        ["provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("payments_provider_reference_uq", table_name="payments")
    op.drop_column("payments", "provider_reference")
```

The migration intentionally begins with a nullable column so older writers remain compatible. Whether the non-concurrent index creation is acceptable depends on table size and traffic. On a large active table, create an index concurrently with a separately managed transaction boundary.

## Migration safety is mostly about locks and time

PostgreSQL `ALTER TABLE` subcommands take locks whose strength varies by operation. Even a fast metadata change can wait behind a long transaction, and then block new traffic while queued. Set a short `lock_timeout` for online migrations so deployment fails cleanly instead of causing an application outage.

```python
def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "orders",
        sa.Column("fulfillment_note", sa.Text(), nullable=True),
    )
```

`SET LOCAL` applies to the current transaction. Operational tooling should also set an appropriate statement timeout. A timeout is not a substitute for understanding the lock.

Before running a production migration, establish:

- expected lock level and whether the operation rewrites the table;
- table and index size, row count, write rate, and likely duration;
- application versions compatible with the before, during, and after schemas;
- timeout, monitoring, cancellation, and escalation behavior;
- backup and recovery posture;
- whether replicas and logical subscribers can absorb the write volume;
- a forward-fix plan if rollback would lose data.

Do not run schema migrations independently in every web replica at startup. Use one coordinated deployment job or migration task. Startup races, partial permissions, and long locks make application boot a poor migration coordinator.

## Expand, migrate, contract

Rolling deployments temporarily run old and new code together. An incompatible one-step rename breaks one of them. Use staged compatibility.

Suppose `users.full_name` must become `display_name`:

### 1. Expand

Add `display_name` as nullable. Deploy code that writes both fields and reads `display_name` with a temporary fallback to `full_name`. The database accepts both application versions.

### 2. Migrate data

Backfill in bounded batches with progress checkpoints. Throttle based on database load and replica lag. Do not hold one transaction over millions of rows.

```sql
WITH batch AS (
    SELECT id
    FROM users
    WHERE display_name IS NULL
    ORDER BY id
    LIMIT 5000
    FOR UPDATE SKIP LOCKED
)
UPDATE users AS u
SET display_name = u.full_name
FROM batch
WHERE u.id = batch.id;
```

The job repeats until no rows remain. It records metrics, is safe to resume, and does not assume one pass catches rows written by old code. Dual writing needs a single well-tested implementation path; two independent writes outside a transaction can diverge.

### 3. Enforce and switch reads

Verify the backfill and deploy readers that use only the new column. If the new field must be non-null, validate that invariant with an online-aware sequence appropriate to the supported PostgreSQL version and table size. One pattern is to add a `CHECK (display_name IS NOT NULL) NOT VALID`, validate it, then set `NOT NULL`, after confirming the exact locking behavior for the deployed PostgreSQL version.

### 4. Contract

Stop writing the old column. After every old binary and rollback window is gone, drop `full_name` in a later release. Removing the old column is not part of the first deployment.

The same pattern applies to type changes, table splits, and relationship changes. Compatibility code is temporary and should have an owner and removal revision.

## Concurrent index creation

`CREATE INDEX CONCURRENTLY` reduces write blocking, but PostgreSQL does not allow it inside a transaction block. Alembic provides an autocommit block:

```python
from alembic import op


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_tenant_created_idx
            ON orders (tenant_id, created_at DESC, id DESC)
            WHERE deleted_at IS NULL
            """
        )
```

Entering an autocommit block commits preceding migration operations. Keep such a revision narrowly scoped and understand that the revision is no longer all-or-nothing. A failed concurrent build can leave an invalid index that must be detected and removed before retry. `IF NOT EXISTS` checks only the name, not whether an existing definition is correct or valid.

On partitioned tables and older supported versions, concurrent index procedures have additional restrictions. Test the exact production version.

## Data migrations and backfills

Small deterministic transformations can live in a schema revision. Large backfills are often safer as separately deployable, resumable jobs because they need throttling and observability.

A production backfill should:

- use stable batches and commit between them;
- be idempotent or checkpointed;
- avoid repeatedly scanning the whole table for remaining rows;
- limit lock duration and statement time;
- expose processed, skipped, failed, and remaining counts;
- measure replica lag, database CPU, WAL generation, and application latency;
- coexist correctly with live writes;
- validate its final result before constraints or reads switch.

Do not import current ORM models into old revisions for data transformations. Models evolve, so rerunning the old migration later can execute new mappings against an old schema. Use Alembic operations, SQLAlchemy Core tables declared inside the revision, or explicit SQL tied to that revision.

## Downgrade and rollback strategy

A syntactically valid `downgrade()` is not necessarily a safe rollback. Dropping a populated column destroys data. Reversing a transformation may be ambiguous. A deployment rollback also has to consider which application version can read the current schema.

Classify changes:

- Reversible: adding and later removing an unused index.
- Conditionally reversible: adding a column, provided no unique new data must be preserved.
- Irreversible: destructive aggregation, lossy type conversion, or dropping the only copy of data.

For a failed release, a forward fix is frequently safer than database downgrade. Expand-contract is valuable because the old application can often be redeployed while the expanded schema remains. Document irreversible downgrade functions by raising an explicit error rather than pretending recovery is safe.

A database backup is not an instant rollback mechanism. Restore time, point-in-time recovery, and the effect on writes after the restore point are business continuity concerns that must be exercised.

## Application transaction ownership

The transaction should match one business use case. The FastAPI router handles HTTP concerns; the service coordinates business state; repositories execute data access without committing independently.

```python
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ReserveInventory:
    tenant_id: UUID
    product_id: UUID
    quantity: int


async def reserve_inventory(
    session: AsyncSession,
    command: ReserveInventory,
) -> UUID:
    async with session.begin():
        stmt = (
            select(Inventory)
            .where(
                Inventory.tenant_id == command.tenant_id,
                Inventory.product_id == command.product_id,
            )
            .with_for_update()
        )
        inventory = (await session.scalars(stmt)).one_or_none()
        if inventory is None:
            raise ProductNotFoundError
        if inventory.available < command.quantity:
            raise InsufficientInventoryError

        inventory.available -= command.quantity
        reservation = Reservation.from_command(command)
        session.add(reservation)
        await session.flush()
        reservation_id = reservation.id

        session.add(OutboxEvent.for_reservation(reservation))

    return reservation_id
```

The row lock makes the check and decrement mutually exclusive for that inventory row. An atomic conditional `UPDATE ... WHERE available >= quantity RETURNING ...` may be shorter and reduce lock round trips. The right choice depends on how many rows and invariants the use case touches.

Do not send email, charge a card, or call a webhook inside this database transaction. Network latency extends lock and connection time, and a database rollback cannot undo the remote action. Commit an outbox record with the state change and let an idempotent worker deliver it.

## Savepoints for local recovery

A savepoint, represented by `begin_nested()`, can roll back one optional operation without discarding the outer transaction:

```python
from sqlalchemy.exc import IntegrityError

async with session.begin():
    session.add(order)

    try:
        async with session.begin_nested():
            session.add(IdempotencyRecord(key=request_key, order=order))
            await session.flush()
    except IntegrityError as exc:
        if not is_idempotency_key_conflict(exc):
            raise
        raise RequestAlreadyProcessedError from exc
```

Translate only a known named constraint. A savepoint has database cost and does not make arbitrary exception handling safe. Often the existing idempotency record should be looked up and its stored response returned after the conflicting transaction is visible.

## Optimistic concurrency

Row locks are pessimistic: contenders wait. Optimistic concurrency lets work proceed and rejects a stale writer:

```sql
UPDATE documents
SET body = $1,
    version = version + 1,
    updated_at = now()
WHERE tenant_id = $2
  AND id = $3
  AND version = $4
RETURNING version;
```

If no row returns, respond with a conflict or reload and merge according to the product. This is useful when collisions are uncommon and clients may edit for a long time. It must cover every writer to the resource.

## Retrying serialization failures and deadlocks

PostgreSQL can abort one participant with SQLSTATE `40001` (serialization failure) or `40P01` (deadlock detected). Retry the complete transaction with a fresh session and bounded jittered backoff.

```python
import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

T = TypeVar("T")
RETRYABLE_SQLSTATES = {"40001", "40P01"}


def get_sqlstate(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


async def run_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    attempts: int = 3,
) -> T:
    for attempt in range(attempts):
        try:
            async with session_factory() as session:
                async with session.begin():
                    return await operation(session)
        except DBAPIError as exc:
            retryable = get_sqlstate(exc) in RETRYABLE_SQLSTATES
            if not retryable or attempt == attempts - 1:
                raise

            delay = 0.025 * (2**attempt) + random.uniform(0, 0.025)
            await asyncio.sleep(delay)

    raise AssertionError("transaction loop exhausted")
```

The operation must not perform non-idempotent external side effects. Retrying after an ambiguous connection failure is a different problem: the client may not know whether commit succeeded. Idempotency records and externally visible operation IDs are needed for that uncertainty.

## Transaction failure modes

**Transaction per repository call**

The system commits partial business operations. Move commit ownership to the use-case boundary.

**Transaction around the entire HTTP request by default**

It is simple, but validation, response generation, or slow downstream work can hold a connection and transaction longer than needed. Prefer an explicit service boundary for write transactions.

**Long read transaction**

It retains an old snapshot, can delay vacuum cleanup, and consumes pool capacity. Stream or batch deliberately and monitor transaction age.

**Inconsistent lock ordering**

Two workflows lock the same resources in opposite order and deadlock. Define a stable order and retain bounded whole-transaction retries.

**Migration waits forever for a lock**

It queues behind an old transaction and new application queries queue behind the migration. Use lock timeouts, inspect blockers, and schedule high-risk changes.

**New code deployed before the schema**

Requests fail on missing columns. Define and automate deployment ordering while preserving backward compatibility.

## Testing migrations and transactions

For every release path that matters:

1. Restore or create the oldest supported starting schema.
2. Load representative data, including nulls, duplicates, and edge values.
3. Run `alembic upgrade head`.
4. Assert schema shape and business data.
5. Start the compatible application version and exercise reads and writes.
6. Test downgrade only where it is declared supported.
7. Upgrade again to catch non-repeatable behavior.

On a production-sized clone or generated dataset, measure lock acquisition and migration duration. A tiny CI database cannot reveal table rewrite cost.

Transaction integration tests should use multiple real connections. Coordinate concurrent tasks with events or barriers instead of arbitrary sleeps. Assert the final invariant, expected SQLSTATE handling, and that retries do not duplicate outbox events or other effects.

## Interview discussion

**Why must autogenerate be reviewed?**

It compares metadata, not intent or workload. It cannot safely infer renames, backfills, compatibility windows, acceptable locks, or whether data loss is intended.

**How would you rename a heavily used column without downtime?**

Add the new column, deploy compatible dual-write/read-fallback code, backfill in batches, validate, switch all readers and writers, wait out rollback and old-worker windows, then drop the old column in a later release.

**Why not run Alembic from every FastAPI startup?**

Replicas race for locks and application readiness becomes coupled to a privileged, possibly long-running operation. Use one observable, coordinated migration job.

**What should be retried after a deadlock?**

The entire transaction from a clean session, with bounded jitter. The code must be idempotent with respect to effects outside PostgreSQL.

**When would you use optimistic instead of pessimistic locking?**

Optimistic version checks suit infrequent conflicts and long client think time. Row locks suit short operations where contention is expected and waiting is acceptable. Both need explicit conflict behavior and measurements.

## Authoritative references

- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [Alembic operation directives](https://alembic.sqlalchemy.org/en/latest/ops.html)
- [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
- [SQLAlchemy transactions and connection management](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL `ALTER TABLE`](https://www.postgresql.org/docs/current/sql-altertable.html)
- [PostgreSQL building indexes concurrently](https://www.postgresql.org/docs/current/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)
