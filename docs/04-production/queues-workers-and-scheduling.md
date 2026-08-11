# Queues, Workers, and Scheduling

An HTTP request has a deadline and a caller waiting for an answer. Many jobs do not fit that model: sending email, generating reports, processing uploads, fan-out notifications, and long AI inference may take seconds or minutes, need retry, or require independent capacity. A queue turns that work into a durable handoff between a producer and one or more workers.

The handoff creates distributed-system problems. Messages can be delayed, duplicated, reordered, or delivered after a producer times out. Reliable background processing therefore depends on idempotency, acknowledgements, bounded retries, durable state, and observability, not only on calling `.delay()`.

## Choose the smallest suitable mechanism

| Mechanism | Lifetime and guarantees | Use it for | Do not use it for |
|---|---|---|---|
| Inline `await` | Same request, caller receives outcome | Necessary I/O that completes within the request budget | Work that can outlive the request |
| FastAPI `BackgroundTasks` | Same application process, after response | Short, best-effort side effects where loss is acceptable | Durable work, CPU-heavy work, long jobs, guaranteed retry |
| In-process `asyncio.create_task()` | Same event loop unless explicitly supervised | Application-lifetime supervisors and carefully managed internal loops | Request-triggered durable jobs |
| Process/thread pool | Same deployment, parallel execution | Bounded CPU or blocking library calls | Durable cross-restart workflow |
| Task queue such as Celery | Brokered delivery to worker processes | Retriable jobs, separate scaling, scheduling | High-volume replayable event history by default |
| Event log such as Kafka | Durable partitioned stream consumed by groups | Domain event distribution, replay, analytics pipelines | Simple request/reply task dispatch with per-task scheduling |
| Managed queue | Provider-defined durable delivery | Reduced broker operations and cloud-native workers | Portability assumptions without reviewing semantics |

### FastAPI `BackgroundTasks`

`BackgroundTasks` runs after the response is sent, but inside the web process. A deploy, crash, worker timeout, or process termination can lose the task. It also competes with request handling for process resources.

```python
from fastapi import BackgroundTasks, FastAPI, status

app = FastAPI()


def record_noncritical_audit(event_id: str) -> None:
    # Short and safe to lose in this example. A real audit requirement
    # usually belongs in a transaction or durable queue.
    print(event_id)


@app.post("/feedback", status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(background: BackgroundTasks) -> dict[str, str]:
    event_id = "evt_123"
    background.add_task(record_noncritical_audit, event_id)
    return {"status": "accepted", "event_id": event_id}
```

Returning 202 does not make the work durable. It says the request was accepted for processing, so the system should normally expose a status resource or another completion signal. If loss would surprise the caller, persist a job before returning.

## A durable job model

Do not make the broker the only user-visible record. A job table provides stable status, ownership, timestamps, attempts, result references, and a place to enforce tenant authorization.

```text
jobs
  id                 UUID/ULID primary key
  tenant_id          authorization boundary
  type               bounded job type
  status             pending | running | succeeded | failed | cancelled
  input_ref          reference to durable input, not a huge payload
  result_ref         reference to durable output
  idempotency_key    optional unique key scoped to tenant and operation
  attempt_count      integer
  progress_current   optional integer
  progress_total     optional integer
  error_code         safe machine-readable failure code
  created_at
  started_at
  completed_at
  heartbeat_at
  version            optimistic concurrency version
```

A common API contract is:

```http
POST /v1/reports
Idempotency-Key: 2a5f...

HTTP/1.1 202 Accepted
Location: /v1/jobs/job_01J...

{"job_id":"job_01J...","status":"pending"}
```

Then:

```http
GET /v1/jobs/job_01J...

HTTP/1.1 200 OK
{"job_id":"job_01J...","status":"running","progress":{"current":42,"total":100}}
```

Use object storage for large inputs and outputs. Broker payloads should contain identifiers, versioned metadata, and trace context, not uploaded files, model weights, or sensitive records that every broker operator can inspect.

## The dual-write problem and transactional outbox

This sequence is unsafe:

```python
await session.commit()      # order exists
send_to_broker(order.id)    # process can fail here
```

Publishing first is also unsafe because a worker can observe an order that later rolls back. A transactional outbox records the domain change and pending message in one database transaction. A relay later publishes outbox rows and marks them dispatched.

