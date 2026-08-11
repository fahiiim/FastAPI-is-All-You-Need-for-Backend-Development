# Querying, Pagination, and Database Performance

A list endpoint is a query contract, not a thin wrapper around `SELECT *`. Its filters, sort order, page model, authorization scope, and response fields determine index design and worst-case cost. Production APIs make that contract finite and observable.

This chapter uses an order feed as the running example. Every query is tenant-scoped before client filters are considered.

## Design the query surface

A useful contract states:

- which fields can be filtered;
- whether repeated values mean OR or AND;
- which sort fields and directions are allowed;
- how nulls and case are treated;
- maximum list sizes, date ranges, page sizes, and offsets;
- whether totals are exact, approximate, or omitted;
- how invalid and expired cursors are reported;
- which consistency behavior clients can expect while rows change.

Do not expose a generic client-to-SQL expression language unless the product truly needs one and the team can secure and operate it. A narrow API is easier to index, document, test, and evolve.

## Typed query parameters

FastAPI can bind a Pydantic model from query parameters. Use enums and bounds so invalid work is rejected before reaching the database.

```python
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class OrderSort(StrEnum):
    CREATED_AT = "created_at"
    TOTAL_AMOUNT = "total_amount"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class OrderListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: list[OrderStatus] = Field(default_factory=list, max_length=5)
    customer_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    search: str | None = Field(default=None, min_length=2, max_length=100)
    sort: OrderSort = OrderSort.CREATED_AT
    direction: SortDirection = SortDirection.DESC
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)

    @field_validator("status")
    @classmethod
    def statuses_are_unique(
        cls, values: list[OrderStatus]
    ) -> list[OrderStatus]:
        if len(values) != len(set(values)):
            raise ValueError("status values must be unique")
        return values


@router.get("")
async def list_orders(
    query: Annotated[OrderListQuery, Query()],
    principal: Annotated[Principal, Depends(require_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderPage:
    return await order_queries.list_orders(session, principal.tenant_id, query)
```

FastAPI and Pydantic version compatibility for query-parameter models should be verified in the project's dependency lock. An alternative is a dependency function with individual `Query` parameters.

Date-time inputs should include an offset. Normalize instants to UTC for storage and comparison. Define whether `created_to` is inclusive; half-open ranges such as `[created_from, created_to)` compose cleanly.

## Build SQL from allowlisted structure

Values become bound parameters. Identifiers and SQL direction are chosen from trusted code, never concatenated from input.

```python
from sqlalchemy import Select, select
from sqlalchemy.orm.attributes import InstrumentedAttribute

SORT_COLUMNS: dict[OrderSort, InstrumentedAttribute[object]] = {
    OrderSort.CREATED_AT: Order.created_at,
    OrderSort.TOTAL_AMOUNT: Order.total_amount,
}


def build_order_statement(
    tenant_id: UUID,
    query: OrderListQuery,
) -> Select[tuple[Order]]:
    stmt = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.deleted_at.is_(None),
    )

    if query.status:
        stmt = stmt.where(Order.status.in_(query.status))
    if query.customer_id is not None:
        stmt = stmt.where(Order.customer_id == query.customer_id)
    if query.created_from is not None:
        stmt = stmt.where(Order.created_at >= query.created_from)
    if query.created_to is not None:
        stmt = stmt.where(Order.created_at < query.created_to)

    sort_column = SORT_COLUMNS[query.sort]
    ordered = sort_column.asc() if query.direction == SortDirection.ASC else sort_column.desc()

    return stmt.order_by(ordered, Order.id.asc()).limit(query.limit).offset(query.offset)
```

The unique `id` tie-breaker makes the order deterministic. For descending primary sort, using an ascending tie-breaker is valid if deliberate, but the matching index and cursor comparison become mixed-direction. Many teams use the same direction for both keys to simplify keyset pagination.

Never implement sorting with `getattr(Order, user_input)` without an allowlist. It exposes columns unintentionally and makes the supported query workload unbounded. Never put a raw client string into `text()`, `literal_column()`, or an f-string.

### Filter semantics and indexes

An index should match important filter combinations, not every optional field. For example:

```sql
CREATE INDEX orders_tenant_status_created_id_idx
ON orders (tenant_id, status, created_at DESC, id DESC)
WHERE deleted_at IS NULL;
```

This supports a tenant and status feed ordered by creation time. A query without `status` may use it less effectively because the order no longer follows directly after the tenant key. If both shapes dominate traffic, separate indexes may be justified.

Large `IN` lists increase parsing, planning, and execution cost. Cap them. If a client genuinely needs thousands of IDs, consider a temporary relation, array join, import job, or purpose-built batch endpoint.

Optional filters create many possible query shapes. Observe normalized statement statistics such as `pg_stat_statements`, then optimize the shapes responsible for material load. An index that saves a rare query but taxes every write is a poor trade.

## Search is not one feature

"Search" can mean exact identity, prefix lookup, substring match, word search, fuzzy similarity, or a specialist relevance engine. Define the behavior before selecting a data structure.

### Exact and prefix matching

Normalize identity fields consistently. For a user-entered prefix:

```python
def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

pattern = f"{escape_like(query.search)}%"
stmt = stmt.where(Customer.normalized_name.ilike(pattern, escape="\\"))
```

Escaping `%` and `_` prevents them from acting as unintended wildcards. Bound parameters already prevent SQL injection; wildcard escaping defines the intended search semantics. A leading wildcard such as `%term%` generally cannot use an ordinary B-tree prefix access path.

### PostgreSQL full-text search

PostgreSQL full-text search tokenizes documents and queries and can rank matches. Keep configuration consistent between the indexed vector and query.

```sql
CREATE INDEX products_search_vector_idx
ON products USING gin (
    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
);

SELECT id, name
FROM products
WHERE tenant_id = $1
  AND to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))
      @@ websearch_to_tsquery('english', $2)
ORDER BY created_at DESC, id DESC
LIMIT $3;
```

For frequent writes or more complex weighting, a stored generated vector can make the expression and index contract clearer. Language configuration, stemming, ranking, and tenant selectivity must be tested with the real corpus.

The `pg_trgm` extension supports indexed similarity and substring-like searches. It adds storage and write cost. For complex typo tolerance, cross-field relevance, facets, or a very large search workload, a search service may be appropriate, but then indexing lag and source-of-truth behavior become part of the API contract.

## Offset pagination

Offset pagination maps naturally to page numbers:

```sql
SELECT id, status, created_at
FROM orders
WHERE tenant_id = $1
ORDER BY created_at DESC, id DESC
LIMIT 50 OFFSET 5000;
```

It is suitable for small administrative datasets, shallow navigation, and interfaces that require jumping to a known page. Its costs are:

- the database generally still walks or processes skipped rows;
- latency grows with deep offsets;
- inserts and deletes before the offset can cause duplicates or omissions between requests;
- an exact `count(*)` can be more expensive than the page query.

Cap both `limit` and `offset`. If the product demands page 10,000 plus an exact total across complex filters, treat that as a reporting requirement rather than pretending it is a cheap transactional query.

### Exact totals are optional work

An endpoint can return one of:

- an exact total from a separate count query;
- `has_next` from fetching `limit + 1` rows;
- an approximate count clearly labeled as such;
- no total.

Do not embed `count(*) over()` by reflex. A window count can force processing the whole matched set even when only 50 rows are returned. Measure the actual plan.

## Cursor and keyset pagination

Keyset pagination resumes after the last sort key rather than skipping an offset. With a fixed descending order:

```sql
SELECT id, status, created_at
FROM orders
WHERE tenant_id = $1
  AND deleted_at IS NULL
  AND (created_at, id) < ($2, $3)
ORDER BY created_at DESC, id DESC
LIMIT 51;
```

The matching index begins `(tenant_id, created_at DESC, id DESC)` for this query shape. `created_at` and `id` must be non-null. The unique tie-breaker prevents rows with identical timestamps from disappearing between pages.

Fetch `limit + 1`, return at most `limit`, and create the next cursor from the last returned row only if an extra row exists.

### An opaque signed cursor

A cursor should include its version, sort values, and a fingerprint of filters that affect the result. Signing detects tampering. Base64 is encoding, not encryption, so do not place secrets in the payload.

