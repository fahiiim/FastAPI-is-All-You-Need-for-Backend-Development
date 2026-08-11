# Performance and Scalability

Performance engineering is the practice of finding the constrained resource, changing one relevant part of the system, and proving the result under representative load. Advice such as "make it async," "add Redis," or "increase workers" skips the diagnosis and can move the bottleneck into a more expensive place.

The objective is not minimum latency at any cost. Define a service-level objective, capacity target, correctness requirements, and cost envelope. Then optimize the paths that threaten them.

## Core measures

- **Latency**: elapsed time for an operation. Report percentiles such as p50, p95, p99, not only averages.
- **Throughput**: completed operations per unit time.
- **Concurrency**: operations in flight at the same time.
- **Utilization**: fraction of a resource's capacity in use.
- **Saturation**: queued work or inability to accept more work, such as pool waiters or event-loop lag.
- **Error rate**: failures and load shedding, which must be included when interpreting throughput.

An endpoint sustaining 5,000 requests per second by returning 503 is not healthy throughput. Likewise, a low average can conceal a damaging tail.

### Little's Law as a sanity check

For a stable system:

```text
average concurrency = throughput * average time in system
```

At 1,000 requests per second and 0.2 seconds average latency, about 200 requests are in flight. If latency rises to 2 seconds while arrival rate stays constant, concurrency grows toward 2,000. Those requests occupy memory, sockets, pool waiters, and proxy state. Latency is therefore also a capacity signal.

## Start with a latency budget

Break an endpoint target into components:

```text
Target p95                                 300 ms
  edge and load balancer                   20 ms
  application queue and middleware         15 ms
  authentication                           15 ms
  database                                 90 ms
  external provider                       100 ms
  serialization and response               20 ms
  contingency                              40 ms
```

Do not assign every downstream the full 300 ms. Parallel calls change the arithmetic, but they still consume connection and concurrency capacity. Retried calls must fit the remaining end-to-end deadline.

Measure both wall time and time waiting for pools, locks, queues, and the event loop. CPU can be low while every request waits for a ten-connection database pool.

## A repeatable diagnostic workflow

1. **Define the symptom**: which route, tenant class, payload, percentile, region, and time window?
2. **Confirm demand and errors**: did arrival rate, payload size, cache hit ratio, or response mix change?
3. **Locate waiting time** with traces and dependency metrics.
4. **Check saturation**: CPU throttling, memory pressure, event-loop lag, thread pool, connection pools, database locks, queue age, network, disk.
5. **Inspect work per request**: query count, rows scanned, bytes encoded, provider calls, retries, logs.
6. **Reproduce** with production-like data distribution and controlled load.
7. **Change one hypothesis** and compare a baseline using the same test.
8. **Verify correctness and cost**, then observe the canary in production.

Profiles, query plans, traces, and metrics complement one another. A profiler shows where a process spends CPU; it cannot explain time waiting inside a remote database unless that wait is also instrumented.

## Understand FastAPI's concurrency model

FastAPI runs on ASGI. `async def` routes execute on the event-loop thread and should yield control while waiting for async I/O. Normal `def` routes run in a thread pool so blocking code does not directly block the event loop.

### Correct asynchronous I/O

```python
import httpx
from fastapi import APIRouter

router = APIRouter()


@router.get("/exchange-rate/{currency}")
async def exchange_rate(currency: str, http: HttpClientDep) -> Rate:
    response = await http.get(f"rates/{currency}")
    response.raise_for_status()
    return Rate.model_validate(response.json())
```

The client must also be asynchronous. Declaring the route async does not transform blocking libraries.

### Blocking the event loop

```python
import requests


@router.get("/bad")
async def bad() -> dict[str, object]:
    # This blocks the event-loop thread and delays unrelated requests.
    return requests.get("https://example.com/data", timeout=3).json()
```

Options:

- use an async library;
- make the route `def` so FastAPI uses its thread pool;
- call a bounded blocking adapter through `asyncio.to_thread()` or the framework thread-pool helper;
- move long or CPU-heavy work to a process pool or task worker.

Thread offloading is not infinite capacity. Each blocked thread consumes memory and eventually queues callers. Bound concurrency around a blocking dependency.

### CPU-bound work

JSON transformation, image processing, compression, cryptography, PDF generation, and model inference can consume CPU without yielding. Multiple processes can use multiple cores; threads do not generally provide parallel Python bytecode execution under the usual CPython runtime.