```mermaid
flowchart LR
    API[FastAPI request] --> TX[Database transaction]
    TX --> Order[(orders)]
    TX --> Outbox[(outbox_events)]
    Relay[Outbox relay] --> Outbox
    Relay --> Broker[(Broker)]
    Broker --> Worker[Idempotent worker]
    Worker --> Result[(job/result state)]
```

The relay can crash after publishing but before marking the row sent, so it may publish again. The consumer still must be idempotent. The outbox solves atomic recording, not exactly-once delivery.

A production outbox needs:

- row claiming that allows multiple relay instances, often `FOR UPDATE SKIP LOCKED`;
- stable event IDs and schema versions;
- publisher confirms where the broker supports them;
- retry with a next-attempt timestamp and terminal failure visibility;
- retention and archival;
- lag metrics from event creation to publish;
- ordering rules, often an aggregate ID and aggregate version.

Change data capture can publish the database log instead of polling, but it adds infrastructure and schema-evolution concerns. It does not remove idempotent consumer requirements.

## Delivery semantics in practical terms

### At-most-once

The message is removed or acknowledged before processing. Failure can lose work, but duplicates are minimized. Suitable only when loss is acceptable.

### At-least-once

The message is acknowledged after successful processing. If the worker completes the side effect but crashes before acknowledgement, the broker redelivers it. This is the normal target for reliable jobs and requires idempotency.

### Exactly-once

Exactly-once is scoped to a boundary. Kafka transactions can provide strong semantics for consume-process-produce flows inside Kafka. They do not make an email provider, payment gateway, database, and broker participate in one atomic transaction. At external boundaries, build effectively-once outcomes with unique operation keys, atomic state transitions, deduplication records, and reconciliation.

## Idempotent workers

An idempotent worker can process the same message more than once without applying the business effect twice.

Useful techniques:

- a database unique constraint on `(consumer_name, message_id)`;
- a unique business key, such as `(merchant_id, payment_attempt_id)`;
- compare-and-set state transitions, such as `pending -> sent`;
- an upstream idempotency key supported by the provider;
- inbox table recording consumed event IDs in the same transaction as local changes;
- deterministic object-storage keys and conditional writes.

Do not use a short-lived Redis key as the only deduplication record for a permanent financial side effect. Expiry, eviction, failover, or replay after retention can reapply the operation.

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def consume_order_created(
    session: AsyncSession, *, message_id: str, order_id: str
) -> None:
    async with session.begin():
        seen = await session.scalar(
            select(InboxMessage.id).where(
                InboxMessage.consumer == "fulfillment",
                InboxMessage.message_id == message_id,
            )
        )
        if seen is not None:
            return

        order = await session.get(Order, order_id, with_for_update=True)
        if order is None:
            raise PermanentMessageError("unknown order")
        order.reserve_fulfillment()
        session.add(
            InboxMessage(consumer="fulfillment", message_id=message_id)
        )
```

Back the inbox lookup with a unique constraint and handle a uniqueness race, because two deliveries can execute concurrently.

## Celery with FastAPI

Celery is a distributed task framework commonly paired with RabbitMQ or Redis. Keep the FastAPI process a producer and run workers separately. Import application/domain services into both entry points; do not call an HTTP route function from a task.

```python
# app/worker/celery_app.py
from celery import Celery

celery_app = Celery(
    "orders",
    broker="amqp://app:secret@rabbitmq:5672/orders",
    backend="redis://redis:6379/2",
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=270,
    task_time_limit=300,
    broker_connection_retry_on_startup=True,
)
```

Configuration choices are workload-specific:

- `acks_late` supports redelivery after worker loss, so the task must be idempotent.
- A low prefetch multiplier improves fairness for long jobs but may reduce throughput for short jobs.
- Soft and hard time limits bound runaway work, but forced termination can interrupt non-atomic side effects.
- A result backend is optional. Do not retain every result forever when the application job table already owns status.

A task should accept small serializable identifiers, establish its own database session, and classify failures.

```python
import httpx

from app.worker.celery_app import celery_app


@celery_app.task(
    bind=True,
    autoretry_for=(httpx.ConnectError, httpx.TimeoutException),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    retry_kwargs={"max_retries": 6},
    name="notifications.send_email",
)
def send_email(self, notification_id: str) -> None:  # type: ignore[no-untyped-def]
    # A synchronous task is appropriate in a standard Celery worker.
    # The service checks durable state, claims the notification atomically,
    # and passes notification_id as the provider idempotency key if supported.
    EmailDeliveryService().deliver(notification_id)