```python
import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID


class InvalidCursorError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrderCursor:
    version: int
    created_at: str
    order_id: str
    query_hash: str


def encode_cursor(cursor: OrderCursor, signing_key: bytes) -> str:
    payload = json.dumps(
        asdict(cursor), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    signature = hmac.digest(signing_key, payload, "sha256")
    return base64.urlsafe_b64encode(payload + signature).decode("ascii").rstrip("=")


def decode_cursor(value: str, signing_key: bytes) -> OrderCursor:
    if len(value) > 2048:
        raise InvalidCursorError("cursor is too large")

    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        if len(raw) <= 32:
            raise ValueError("missing payload")
        payload, signature = raw[:-32], raw[-32:]
        expected = hmac.digest(signing_key, payload, "sha256")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")

        data = json.loads(payload)
        cursor = OrderCursor(**data)
        if cursor.version != 1:
            raise ValueError("unsupported version")
        datetime.fromisoformat(cursor.created_at)
        UUID(cursor.order_id)
        return cursor
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc


def query_fingerprint(tenant_id: UUID, normalized_filters: dict[str, object]) -> str:
    material = json.dumps(
        {"tenant_id": str(tenant_id), "filters": normalized_filters},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
```

Use a dedicated secret from a secrets manager and support key rotation, for example by including a non-secret key identifier. Compare `query_hash` with the current principal and normalized filters so a cursor cannot be replayed for another tenant or query. A cursor may contain a server-side token instead when the payload must be confidential or revocable.

### SQLAlchemy keyset query

```python
from sqlalchemy import select, tuple_


async def fetch_order_page(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    limit: int,
    cursor: OrderCursor | None,
) -> tuple[list[Order], bool]:
    stmt = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.deleted_at.is_(None),
    )

    if cursor is not None:
        cursor_time = datetime.fromisoformat(cursor.created_at)
        cursor_id = UUID(cursor.order_id)
        stmt = stmt.where(
            tuple_(Order.created_at, Order.id) < (cursor_time, cursor_id)
        )

    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
    rows = (await session.scalars(stmt)).all()
    return rows[:limit], len(rows) > limit
```

Row-value comparison is concise and supported by PostgreSQL. For mixed sort directions or nullable fields, write the lexicographic predicate explicitly and define null placement. A pagination library can help, but its generated predicate and index requirements still need review.

Keyset pagination avoids deep-skip cost, but it does not create a frozen snapshot. New rows before the cursor do not disturb later pages. Deleting unseen rows removes them, and updating sort keys can make a row appear twice or not at all. If an export requires a consistent snapshot, run a bounded snapshot workflow or create an asynchronous export artifact instead of keeping an HTTP transaction open indefinitely.

## Query performance workflow

Optimization begins with a measured user-facing problem.

1. Establish latency percentiles, throughput, errors, and the affected endpoint or job.
2. Separate pool checkout, database execution, lock wait, result transfer, ORM work, serialization, and downstream time.
3. Identify normalized high-total-time SQL using database statistics and tracing.
4. Run `EXPLAIN (ANALYZE, BUFFERS)` with representative values in a safe environment.
5. Compare estimated and actual rows, loops, rows removed, sorts, and buffer activity.
6. Change one constraint, query, index, or data-access pattern.
7. Re-measure query and write-path impact.

A plan from an empty development database is weak evidence. Cardinality, distribution, cache state, and parameter values matter.

### Reduce work before adding infrastructure

Common high-value fixes are:

- select only response fields rather than full wide entities;
- eliminate N+1 queries with projections or deliberate relationship loaders;
- filter and aggregate in SQL rather than Python;
- make predicates sargable, meaning usable by an appropriate index;
- remove unnecessary joins and exact counts;
- add a composite or partial index matching a dominant query shape;
- replace deep offset with keyset pagination;
- batch independent writes where semantics allow;
- shorten transactions and resolve lock contention.

Async I/O, more web workers, and Redis do not repair a bad query plan. They may increase the rate at which the application sends bad work to PostgreSQL.

### Bound every expensive dimension

Apply limits to:

- page size and offset;
- number of filter values;
- search length and syntax;
- export range and row count;
- statement and lock time;
- connection pool wait;
- response size;
- concurrent exports per tenant.

