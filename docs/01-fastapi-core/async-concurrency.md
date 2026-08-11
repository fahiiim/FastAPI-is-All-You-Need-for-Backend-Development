# Async, Concurrency, and Work Placement

Asynchronous code helps a worker use waiting time to serve other work. It does not make a database faster, add CPU cores, remove connection limits, or make blocking libraries non-blocking. The engineering question is not "Should this API be async?" It is "Where does each operation wait or compute, and which finite resource bounds it?"

## 1. Vocabulary

- **Sequential execution**: one operation completes before the next begins in that control flow.
- **Concurrency**: multiple operations are in progress during overlapping time.
- **Parallelism**: operations execute at the same instant on different cores or machines.
- **Coroutine**: a function invocation that can suspend and resume. Calling an `async def` function returns a coroutine object.
- **Task**: a scheduled coroutine managed by an event loop.
- **Event loop**: a scheduler that runs ready callbacks and tasks, then waits for I/O readiness and timers.
- **Blocking operation**: code that prevents its execution thread from doing other work until it completes.
- **I/O-bound work**: time is dominated by waiting for network, disk, database, or another service.
- **CPU-bound work**: time is dominated by computation.

Concurrency is a property of the design. `async` is one mechanism for implementing it.

## 2. How an event loop uses one thread

An event loop runs one ready task until that task:

- Awaits an incomplete asynchronous operation.
- Returns.
- Raises.
- Is preempted only by code that explicitly yields through an awaitable.

While one task waits for a socket, another task can run. If a task performs a blocking call or a long CPU loop, it does not yield, and unrelated requests on that event loop wait.

```python
import asyncio


async def fetch_pair() -> tuple[str, str]:
    first, second = await asyncio.gather(
        fetch_text("https://one.example"),
        fetch_text("https://two.example"),
    )
    return first, second
```

The calls can overlap because each properly awaits non-blocking network I/O. They are not necessarily running Python instructions in parallel.

## 3. Coroutines do nothing until awaited or scheduled

```python
async def load_order(order_id: str) -> Order:
    return await repository.get(order_id)


coroutine = load_order("o_123")
# No order has been loaded yet.
order = await coroutine
```

A common mistake is forgetting `await`, then trying to serialize or access a coroutine object. Static checking and tests catch many of these failures.

Creating a task schedules it independently within the current loop:

```python
task = asyncio.create_task(refresh_cache())
result = await task
```

Do not create a task and discard the reference for important work. It can fail without a useful owner, be cancelled at shutdown, or disappear with the process. Structured concurrency or a durable worker is usually better.

## 4. FastAPI endpoint execution

FastAPI supports both declaration styles:

```python
@app.get("/async-orders/{order_id}")
async def async_order(order_id: str) -> OrderView:
    return await async_repository.get(order_id)


@app.get("/sync-orders/{order_id}")
def sync_order(order_id: str) -> OrderView:
    return sync_repository.get(order_id)
```

- `async def` path operations run on the event-loop thread. Use them when the request path uses awaitable libraries and can avoid blocking.
- Normal `def` path operations run through a thread pool. Use them for synchronous libraries when replacement or explicit adaptation is not warranted.

The same principle applies to dependencies. A synchronous dependency is offloaded; an asynchronous dependency runs on the event loop.

Tiny pure helper functions do not need to become sync dependencies merely to obtain a thread. Calling a plain helper from an async route runs it inline, which is correct when it is quick.

## 5. Incorrect async code

### Blocking sleep

```python
import time


@app.get("/wrong")
async def wrong() -> dict[str, str]:
    time.sleep(2)  # Stops this event-loop thread.
    return {"status": "done"}
```

Use an asynchronous timer:

```python
import asyncio


@app.get("/cooperative")
async def cooperative() -> dict[str, str]:
    await asyncio.sleep(2)
    return {"status": "done"}
```

Sleeping in an API is rarely useful, but the example exposes the scheduling difference.

### Synchronous HTTP client inside an async endpoint

