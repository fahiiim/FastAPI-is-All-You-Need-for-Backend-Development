# Decision Guide: Persistence and Service Architecture

Choose PostgreSQL, repositories, modules, and service boundaries for their guarantees and change patterns. None is a senior-engineering decoration.

## When PostgreSQL is a strong default

PostgreSQL fits systems that need transactions, constraints, relational queries, secondary indexes, and durable operational data. It handles far more than simple CRUD and often remains the right source of truth after caches, search indexes, and queues are added.

Choose it when:

- data relationships and integrity matter;
- several records change atomically;
- filters and reporting will evolve;
- uniqueness must hold under concurrency;
- the team can operate backups, migrations, and connection pools.

Another store may be better for a dominant specialized workload, but define what PostgreSQL cannot meet. Do not replace transactions with application code because a different database looks simpler in a demo.

## Offset or cursor pagination

Use offset pagination for small, stable result sets where arbitrary page numbers matter and the database can afford walking the offset. It is simple for administrative screens.

Use cursor pagination for large or frequently changing feeds. The cursor encodes the last ordering tuple, such as `(created_at, id)`, and the query seeks after it through a matching index. It avoids skipped or duplicated positions caused by inserts before an offset.

Cursor pagination requires:

- deterministic ordering with a unique tie-breaker;
- a versioned opaque cursor;
- filters bound into or validated against the cursor;
- a clear forward and reverse navigation contract;
- an index whose leading columns match filters and ordering.

## Should I add a repository?

Add a repository when it provides a meaningful persistence boundary:

- the domain speaks in operations such as `reserve_inventory`;
- queries have reusable loading, tenant, or lock rules;
- application tests benefit from a port with a realistic fake;
- persistence mappings should not escape into policy code;
- several adapters implement the same application need.

Skip it when every method merely renames `session.get`, `session.add`, and `select`. SQLAlchemy already supplies a unit-of-work and identity-map abstraction. A generic repository can hide the query features needed for performance.

Repositories do not own authorization or commit secretly. One application use case should control the transaction.

## Service layer decision

Create an application service or use-case function when an operation:

- combines repositories or integrations;
- applies business policy;
- defines a transaction;
- is called from HTTP and workers;
- has enough behavior to test without transport details.

A one-line route can call a query object or repository directly if no business workflow exists. A pass-through class that duplicates every router method adds no boundary.

## Layered or modular

Organize a small codebase with simple layers. Move toward feature modules when changes cluster by business capability and horizontal folders become catalogs of unrelated files.

```text
# Horizontal layers
routers/orders.py
services/orders.py
repositories/orders.py

# Feature module
orders/router.py
orders/service.py
orders/repository.py
orders/schemas.py
```

Feature modules improve ownership and make dependencies between capabilities visible. Shared code should be deliberately small; a `common/` directory often becomes a hidden coupling mechanism.

## Modular monolith or microservices

Start with a modular monolith unless a process boundary solves a demonstrated organizational or runtime problem.

Split a service when a stable capability needs:

- independent release and ownership;
- security or compliance isolation;
- a different availability or scaling profile;
- a technology/runtime boundary justified by the workload;
- failure isolation that cannot be achieved in one deployment.

Before splitting, require an answer for service identity, network timeouts, retries, tracing, schema compatibility, event delivery, data ownership, local development, and incident response.

Do not split only because the codebase is large. A distributed monolith has synchronous call chains, shared databases, coordinated releases, and all the network failure modes of services.

## Clean or hexagonal architecture

Use dependency inversion around volatile or expensive boundaries: payment providers, model providers, message brokers, complex persistence, and important domain policy. Keep simple framework code simple.

The cost is mapping and composition. The benefit is not that every technology becomes replaceable overnight. It is that policy can be tested and understood without booting those technologies.

## Decision record template

Record decisions that will be costly to reverse:

```markdown
# ADR: Use cursor pagination for the activity feed

## Context
Feed rows grow rapidly, new rows arrive continuously, and clients scroll forward.

## Decision
Order by `(occurred_at DESC, id DESC)` and expose an opaque versioned cursor.

## Consequences
Stable forward traversal and index-backed seeks. No direct page numbers. Filters are
bound to the cursor and a new index is required.

## Revisit when
Product requires random page access or the dominant ordering changes.
```

## Interview answer

**When should I use microservices?**

Use them around stable business boundaries when independent ownership, release, isolation, or scaling is worth distributed transactions, network failure handling, observability, and operational duplication. I would first enforce the boundary in a modular monolith. Extraction should follow measured coupling and ownership, not precede them.

## Related material

- [Backend project structure](../backend-project-structure.md)
- [Relational databases](../docs/02-data/relational-databases.md)
- [Querying and pagination](../docs/02-data/querying-pagination-and-performance.md)
- [Architecture patterns](../architecture/architecture-patterns.md)

[Back to documentation map](../README.md)