```

Do not autoretry every `Exception`. Invalid addresses, unsupported templates, authorization failures, and schema errors are usually permanent. Retrying them wastes capacity and delays visibility.

### Publishing from a route

Persist the job and outbox event in the request transaction. If the product accepts the smaller failure window of direct publishing, handle broker errors, use a stable task ID, and do not claim the task is queued until the broker has accepted it.

```python
from fastapi import APIRouter, status

router = APIRouter()


@router.post("/exports", status_code=status.HTTP_202_ACCEPTED)
async def create_export(command: CreateExport, service: ExportServiceDep) -> JobAccepted:
    job = await service.create_job(command)  # commits job plus outbox row
    return JobAccepted(job_id=job.id, status=job.status)
```

This keeps Celery out of the API layer and makes the acceptance contract testable without a live broker.

## RabbitMQ, Redis brokers, and Kafka

### RabbitMQ

RabbitMQ is a message broker with exchanges, routing keys, queues, acknowledgements, dead lettering, priorities, and queue types. It fits command-style work distribution and routing well.

For reliable task delivery:

- declare durable queues and publish persistent messages;
- use publisher confirms so the producer knows the broker accepted responsibility;
- use manual consumer acknowledgements after the durable business effect;
- choose quorum queues where their replicated safety and performance tradeoff fits;
- set prefetch according to task duration and worker capacity;
- define dead-letter behavior deliberately;
- monitor unroutable messages, redelivery, consumer count, queue depth, and oldest-message age.

TCP success does not prove a message was durably accepted. Publisher confirms and consumer acknowledgements address different legs of delivery. Even with both, duplicates remain possible.

### Redis as a task broker

Redis is operationally convenient when already present, but review the queue framework's visibility timeout, acknowledgement emulation, persistence, eviction, and failover behavior. Do not allow cache eviction to discard broker data. Separate instances or at least memory and eviction policies for materially different workloads.

### Kafka

Kafka stores ordered records in partitioned logs. Consumer groups divide partitions among instances, and independent groups can replay the same events. It fits retained domain events, integration streams, analytics, and high-throughput pipelines.

Kafka is not a drop-in replacement for a task queue:

- ordering is within a partition, not an entire topic;
- partition count bounds active consumers in one group;
- delayed delivery and per-message retry require patterns such as retry topics;
- poison records can block a partition unless handled;
- consumer offset commit and external side effects still need coordination;
- schema compatibility and event retention are first-class design work.

Choose a partition key that represents the ordering boundary, such as `order_id`. A hot tenant or celebrity user can create partition skew.

### Selection guide

Use RabbitMQ or a managed task queue for commands that one worker should execute, with per-job acknowledgement, routing, and retry. Use Kafka when multiple independent consumers, retention, replay, ordered event streams, and high throughput justify its operational and modeling cost. It is common to use both, but only when the organization can operate both and the responsibilities remain clear.

## Retry, backoff, jitter, and dead letters

A retry is appropriate only when:

- the failure is plausibly transient;
- the operation is idempotent or guarded by a durable operation key;
- enough deadline or job lifetime remains;
- retrying will not amplify an overloaded dependency.

Use exponential backoff with random jitter and a cap. A conceptual full-jitter delay is:

```python
import random


def retry_delay(attempt: int, *, base: float = 0.5, cap: float = 60.0) -> float:
    maximum = min(cap, base * (2**attempt))
    return random.uniform(0, maximum)