Large exports should normally be background jobs that write an artifact to object storage. Give them workload isolation so they do not monopolize the transactional pool.

### N+1 and response serialization

The query is not finished when `session.execute()` returns. ORM relationship access and response-model conversion can emit more SQL or spend significant CPU. Trace through serialization and assert query counts. `selectinload` often suits bounded collections; a projection is better when only a few related fields are needed.

### Pool pressure

Pool checkout time is separate from query execution time. A five-millisecond query can still sit behind long transactions for seconds. Monitor active and waiting database sessions, transaction age, lock waits, and application pool metrics. Increasing the pool without database headroom can worsen total latency.

## Error behavior

Return stable client errors:

- `422 Unprocessable Content` for invalid typed filters or bounds, following the application's validation convention;
- `400 Bad Request` or `422` consistently for a malformed cursor;
- `403 Forbidden` only if the authorization disclosure policy allows it;
- a non-revealing `404 Not Found` for tenant-scoped resources when appropriate;
- `503 Service Unavailable` for controlled capacity rejection if retry is sensible.

Do not reveal raw SQL, constraint details, query plans, table names, or signed cursor verification reasons to clients. Log a safe diagnostic with request and query identifiers.

## Testing list endpoints

Seed data specifically designed to break naive pagination:

- many rows with the same timestamp;
- rows immediately before and after filter boundaries;
- mixed tenants with overlapping IDs and values;
- deleted rows and nullable optional filters;
- strings containing `%`, `_`, backslashes, quotes, and non-ASCII text;
- enough rows to exercise page boundaries.

Tests should verify:

- deterministic ordering and no duplicates across an unchanged dataset;
- tenant scope cannot be changed by filters or a replayed cursor;
- cursor encode/decode round trips and tampering fails;
- cursor query fingerprints reject changed filters;
- page size, offset, filter-list, and cursor-size caps;
- invalid sort fields never become SQL identifiers;
- concurrent insert/delete/update behavior matches the documented contract;
- exact totals, if offered, use the same authorization and filters;
- query count and representative plans stay within a budget.

Property-based tests are valuable for cursor codecs and lexicographic page traversal. Integration tests must use PostgreSQL when they rely on tuple comparison, full-text search, trigram indexes, or PostgreSQL plans.

## Interview discussion

**Offset or cursor pagination?**

Offset is simple and supports page numbers, but deep pages become expensive and concurrent changes shift results. Cursor pagination gives stable forward traversal and index-friendly seeks, but it complicates arbitrary jumps, nullable/mixed sorts, and cursor versioning. Choose from product behavior and workload.

**Why must ordering include a unique tie-breaker?**

Without one, rows sharing the visible sort value have no deterministic relative order. A cursor containing only that value can skip or repeat them.

**Why might an index not be used?**

The query reads a large fraction of the table, the leading index columns do not match, a function or cast prevents the access path, statistics are inaccurate, the partial-index predicate is not implied, or the planner correctly estimates a scan is cheaper. Inspect the actual plan.

**How would you diagnose a slow list endpoint?**

Break latency into pool, database, lock, transfer, ORM, and serialization time. Find the real statement and values, inspect its plan and row estimates on representative data, check N+1 and response size, then change and measure one cause.

**Would you always return an exact count?**

No. Exact counts can dominate latency for broad or joined filters. Many feeds need only `has_next`; reporting workflows can compute totals separately.

## Authoritative references

- [PostgreSQL: Using `EXPLAIN`](https://www.postgresql.org/docs/current/using-explain.html)
- [PostgreSQL: Multicolumn indexes](https://www.postgresql.org/docs/current/indexes-multicolumn.html)
- [PostgreSQL: Partial indexes](https://www.postgresql.org/docs/current/indexes-partial.html)
- [PostgreSQL: Full-text search](https://www.postgresql.org/docs/current/textsearch.html)
- [PostgreSQL: `pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html)
- [PostgreSQL: `pg_stat_statements`](https://www.postgresql.org/docs/current/pgstatstatements.html)
- [SQLAlchemy ORM querying guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/)
- [FastAPI query parameter models](https://fastapi.tiangolo.com/tutorial/query-param-models/)