```python
import requests


@app.get("/wrong-provider-call")
async def wrong_provider_call() -> dict[str, object]:
    response = requests.get("https://provider.example/data", timeout=5)
    return response.json()
```

Use a lifespan-managed asynchronous client:

```python
from fastapi import Request
from httpx import AsyncClient, Timeout


@app.get("/provider-call")
async def provider_call(request: Request) -> dict[str, object]:
    client: AsyncClient = request.app.state.provider_client
    response = await client.get(
        "/data",
        timeout=Timeout(5.0, connect=1.0),
    )
    response.raise_for_status()
    return response.json()
```

Client construction belongs in lifespan so connections are reused. Set explicit timeouts and limits. An async client can still overwhelm a provider if concurrency is unbounded.

### CPU loop inside the event loop

```python
from typing import Annotated

from fastapi import Body


@app.post("/wrong-hash")
async def wrong_hash(
    payload: Annotated[
        bytes,
        Body(max_length=1024 * 1024, media_type="application/octet-stream"),
    ],
) -> dict[str, str]:
    digest = expensive_python_hash(payload)  # No await point while computing.
    return {"digest": digest}
```

Move substantial CPU work to a process pool or, for durable and heavy jobs, an external worker system.

## 6. I/O-bound work

Async helps when the full call chain offers non-blocking APIs:

- Async database driver through SQLAlchemy's async APIs.
- Async HTTP client.
- Async Redis client.
- ASGI request and response streaming.
- Timers and sockets exposed as awaitables.

An async wrapper around a sync driver does not necessarily make it non-blocking. Inspect the library's implementation and integration guidance.

### Sequential versus concurrent I/O

Sequential calls preserve order and reduce downstream pressure:

```python
profile = await users_client.get_profile(user_id)
permissions = await policy_client.get_permissions(user_id)
```

Concurrent calls reduce combined latency when they are independent:

```python
async with asyncio.TaskGroup() as group:
    profile_task = group.create_task(users_client.get_profile(user_id))
    permissions_task = group.create_task(policy_client.get_permissions(user_id))

profile = profile_task.result()
permissions = permissions_task.result()
```

Concurrency is not automatically correct. Ask:

- Are calls independent?
- Does one result determine whether the other is allowed?
- What happens if one fails and the other causes a side effect?
- Can the provider, pool, and tenant budget handle both?
- Is total deadline propagated?

`TaskGroup` provides structured concurrency: leaving the block waits for its tasks, and a non-cancellation failure cancels sibling tasks and groups errors. Understand those semantics before using it around side effects.

## 7. Timeouts and deadlines

Every network or pool wait needs a finite budget. A timeout on the outer request is not enough if inner calls continue consuming resources.

```python
import asyncio


async def load_dashboard(user_id: str) -> Dashboard:
    try:
        async with asyncio.timeout(2.0):
            async with asyncio.TaskGroup() as group:
                orders_task = group.create_task(load_orders(user_id))
                balance_task = group.create_task(load_balance(user_id))
        return Dashboard(
            orders=orders_task.result(),
            balance=balance_task.result(),
        )
    except TimeoutError as exc:
        raise DashboardUnavailable("dashboard deadline exceeded") from exc
```

Prefer a request deadline over unrelated per-call timeouts. Each downstream call should use the remaining budget, leaving time for cleanup and an error response. A retry consumes the same total budget; it does not reset time.

Timeouts create uncertainty for side effects. The remote operation may have completed even if the local wait timed out. Use an idempotency key and status reconciliation.

## 8. Cancellation is normal control flow

Tasks can be cancelled during client disconnects, timeouts, server shutdown, or structured-concurrency failure. Cancellation is delivered at an await point.

```python
import asyncio


async def guarded_operation() -> None:
    resource = await acquire_resource()
    try:
        await perform_operation(resource)
    except asyncio.CancelledError:
        await record_cancellation()
        raise
    finally:
        await resource.close()
```

Always propagate `CancelledError` after necessary cleanup. Swallowing it prevents timely shutdown and can leave callers believing work stopped when it did not.