Short CPU work may remain inline if measured. Long work should use a bounded process pool or a job system. A process pool inside every web replica can multiply processes and memory unexpectedly, especially for large models.

### Parallel I/O with structure and bounds

Independent calls can overlap:

```python
import asyncio


async def dashboard(user_id: str) -> Dashboard:
    async with asyncio.TaskGroup() as group:
        profile_task = group.create_task(profile_client.get(user_id))
        orders_task = group.create_task(order_client.list_recent(user_id))
    return Dashboard(profile=profile_task.result(), orders=orders_task.result())
```

Parallelism reduces critical-path latency only if downstream capacity exists. Ten calls per request at 500 concurrent requests can become 5,000 in-flight dependency calls. Use semaphores, connection limits, batch endpoints, and deadlines. Decide whether one child failure cancels the whole result or produces a partial response.

## Database performance usually dominates

### Reduce round trips and rows

- Fetch only required columns and rows.
- Eliminate N+1 loading with deliberate joins or eager loading.
- Batch inserts and updates where transaction semantics allow.
- Paginate large collections with stable ordering.
- Push filtering and aggregation into the database when it reduces data transfer without creating an unmaintainable query.
- Avoid holding a transaction open during third-party calls or user think time.

Counting queries in selected tests can detect N+1 regressions. The correct count is context-specific, so avoid a universal one-query rule.

### Use query plans

For a slow PostgreSQL query, capture the actual SQL and parameters safely, then use `EXPLAIN (ANALYZE, BUFFERS)` in a controlled environment. Examine:

- actual versus estimated row counts;
- sequential scans on large relations;
- index conditions and post-filtered rows;
- nested loops multiplying unexpected rows;
- sort/hash memory and disk spill;
- buffer hits and reads;
- lock waits and transaction contention.

`EXPLAIN ANALYZE` executes the statement. Use caution with mutations and production load. An index speeds some reads but costs storage, cache, and every relevant write. Design composite indexes around equality, range, ordering, and actual query shapes.

### Pagination

Large `OFFSET` values make the database walk and discard earlier rows and can produce duplicates or gaps as rows change. Keyset, or cursor, pagination uses the last ordered key:

```sql
SELECT id, created_at, total
FROM orders
WHERE tenant_id = :tenant_id
  AND (created_at, id) < (:cursor_created_at, :cursor_id)
ORDER BY created_at DESC, id DESC
LIMIT :page_size;
```

The `(created_at, id)` tie-breaker gives a total order and should match an index such as `(tenant_id, created_at DESC, id DESC)`. Offset pagination remains useful for small results and random page access where consistency is less important.

### Connection pool budgets

A pool reuses database connections and bounds concurrency. It is not a cache of unlimited capacity.

```text
potential application connections = replicas * workers * pool_size
                                  + replicas * workers * max_overflow
                                  + migration, worker, and operator connections
```

If 20 replicas each have 4 workers and pool size 10, the base pool budget is 800 connections. That may overwhelm PostgreSQL even though each local value looks small.

Set finite pool checkout timeouts and measure wait time. A larger pool can reduce waiting until database CPU, memory, locks, or I/O saturate, after which it often increases contention and tail latency. An external pooler can reduce server connection overhead, but transaction versus session pooling affects prepared statements and session features.

Also tune:

- connection lifetime/recycling around network and credential rotation;
- pre-ping or recovery behavior according to failure frequency;
- statement timeouts so abandoned work does not run indefinitely;
- transaction idle timeouts;
- separate pool budgets for API, workers, and administrative tasks.

## Caching as a measured optimization

Record cache hit ratio and, more importantly, **miss cost**. A 99 percent hit ratio can still overload the database if a hot key expires under enormous traffic. A 20 percent hit ratio may be valuable when the hits avoid the most expensive computation.

Measure:

- hit, miss, stale serve, bypass, and error;
- command and pool-wait latency;
- source load caused by misses;
- stampede concurrency;
- memory, key count, item size, evictions, and hot keys;
- stale data incidents and invalidation delay.

Cache final representations when safe to avoid both query and serialization cost. Include every representation dimension in the key and apply authorization before returning user-specific data.

## Serialization and validation

FastAPI response models protect the contract but validation and conversion consume CPU. Keep them unless measurement shows they materially threaten an objective; removing validation changes safety and documentation semantics.

Useful steps:

- return bounded result sets;
- select only fields in the response model;
- avoid repeatedly converting ORM objects through several dictionary layers;
- use Pydantic v2 `model_validate` and `model_dump` directly at clear boundaries;
- use `TypeAdapter` once and reuse it for repeated non-model validation;
- avoid wrap validators when a simpler constrained type or before/after validator works;
- benchmark an alternative JSON encoder with representative Unicode, decimals, datetimes, and error behavior before adopting it.

A faster serializer does not help an endpoint spending 95 percent of its time in SQL. Trace before changing global response behavior.

### Large and streaming responses

Building a 500 MB list consumes memory before the first byte is sent. Prefer pagination, an asynchronous export job, or streaming from a bounded source. Streaming keeps a worker and connection active, requires disconnect/cancellation handling, and can still create backpressure if the client reads slowly.

For file downloads, object storage and a short-lived signed URL usually scale better than proxying bytes through FastAPI.

## Compression

Compression reduces network bytes but consumes CPU and can delay small responses. Apply it at one well-understood layer, commonly the reverse proxy or CDN.

- Set a minimum response size.
- Do not recompress already compressed images, archives, and video.
- Add or respect `Vary: Accept-Encoding` in caches.
- Benchmark compression level and CPU under peak load.
- Consider security risks when secrets and attacker-controlled text share a compressed response context.
- Verify streaming and buffering behavior.

Brotli may compress text better than gzip but can cost more CPU depending on level and implementation. The right choice depends on payload and edge capabilities.

## Memory performance

Memory leaks and peaks lead to garbage-collection pauses, swapping, or out-of-memory kills.

Common sources:

- unbounded in-process caches and dictionaries;
- reading uploads or provider responses fully into bytes;
- retaining ORM sessions, responses, tasks, or trace objects;
- high-cardinality metrics;
- queues with no maximum;
- one large model or lookup table copied into every worker;
- accumulating background tasks disconnected from ownership.

Track resident memory per process, allocation rate, garbage-collection time, item sizes, and memory per request under load. Use allocation profilers such as `tracemalloc` or production-appropriate sampling tools. Recycling workers can limit impact while investigating, but it is containment, not a repair.

## Network and protocol costs

- Reuse HTTP and database connections.
- Keep DNS behavior and TTLs appropriate for service discovery.
- Batch small downstream operations when APIs support it.
- Put static and globally cacheable data at a CDN.
- Bound request headers and bodies before expensive parsing.
- Avoid chatty service boundaries with many sequential calls.
- Evaluate HTTP/2 where multiplexing and infrastructure support help, but measure end-to-end.

Timeouts, retries, TLS, proxies, and load balancers affect performance. A fast local benchmark that bypasses them is not a production capacity result.

## Load testing

A valid load test models demand rather than simply opening as many connections as possible.

Define:

- endpoint and payload distribution;
- authenticated identities and tenant skew;
- cache warm or cold state;
- database size and index selectivity;
- arrival-rate or closed-loop user model;
- ramp-up, steady duration, and cool-down;
- pass/fail thresholds for latency, errors, saturation, and correctness;
- environment differences from production.

### Example with Locust

```python
import os

from locust import HttpUser, between, task


class Shopper(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        self.client.headers["Authorization"] = f"Bearer {os.environ['LOAD_TEST_TOKEN']}"

    @task(8)
    def list_products(self) -> None:
        with self.client.get(
            "/v1/products?limit=20",
            name="GET /v1/products",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")

    @task(1)
    def create_cart(self) -> None:
        self.client.post(
            "/v1/carts",
            json={"items": [{"sku": "SKU-42", "quantity": 1}]},
            name="POST /v1/carts",
        )
```

Avoid placing a real shared token in source or logs. Generate synthetic test identities.

### Test types

- **Baseline**: one or few users, verifies script and minimum latency.
- **Load**: expected peak for long enough to reach steady state.
- **Stress**: increase until an objective fails, identifying bottleneck and degradation.
- **Spike**: sudden traffic jump and recovery.
- **Soak**: sustained load to reveal leaks, fragmentation, pool erosion, and slow queues.
- **Capacity regression**: repeatable benchmark comparing releases.

Run load generators outside the service host. Monitor every tier during the test. Coordinate dangerous production tests with operators, limit scope, and use test data.

### Coordinated omission

Closed-loop load generators wait for a response before sending the next request, so a slow service reduces offered load and can under-report latency during stalls. Arrival-rate tests preserve the intended arrival pattern and reveal queuing. Understand the tool's model and corrected latency reporting.

