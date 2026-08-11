# Relational Databases and PostgreSQL

A production API does not merely persist Python objects. It maintains invariants while requests race, processes fail, and schemas evolve. PostgreSQL is a strong default for FastAPI systems that need transactions, relational integrity, expressive queries, and mature operational tooling. The database should enforce facts that must remain true regardless of which endpoint, worker, or script writes the data.

## The relational model in practical terms

A table represents a set of facts. A row is one fact, a column has a defined domain, and a key identifies or relates facts. SQL is declarative: the application describes the result it needs and the database planner chooses an execution plan.

This distinction matters. An ORM can make rows feel like objects, but PostgreSQL still evaluates joins, constraints, indexes, locks, and transactions. Engineers who cannot read the resulting SQL will struggle to diagnose correctness and latency problems.

Use PostgreSQL when the workload benefits from some combination of:

- multi-row atomic updates;
- foreign keys and uniqueness guarantees;
- ad hoc filtering, aggregation, and joins;
- concurrent reads and writes with explicit isolation semantics;
- a durable system of record.

It is not automatically the best store for large immutable blobs, a search corpus that depends on specialist ranking, or ephemeral cache entries. A common production design keeps authoritative metadata in PostgreSQL and uses object storage, a search engine, or Redis for narrower purposes.

## A schema with enforceable invariants

The following schema is deliberately tenant-aware. Globally unique UUIDs are convenient, while composite tenant constraints make accidental cross-tenant references impossible at the database boundary.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email text NOT NULL,
    display_name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_tenant_email_uq UNIQUE (tenant_id, email),
    CONSTRAINT users_tenant_id_id_uq UNIQUE (tenant_id, id),
    CONSTRAINT users_email_not_blank CHECK (length(btrim(email)) > 0)
);

CREATE TABLE orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    customer_id uuid NOT NULL,
    status text NOT NULL,
    total_amount numeric(12, 2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT orders_tenant_id_id_uq UNIQUE (tenant_id, id),
    CONSTRAINT orders_customer_fk
        FOREIGN KEY (tenant_id, customer_id)
        REFERENCES users (tenant_id, id)
        ON DELETE RESTRICT,
    CONSTRAINT orders_total_nonnegative CHECK (total_amount >= 0),
    CONSTRAINT orders_status_valid
        CHECK (status IN ('pending', 'paid', 'cancelled'))
);

CREATE TABLE order_items (
    tenant_id uuid NOT NULL,
    order_id uuid NOT NULL,
    line_number integer NOT NULL,
    product_id uuid NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    PRIMARY KEY (tenant_id, order_id, line_number),
    FOREIGN KEY (tenant_id, order_id)
        REFERENCES orders (tenant_id, id)
        ON DELETE CASCADE,
    CHECK (quantity > 0),
    CHECK (unit_price >= 0)
);
```

Several decisions are doing real work:

- `timestamptz` records an instant. Convert to a user's time zone at an interface boundary.
- `numeric` avoids binary floating-point surprises for monetary values. Some high-throughput systems store minor units as integers instead.
- `NOT NULL` makes required data explicit. An absent value is different from an empty string or zero.
- A named `CHECK` constraint gives a useful error identifier and protects writes outside the API.
- Composite foreign keys carry tenant identity through relationships. An `order` cannot point at another tenant's user even if application authorization fails.
- `ON DELETE CASCADE` is used only where a child has no independent lifetime. Deleting a tenant or order is a high-impact operation and should normally be an audited service operation.

### Primary and foreign keys

A primary key is the row's stable identity. Prefer keys that do not change when business attributes change. Database-generated integers are compact and index-friendly. UUIDs are useful when IDs must be generated outside one database or must be difficult to enumerate, but their indexes are larger. Time-ordered UUID variants can reduce random B-tree insertion patterns, subject to driver and database support.

A foreign key protects referential integrity. It does not automatically create an index on the referencing columns in PostgreSQL. Index foreign-key columns that are used for joins, parent deletion checks, or common filters.

Natural keys such as an email or external provider ID usually belong in a `UNIQUE` constraint, not as the primary key. Their rules can change. For case-insensitive identity, define a single normalization policy and enforce it consistently, for example with a stored normalized value or an appropriate case-insensitive index. Application-only duplicate checks have a race condition; uniqueness must be decided by the database.

### Constraints are concurrency controls

This endpoint pattern is incorrect:

```python
if not await repository.email_exists(tenant_id, email):
    await repository.create_user(tenant_id, email)