Cleanup itself may need a small protected budget, but shielding large operations from cancellation can delay shutdown. A database transaction context should roll back on cancellation. A remote provider still needs idempotency because cancellation does not undo a request already sent.

## 9. Thread pools for blocking I/O

When a synchronous library must be called from async code, offload a bounded operation:

```python
import asyncio


async def read_legacy_customer(customer_id: str) -> Customer:
    return await asyncio.to_thread(legacy_client.read_customer, customer_id)
```

Starlette also uses a thread pool for sync endpoints, sync dependencies, some file handling, and synchronous background tasks. Pool capacity is shared and finite. A surge of slow sync calls can cause queueing across unrelated features.

Thread offload has important limits:

- Cancelling the await does not forcibly stop arbitrary code already running in a thread.
- The called library must be safe for the way its objects are shared.
- Context propagation and thread-local behavior need verification.
- Threads consume memory and downstream connections.
- More threads can amplify an overloaded database or provider.
- Pure Python CPU work does not generally scale across cores on conventional GIL-enabled CPython builds.

Prefer a sync route for a predominantly synchronous request path. Use explicit `to_thread` when an otherwise async path has a contained blocking call and ownership is clear.

Do not create an unbounded new executor per request. Configure a deliberate shared capacity or let the framework's bounded mechanism own routine offload.

## 10. Process pools and CPU-bound work

Separate processes can execute CPU-heavy Python work in parallel and isolate it from the web event loop:

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor


def render_document(source: bytes) -> bytes:
    # Must be a top-level picklable function for common process-pool setups.
    return cpu_heavy_renderer(source)


async def render_with_pool(
    pool: ProcessPoolExecutor,
    source: bytes,
) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(pool, render_document, source)
```

Create and close a process pool with application lifespan, not per request. Account for deployment multiplication: each web worker creating four child processes can quickly exceed CPU and memory budgets.

A process pool is suitable when:

- Work is bounded and relatively short.
- Inputs and outputs are practical to serialize between processes.
- Loss on web-process failure is acceptable or handled.
- CPU and queue length are strictly bounded.

Use an external job queue when work is long, durable, retryable, scheduled, memory-heavy, independently scaled, or needs progress reporting. Return `202 Accepted` with an operation resource rather than keeping an HTTP connection open indefinitely.

Native extensions may release the GIL and use threads internally. Measure the actual library and cap its internal parallelism to avoid multiplying threads across worker processes.

## 11. Async database access

Async database APIs allow the event loop to serve other work while waiting for the driver. They do not change database capacity or query complexity.

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def find_order(session: AsyncSession, order_id: str) -> Order | None:
    statement = select(Order).where(Order.id == order_id)
    return await session.scalar(statement)
```

Rules that matter:

- One `AsyncSession` represents mutable transaction state and should not be used concurrently by several tasks.
- A connection remains finite even while the coroutine waiting on it is cheap.
- Lazy relationship access can attempt implicit I/O in surprising places.
- Long transactions hold locks and connections while other awaits happen.
- Concurrent queries often need separate sessions and connections, increasing pool demand.

Do not run two repository calls concurrently merely because they are both async if they share one session. Sequence them, restructure the query, or give deliberately independent operations separate sessions with clear consistency semantics.

Connection pool wait time is a first-class metric. Increasing pool size can move the bottleneck to the database and worsen overload.

## 12. Async HTTP clients and downstream protection

An application-wide async client reuses connections. Configure:

- Connect, read, write, and pool acquisition timeouts.
- Maximum total and keep-alive connections.
- TLS verification and trust policy.
- Redirect policy.
- Bounded response sizes or streaming limits.
- Retry behavior outside the client when business semantics require it.

Bound concurrency for a fragile provider:

```python
import asyncio


class LimitedGateway:
    def __init__(self, client: AsyncClient, capacity: int) -> None:
        self._client = client
        self._slots = asyncio.Semaphore(capacity)

    async def get_quote(self, sku: str) -> Quote:
        async with self._slots:
            response = await self._client.get(f"/quotes/{sku}", timeout=2.0)
            response.raise_for_status()
            return Quote.model_validate(response.json())
```