```

Limit both attempts and elapsed time. Respect an upstream `Retry-After` value when trusted and within policy. Apply a retry budget so a dependency outage does not turn every original request into many queued attempts.

A dead-letter queue is an investigation and recovery mechanism, not a trash can. Store failure category, attempt count, original message ID, timestamps, and safe diagnostic context. Alert on arrival rate and age. Provide an audited replay tool that preserves message identity and prevents bulk retry into a still-failing dependency.

## Backpressure and overload

Queue depth alone is not enough. A system can have a short queue full of hour-long jobs or a long queue of millisecond jobs. Track oldest-message age and estimated time to drain.

When producers outrun consumers:

- reject or defer new optional work;
- enforce tenant quotas and global admission control;
- scale workers until the database or upstream becomes the bottleneck;
- separate short and long tasks into queues and worker pools;
- bound payload and result size;
- pause low-priority consumers;
- shed duplicate/coalescible jobs;
- expose honest completion estimates rather than accepting infinite work.

Autoscaling on queue depth without considering downstream capacity can overwhelm the database. Worker concurrency times database connections per worker must fit the database pool budget.

## Scheduling recurring work

Scheduling and executing are separate concerns. The scheduler determines when a job is due; workers perform it.

Options include:

- platform cron that enqueues a durable job;
- Celery Beat as a scheduler for Celery tasks;
- APScheduler for an application with carefully controlled single ownership;
- a database-backed scheduler with row leasing;
- a managed scheduler that invokes an endpoint or publishes to a queue.

Do not run an in-process scheduler in every Uvicorn worker unless duplicate schedules are intentional. Four web workers can emit the same job four times. Even a single scheduler may emit twice during failover, so scheduled jobs remain idempotent.

Time concerns:

- store instants in UTC and retain the named time zone for human schedules;
- define daylight-saving behavior for missing or repeated local times;
- decide whether missed runs are skipped, coalesced, or replayed;
- prevent overlapping runs with a job state transition or lease, not only a process-local flag;
- record scheduled time separately from actual start time to measure schedule delay.

## Email and notification jobs

Email illustrates why a queue alone is insufficient:

1. Persist a notification intent with recipient, template version, locale, and business key.
2. Commit it with the triggering domain change or outbox event.
3. A worker claims the intent atomically.
4. Render from versioned, tested templates.
5. Send using a provider idempotency key where available.
6. Record provider message ID and status.
7. Process delivery, bounce, complaint, and unsubscribe webhooks idempotently.

Separate transactional mail from bulk campaigns so a campaign cannot delay password resets. Apply suppression lists and user preferences before sending. Treat email addresses and content as sensitive data in broker payloads and logs.

## Cancellation and progress

Cancellation is cooperative. An API can mark `cancel_requested`, but a running worker must check at safe points and stop without leaving partial state. Broker revocation or killing a process alone is not a business rollback.

Progress updates should be monotonic, rate-limited, and useful. Updating the database after every processed byte creates avoidable load. For jobs with unknown total work, expose phases (`uploading`, `extracting`, `indexing`) rather than a fictional percentage.

## Testing background work

Test at several boundaries:

- unit-test the service called by the task as ordinary Python;
- test the task adapter's retry/permanent-failure classification;
- test the API creates a job and outbox row atomically;
- integration-test broker serialization, routing, and a real worker in a separate suite;
- simulate redelivery and assert the business effect remains single;
- test worker death after the side effect but before acknowledgement;
- test dead-letter and replay tooling;
- test schedule duplication and missed-run policy.

Eager task modes are useful but do not reproduce broker acknowledgements, serialization, process boundaries, or concurrency. Do not let them be the only integration coverage.

## Operational checklist

- The job exists durably before the API reports acceptance.
- Message schemas are versioned and payload sizes bounded.
- Publishing is coordinated with database writes through an outbox or a documented alternative.
- Workers are idempotent under concurrent duplicate delivery.
- Transient and permanent failures are classified.
- Retries have backoff, jitter, caps, budgets, and a terminal state.
- Queue depth, oldest age, processing latency, failures, retries, and worker saturation are monitored.
- Broker credentials, virtual hosts/namespaces, TLS, and ACLs are least privilege.
- Long and short workloads cannot starve each other.
- Schedulers can fail over without relying on exactly-once firing.
- Shutdown stops intake, drains within a deadline, and safely requeues unfinished work.

## Interview prompts

1. Why is FastAPI `BackgroundTasks` unsuitable for a payment or email that must not be lost?
2. Explain the database-and-broker dual-write problem and the transactional outbox.
3. How can at-least-once delivery create a duplicate after successful processing?
4. Compare RabbitMQ and Kafka for work distribution and event integration.
5. What does `acks_late` change in a Celery task, and what must the task guarantee?
6. How would you stop a retry storm during a third-party outage?
7. Why can four Uvicorn workers make an in-process scheduler run a job four times?
8. Which metrics reveal that a queue is falling behind before queue storage fills?

## Further reading

- [FastAPI: Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Celery: Tasks, retry, acknowledgement, and idempotency](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Celery: Periodic Tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
- [RabbitMQ Reliability Guide](https://www.rabbitmq.com/docs/reliability)
- [RabbitMQ Consumer Acknowledgements and Publisher Confirms](https://www.rabbitmq.com/docs/confirms)
- [Apache Kafka Design](https://kafka.apache.org/documentation/#design)

## Related topics

- [Integrations, Webhooks, and Resilience](./integrations-webhooks-and-resilience.md)
- [Testing Strategy](./testing-strategy.md)
- [Distributed Systems](../../architecture/distributed-systems.md)