```

Two requests can both observe absence and then insert. Keep the friendly pre-check if it improves the response, but retain a unique constraint and translate its specific violation into `409 Conflict`. Do not turn every integrity error into `409`; a foreign-key failure or broken invariant can indicate a server-side defect.

Constraints should express row-local and relational invariants. Rules that involve time, remote services, or complex workflow state often belong in domain logic, sometimes combined with locking or a compare-and-set update.

## SQL every backend engineer should read

The core operations are projection, filtering, joins, grouping, ordering, and mutation. Select only required columns when a row has large payloads.

```sql
SELECT
    o.id,
    o.status,
    o.total_amount,
    u.display_name AS customer_name
FROM orders AS o
JOIN users AS u
  ON u.tenant_id = o.tenant_id
 AND u.id = o.customer_id
WHERE o.tenant_id = $1
  AND o.status = $2
  AND o.deleted_at IS NULL
ORDER BY o.created_at DESC, o.id DESC
LIMIT $3;
```

Place values in driver parameters, never string interpolation. Parameters prevent data from being parsed as SQL and allow the driver to encode types correctly. Table names, column names, and sort directions cannot generally be ordinary bound values, so map them from a small allowlist.

Aggregation changes cardinality. When joining one order to many items, `count(*)` counts joined rows, not necessarily orders. Use `count(DISTINCT o.id)`, pre-aggregate, or query the entity at the correct grain.

An update can combine validation and concurrency control:

```sql
UPDATE orders
SET status = 'paid'
WHERE tenant_id = $1
  AND id = $2
  AND status = 'pending'
RETURNING id, status;
```

Zero returned rows means either the resource does not exist or its state changed. The application can decide whether to issue a second, tenant-scoped lookup or return a deliberately non-revealing result.

## Normalization and deliberate denormalization

Normalization reduces update anomalies:

- First normal form keeps values atomic for the model and avoids repeated column groups.
- Second normal form removes attributes that depend on only part of a composite key.
- Third normal form removes attributes that depend on another non-key attribute.

In practice, start with one authoritative location for each fact. An order item may copy the sale-time product price because it is a historical fact, not because the current product price was carelessly duplicated. That is deliberate snapshotting.

Denormalize only with a clear owner and repair story. A cached `orders.item_count` can speed a frequent read, but every item mutation must update it atomically, or an asynchronous projection must tolerate and repair lag. Ask:

1. Which representation is authoritative?
2. How is the duplicate updated?
3. What consistency lag is acceptable?
4. How will drift be detected and repaired?
5. Does the measured read benefit justify the write complexity?

JSONB is useful for sparse, evolving attributes that are read as a unit. It is not a substitute for relational modeling when fields need foreign keys, frequent filtering, independent updates, or stable semantics.

## Indexes are workload-specific data structures

An index trades storage and write cost for faster access paths. Every insert, update of indexed columns, and delete must maintain relevant indexes. Create indexes from observed query shapes, not from a rule such as "index every column."

PostgreSQL B-tree indexes suit equality, range, and ordered retrieval. Other useful types include GIN for containment and full-text patterns, GiST for operator-class-specific searches, and BRIN for very large physically correlated tables.

### Composite index order

For the earlier list query:

```sql
CREATE INDEX orders_tenant_status_created_id_idx
ON orders (tenant_id, status, created_at DESC, id DESC)
WHERE deleted_at IS NULL;
```

Equality columns generally come first, followed by range or ordering columns. This index can efficiently serve a predicate on `tenant_id` and `status` with the matching order. It is not a general replacement for an index whose leading key is `status`, because multicolumn B-tree usefulness depends heavily on the leftmost columns.

The `id` tie-breaker makes ordering deterministic and supports cursor pagination. The partial predicate keeps soft-deleted rows out of the index, but the query predicate must imply `deleted_at IS NULL` for the planner to use it. Partial indexes are especially valuable when the indexed subset is small and stable.

An included column can enable an index-only scan without changing key order:

```sql
CREATE INDEX orders_feed_idx
ON orders (tenant_id, created_at DESC, id DESC)
INCLUDE (status, total_amount)
WHERE deleted_at IS NULL;
```

Do not assume an index-only scan reads no heap pages. PostgreSQL visibility information and recently changed pages affect whether heap checks are required.

### Read the plan, not the index name

Use representative parameters and production-like data:

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT id, status, total_amount
FROM orders
WHERE tenant_id = '00000000-0000-0000-0000-000000000001'
  AND deleted_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT 50;
```