A semaphore limits concurrency within one process, not across a cluster. It also creates a queue, so bound queue wait with the request deadline and expose saturation metrics. Distributed rate limits and admission control solve different problems.

## 13. Backpressure and bounded queues

If producers create work faster than consumers finish it, an unbounded queue turns latency into memory growth.

```python
import asyncio


queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1_000)


async def enqueue(event: Event) -> None:
    try:
        await asyncio.wait_for(queue.put(event), timeout=0.05)
    except TimeoutError as exc:
        raise ServiceOverloaded("event queue is full") from exc
```

This queue is process-local and not durable. It may be appropriate for telemetry that can be dropped under pressure. It is inappropriate for orders, payments, or audit records requiring delivery.

Every concurrency design should name its behavior at capacity:

- Queue with a maximum wait.
- Reject or shed load.
- Degrade optional work.
- Spill to a durable broker.
- Scale consumers within an external limit.

Without an explicit capacity behavior, overload chooses one for you, usually high latency and memory exhaustion.

## 14. Races still exist in one event loop

Coroutines can interleave at await points:

```python
balance = await load_balance(account_id)
if balance >= amount:
    await debit(account_id, amount)
```

Another request can change the balance between the read and write. A process-local `asyncio.Lock` protects only tasks in one event loop, not other workers or services.

Use the authoritative system's concurrency controls:

- Atomic SQL update with a predicate.
- Row lock inside a short transaction.
- Unique or check constraint.
- Optimistic version column.
- Atomic store operation.
- Distributed lock only when its failure model is understood and the protected operation truly requires it.

The database often offers a simpler correctness boundary than application locks.

## 15. Structured concurrency versus detached work

Use `TaskGroup` when child operations belong to the request and must finish or fail together. Use a durable job when work should outlive the request. These are distinct lifetimes.

Detached in-process tasks are risky:

```python
# Risky: no durable ownership, result, or shutdown contract.
asyncio.create_task(send_receipt(order_id))
```

If the receipt matters, write an outbox record in the same transaction as the order and let a worker deliver it. If it is best-effort telemetry, a managed process-level queue with shutdown draining and drop metrics may be sufficient.

FastAPI's `BackgroundTasks` gives an in-process post-response hook, but not durability or independent capacity.

## 16. Context and observability

`contextvars.ContextVar` can carry request-scoped logging context across async tasks without passing it through every function:

```python
from contextvars import ContextVar, Token

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    return request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_var.reset(token)
```

Bind and reset it in `try/finally`. Task and thread context propagation follows specific runtime APIs, so test logging context through any custom executor or callback integration. Do not use context variables as authorization storage when explicit principal passing is clearer and safer.

Measure concurrency behavior, not only handler duration:

- Event-loop lag.
- In-flight requests by route class.
- Thread and process work queue delay.
- Database and HTTP pool acquisition time.
- Downstream request latency and timeout rate.
- Semaphore or queue saturation.
- Cancellation and disconnect counts.
- Worker CPU, memory, and restart rate.

## 17. Scaling workers

More workers provide process isolation and can use more cores, but every worker may allocate:

- A database pool.
- HTTP connection pools.
- Thread-pool capacity.
- In-memory caches.
- Model weights.
- Process-pool children.

Calculate totals across replicas and workers. Tune based on downstream capacity and memory, not a generic workers-per-core formula. In container orchestration, fewer workers per container with more replicas can simplify resource limits and failure isolation, but the right choice depends on startup cost, memory sharing, traffic, and deployment platform.

Worker scaling cannot fix slow SQL, unbounded fan-out, lock contention, or an overloaded provider.

## 18. Decision guide