## Profiling tools and evidence

| Question | Evidence |
|---|---|
| Where does Python spend CPU? | Sampling CPU profiler, flame graph |
| What allocates memory? | Allocation profiler, heap snapshots, `tracemalloc` |
| Which dependency dominates latency? | Distributed trace spans and client metrics |
| Why is SQL slow? | Query statistics, lock views, `EXPLAIN (ANALYZE, BUFFERS)` |
| Is async code blocked? | Event-loop lag, slow callback diagnostics, stack samples |
| Is the pool too small or dependency too slow? | Pool checkout wait, in-use count, dependency latency |
| Is serialization material? | Span/timer around validation and encoding, CPU profile |
| Why did tail latency jump? | Correlate p99 with saturation, GC, retries, deploys, and traffic mix |

Profile representative optimized builds. Profiling overhead can change timing, so use sampling and controlled duration in production.

## Scaling patterns

### Vertical scaling

Give a process or host more CPU, memory, faster storage, or network. It is simple and useful, but has a ceiling and can increase failure impact.

### Horizontal scaling

Add replicas behind a load balancer. Request handlers should avoid process-local correctness state. Shared databases, caches, quotas, WebSocket routing, file storage, and schedulers must support the new topology.

Horizontal application scaling helps only if the bottleneck is the application tier. If the database is at 95 percent CPU, adding API replicas may increase query concurrency and make it worse.

### Read replicas and partitioning

Database read replicas can serve stale-tolerant reads, analytics, or failover depending on configuration. Read-after-write routing and replication lag must be explicit. Sharding partitions data and write load but adds routing, cross-shard query, rebalancing, transaction, and operational complexity. Exhaust schema, query, index, cache, and hardware improvements first unless scale or isolation clearly demands it.

### Workload separation

Separate resources for:

- interactive API versus batch workers;
- short versus long jobs;
- transactional queries versus analytics;
- public traffic versus administrative operations;
- inexpensive requests versus AI/GPU inference.

Bulkheads prevent one workload from occupying all pools. They also make cost and objectives easier to attribute.

## Overload behavior

A scalable service does not accept unbounded work. It sheds load before queues consume all memory and timeouts synchronize.

Controls include:

- edge and identity-aware rate limits;
- maximum request body and concurrency;
- bounded server backlog and pool waits;
- queue admission limits and job quotas;
- deadlines propagated downstream;
- circuit breakers and retry budgets;
- priority with reserved capacity for critical operations;
- 429 or 503 responses with meaningful retry guidance.

Failing quickly under unavoidable overload often preserves more useful throughput than letting every request time out.

## Performance review checklist

- Each critical operation has latency, throughput, error, and capacity objectives.
- Dashboards show percentiles and saturation, not only averages and CPU.
- Async routes contain no unbounded blocking work.
- Database queries, row counts, plans, transactions, and pool waits have been measured.
- Pool sizes are budgeted across all replicas and workers.
- Cache policy includes miss amplification and outage behavior.
- Payload size, pagination, serialization, streaming, and compression are intentional.
- Load tests model traffic mix, data size, identity skew, and arrival behavior.
- Changes compare against a controlled baseline and include correctness checks.
- Overload is bounded and produces deliberate responses rather than collapse.

## Interview prompts

1. An API's application CPU is 20 percent but latency tripled. What would you inspect next?
2. Why can increasing a database connection pool make p99 latency worse?
3. When does `async def` improve throughput, and when can it damage it?
4. Explain Little's Law in the context of a slow endpoint.
5. How would you prove an N+1 query regression?
6. Compare offset and cursor pagination under concurrent writes.
7. What is coordinated omission in a load test?
8. Why might adding API replicas worsen a database bottleneck?
9. How would you separate interactive requests from long AI inference work?

## Further reading

- [Python: asyncio](https://docs.python.org/3/library/asyncio.html)
- [FastAPI: Concurrency and async/await](https://fastapi.tiangolo.com/async/)
- [SQLAlchemy Connection Pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)
- [PostgreSQL: Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
- [Pydantic Performance](https://docs.pydantic.dev/latest/concepts/performance/)
- [Uvicorn Resource Limits](https://www.uvicorn.org/settings/#resource-limits)
- [Locust Documentation](https://docs.locust.io/)

## Related topics

- [Caching, Redis, and Rate Limiting](./caching-redis-and-rate-limiting.md)
- [Observability](./observability.md)
- [Production Architecture](../../architecture/production-architecture.md)