`ANALYZE` executes the statement. Use it carefully for mutations. Compare estimated and actual rows, loops, sort methods, buffer activity, and time at each node. Large estimate errors can come from stale statistics or correlated columns. A sequential scan is not inherently wrong; it is often cheapest for a large fraction of a small table.

Unused and duplicate indexes consume I/O. Review them with workload evidence and remember that statistics reset, replicas can have different read patterns, and a constraint may depend on an index.

## Transactions and ACID

A transaction is the unit that either commits or rolls back. ACID is a useful model:

- Atomicity: all effects in the transaction commit, or none do.
- Consistency: committed state satisfies enforced invariants. The application still has to define correct business transitions.
- Isolation: concurrent transactions interact according to the selected isolation level.
- Durability: a reported commit survives failures within the database's configured durability guarantees.

Transactions do not include arbitrary external HTTP calls. If a transaction commits and publishing a message fails, use a transactional outbox or another explicit coordination pattern rather than imagining both systems share one atomic commit.

Keep transactions short. Waiting for an API call or user input while holding a transaction increases lock duration, retains old row versions, and consumes a connection.

### PostgreSQL isolation levels

PostgreSQL defaults to `READ COMMITTED`. Each statement sees a snapshot as of that statement, so two reads in one transaction can observe different committed data. This is often appropriate, but a read-modify-write workflow still needs an atomic update, row lock, uniqueness constraint, or higher isolation.

`REPEATABLE READ` gives a stable transaction snapshot in PostgreSQL and can abort when concurrent updates make the requested outcome impossible. `SERIALIZABLE` aims for results equivalent to some serial execution and may raise serialization failures. The application must retry the entire transaction with bounded backoff. A retry that begins halfway through the business operation is not safe.

`READ UNCOMMITTED` behaves as `READ COMMITTED` in PostgreSQL. Know the behavior of the database in use rather than repeating only the SQL standard's anomaly table.

For a hot counter, avoid a separate read:

```sql
UPDATE inventory
SET available = available - $1
WHERE tenant_id = $2
  AND product_id = $3
  AND available >= $1
RETURNING available;
```

This is atomic. If no row is returned, stock is unavailable or the product is absent. For multi-row allocation, define a consistent lock order to reduce deadlocks, and retry a deadlock victim at the transaction boundary.

## Connection pooling and capacity

Opening a PostgreSQL connection has cost, so applications reuse connections through a pool. A pool does not make the database able to execute unlimited concurrent queries. Too many active connections can increase memory use and scheduling contention.

Budget the worst case:

```text
application_connections = replicas * worker_processes * (pool_size + max_overflow)
```

Then leave capacity for migrations, administration, workers, and failover. The exact useful pool size is a measured capacity decision, not a function of request count. Requests may wait briefly for a connection; that backpressure is safer than overwhelming the database. Set a finite pool checkout timeout so exhaustion becomes a visible failure rather than an indefinitely hung request.

Operational rules:

- Create an engine and its pool per process. Do not share live pooled connections across a process fork.
- Hold a connection only while doing database work. Do not perform slow network I/O inside the transaction.
- Close sessions on every path through a request dependency.
- Set statement and lock timeouts appropriate to the operation.
- Monitor checked-out connections, checkout wait, query latency, transaction age, blocked queries, and database saturation.
- Treat PgBouncer transaction pooling semantics carefully. Session-local state, prepared statements, temporary tables, and advisory locks can behave differently depending on versions and configuration.