| Work | Default placement | Why |
| --- | --- | --- |
| Async database or HTTP I/O | `async def` and awaitable client | Waiting yields to other requests |
| Predominantly sync request path | `def` route | Framework offloads it consistently |
| One contained blocking call in async path | Bounded thread offload | Preserves async surrounding code |
| Short CPU-heavy, picklable work | Bounded process pool | Uses separate processes and protects event loop |
| Long or important CPU work | External job worker | Durability, retries, independent scaling |
| Independent request-scoped I/O | `TaskGroup` with deadline and capacity | Structured cancellation and ownership |
| Important post-commit side effect | Transactional outbox and worker | Survives crashes and avoids dual-write gap |
| Best-effort short follow-up | `BackgroundTasks` or managed local queue | Low operational overhead when loss is acceptable |
| Cross-worker coordination | Shared store or broker | Process memory is isolated |

## 19. Common mistakes

| Mistake | Symptom | Correction |
| --- | --- | --- |
| `time.sleep` or sync HTTP in `async def` | All routes on a worker pause | Await an async API or offload deliberately |
| Assuming `await` makes work parallel | CPU remains saturated | Use processes or distributed workers |
| Unbounded `gather` over user input | Provider and pool collapse | Limit fan-out and apply backpressure |
| Sharing one `AsyncSession` across tasks | Transaction-state errors and races | Sequence operations or use independent sessions deliberately |
| Fire-and-forget `create_task` | Lost failures and shutdown work | Use structured concurrency or durable jobs |
| Retrying inside every layer | Retry storm and exceeded deadlines | Assign one retry owner and use a total budget |
| Huge thread pool | Downstream overload and memory growth | Bound capacity and measure queue delay |
| Process pool per request | Process explosion | Own one bounded pool in lifespan |
| Swallowing cancellation | Slow shutdown and leaked work | Clean up and re-raise |
| Local lock for cluster invariant | Cross-worker race remains | Enforce atomically in shared authoritative storage |

## Interview prompts

1. **When does `async def` improve a FastAPI endpoint?** When the request spends meaningful time in awaitable I/O and the full call path avoids blocking the event loop. It improves concurrency, not the latency of the downstream operation itself.
2. **Why can an async database service still exhaust connections?** Suspended coroutines are cheap, but each active database operation needs finite server and pool capacity. High concurrency can queue on or exceed that capacity.
3. **When would you choose a sync endpoint?** When the request path relies mainly on blocking libraries. FastAPI offloads a normal `def` handler to a thread pool, making the blocking boundary explicit.
4. **Thread pool or process pool?** Threads are appropriate for blocking I/O and some native work that releases the GIL. Processes isolate CPU-heavy Python work and can use multiple cores, but have serialization, memory, and lifecycle cost.
5. **What happens when an `asyncio.to_thread` call is cancelled?** The awaiting coroutine can be cancelled, but arbitrary code already running in the thread is not forcibly terminated. The operation needs its own timeout and idempotency behavior.
6. **Why not call ten providers concurrently for every request?** It multiplies downstream load, consumes connection capacity, complicates partial failure, and can create correlated overload. Concurrency must be bounded and tied to a deadline.
7. **How do you prevent a race between balance check and debit?** Use an atomic conditional database update or a short transaction with an appropriate lock or isolation strategy. An application-level check alone is not authoritative.
8. **What is backpressure?** A mechanism that prevents producers from outrunning finite consumers, using bounded queues, admission control, reduced production, or explicit rejection rather than unbounded memory and latency.
9. **How would you handle a 10-minute AI or image job?** Persist a job and idempotency key, enqueue durable work, return `202` with a status resource, run it in independently scaled workers, and support retries, cancellation, progress, and result storage.

## Sources

- [Python asyncio overview](https://docs.python.org/3/library/asyncio.html)
- [Python coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Python synchronization primitives](https://docs.python.org/3/library/asyncio-sync.html)
- [Python queues](https://docs.python.org/3/library/asyncio-queue.html)
- [Python executors](https://docs.python.org/3/library/concurrent.futures.html)
- [Python context variables](https://docs.python.org/3/library/contextvars.html)
- [FastAPI async guidance](https://fastapi.tiangolo.com/async/)
- [Starlette thread pool](https://www.starlette.io/threadpool/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [HTTPX async support](https://www.python-httpx.org/async/)