An async driver allows the event loop to work on other requests while PostgreSQL is waiting. It does not make one connection execute multiple statements simultaneously, and it does not remove the database's connection limit.

## The N+1 query failure

N+1 occurs when one query loads N parent rows and later attribute access triggers one additional query per parent. It often hides behind ORM serialization:

```text
1 query:  load 100 orders
100 queries: load each order's customer or items
```

Fix it by selecting the required projection with a join, batch-loading related rows, or using a deliberate eager-loading strategy. Do not blindly join every collection. Joining multiple one-to-many collections can multiply result rows and memory use. Query-count assertions and SQL logging in integration tests catch regressions.

## Failure diagnosis

| Symptom | Likely questions |
| --- | --- |
| Pool timeout | Are sessions leaked? Are transactions waiting on locks? Is pool capacity multiplied by workers? |
| High database CPU | Which normalized queries dominate total time? Are plans scanning or sorting excessive rows? |
| Endpoint latency with low CPU | Is it waiting for pool checkout, a lock, storage I/O, or a downstream call? |
| Deadlocks | Do code paths lock the same rows in different orders? Is the full transaction retried? |
| Table/index bloat | Are long transactions preventing cleanup? Is autovacuum keeping up? |
| Sudden slow plan | Did cardinality or data distribution change? Are statistics current? Did a parameter-sensitive plan change? |
| Replica returns stale data | Does the endpoint require read-your-writes? Is replica lag measured and bounded? |

Collect the SQL shape, bind-safe diagnostics, plan, row counts, lock information, and timing before adding an index. Never log credentials or raw sensitive bind values.

## Testing database behavior

Unit tests cannot prove database constraints or isolation behavior. Use a real PostgreSQL instance of the supported major version for integration tests.

At minimum, test:

- duplicate concurrent inserts produce one success and one expected conflict;
- cross-tenant foreign keys are rejected;
- delete actions preserve or remove children according to the domain policy;
- transaction rollback leaves no partial write;
- serialization and deadlock retries rerun the entire idempotent unit of work;
- representative list queries stay within an agreed query-count and latency budget;
- migrations upgrade an older schema with realistic row counts.

Avoid making every test run inside one outer transaction if the behavior under test depends on commits, multiple connections, locks, or isolation. Those tests need separate sessions and explicit synchronization.

## Interview discussion

**Why put constraints in the database if Pydantic already validates input?**

Pydantic validates one request representation. The database receives writes from concurrent requests, workers, migrations, and administrative tools. Constraints are the final concurrency-safe authority for relational invariants. Application validation still provides earlier, clearer feedback.

**When is a composite index useful?**

When its ordered keys match a recurring predicate and order. Explain equality prefixes, range columns, sort order, selectivity, and write cost. A good answer includes verifying with `EXPLAIN (ANALYZE, BUFFERS)` on realistic data.

**Would you choose UUID or integer primary keys?**

Neither is universally correct. Integers are compact and locality-friendly. UUIDs support distributed generation and less guessable public identifiers at a storage cost. Authorization must never rely on an ID being difficult to guess.

**How do you prevent overselling inventory?**

Use an atomic conditional update or lock rows in a transaction, enforce nonnegative inventory, and make retry/idempotency behavior explicit. A read followed by an unconditional update is subject to lost updates.

**What does `SERIALIZABLE` cost?**

It simplifies reasoning about certain races but adds tracking, aborts, and mandatory whole-transaction retries. It does not make external side effects transactional. Contention and retry rates must be measured.

## Authoritative references

- [PostgreSQL: Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- [PostgreSQL: Indexes](https://www.postgresql.org/docs/current/indexes.html)
- [PostgreSQL: Multicolumn indexes](https://www.postgresql.org/docs/current/indexes-multicolumn.html)
- [PostgreSQL: Transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL: Explicit locking and deadlocks](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL: Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
- [PostgreSQL: Routine vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
