# Containers and Deployment

Deployment is the process of turning a tested source revision into a running service that starts reliably, receives traffic securely, survives routine failures, and can be replaced or rolled back. Docker packages the application and runtime dependencies, but it does not provide availability, TLS, secret management, database safety, or observability by itself.

A production design must answer:

- who terminates TLS and validates proxy headers;
- who starts and restarts processes;
- how many replicas and worker processes run;
- how configuration and secrets reach each process;
- when migrations and other one-time steps run;
- how readiness, liveness, graceful shutdown, and rollback work;
- how images are built, verified, promoted, and traced to source.

## Build an immutable image

Build once, then promote the same image digest through environments. Environment-specific source builds create artifacts that are difficult to compare. Runtime configuration selects endpoints and features; it should not change application code in the image.

### A production-oriented Dockerfile

This example uses a builder stage to create a virtual environment, then copies only runtime artifacts into a smaller final stage. Pin the Python base by digest in a real release process and update it deliberately.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY requirements.lock ./requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --require-hashes -r requirements.lock


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app migrations ./migrations

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Important details:

- Exec-form `CMD` lets Uvicorn receive termination signals as PID 1.
- `PYTHONUNBUFFERED=1` sends logs promptly to the container collector.
- A non-root numeric user reduces privilege and works with runtimes that do not resolve names.
- Locked hashes make dependency resolution reproducible and detect changed artifacts.
- Build tools and package caches remain outside the runtime stage.
- The application is copied after dependencies so source changes do not invalidate the expensive dependency layer.

Multi-stage builds reduce image content, but they do not automatically make it secure. Keep the runtime base patched, scan OS and Python packages, remove unused executables when justified, and avoid installing compilers in the final stage.

If dependencies compile native extensions, build them against a compatible libc and runtime image. A wheel built on one distribution may not run on another.

### Build context

Use `.dockerignore` to prevent large or sensitive files from entering the build context:

```text
.git
.env
.venv
__pycache__/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
tests/
docs/
dist/
*.pem
```

Including a secret in build context is risky even when no final `COPY` appears to expose it. Use BuildKit secret mounts for build-time credentials and ensure no command writes them into a layer. Prefer private package registry tokens that are short-lived and scoped.

### Image contents and provenance

A release should record:

- immutable image digest;
- source commit and clean/dirty status;
- build pipeline identity and timestamp;
- dependency lock and software bill of materials;
- vulnerability scan result and accepted exceptions;
- signature or provenance attestation where the platform supports verification.

Expose version and commit in a safe metadata endpoint and telemetry resource, not as a mutable `latest` tag alone.

## Docker Compose for local integration

Compose is useful for a reproducible local stack and can operate a modest single-host deployment. It is not a full multi-host orchestrator.

```yaml
services:
  api:
    build:
      context: .
      target: runtime
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    environment:
      APP_ENVIRONMENT: local
      APP_DATABASE_URL: postgresql+asyncpg://app:app@postgres:5432/app
      APP_REDIS_URL: redis://redis:6379/0
    volumes:
      - ./app:/app/app
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:8
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  postgres-data:
```

This uses deliberately simple local credentials. Production secrets do not belong in the Compose file or repository.

`depends_on` with a health condition helps startup order, but it does not guarantee a dependency stays available. The application still needs timeouts, retries where safe, and reconnection behavior.

Use a development stage or override file for reload and bind mounts. Do not deploy the reload server, source bind mounts, or a writable repository into production.

## Process topology: Uvicorn and workers

Uvicorn is an ASGI server. One Uvicorn process can handle many concurrent I/O-bound requests, but it uses one Python process and normally one CPU core at a time for Python execution.

There are two common replication models:

### One process per container

Run one Uvicorn process, then let Kubernetes, ECS, Nomad, or another orchestrator replicate containers. This gives the orchestrator direct visibility into process health, predictable resource accounting, and simple rolling replacement.

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="10.0.0.0/8" \
  --timeout-graceful-shutdown=30
```

Set the trusted proxy range to the real network path. Never trust forwarded headers from arbitrary clients.

### Multiple workers per host or container

On a single VM or a simple Compose host, multiple Uvicorn workers can use multiple CPU cores:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Each worker has its own memory, event loop, connection pools, in-process cache, and application startup. Four workers configured with a 20-connection database pool can open up to 80 database connections before overflow. Memory-resident models are also copied or otherwise resident per process, so worker count cannot be chosen from CPU count alone.

Gunicorn remains an option on Unix when its process management features are needed. Uvicorn's old `uvicorn.workers` module is deprecated; use the separately maintained `uvicorn-worker` package when choosing Gunicorn:

```text
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn_worker.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 60 \
  --graceful-timeout 30
```

Validate exact options against the installed versions. Do not combine orchestrator replication and a large worker count without a capacity model.

### Worker sizing

Load-test representative endpoints and consider:

- CPU utilization and throttling;
- memory per process and peak request memory;
- database, Redis, and HTTP connection budgets;
- blocking synchronous code;
- event-loop lag;
- request duration and graceful-shutdown window;
- long-lived WebSocket/SSE connections;
- CPU-intensive or model-inference work that belongs in separate workers.

More workers can increase context switching and downstream contention while worsening latency. Start small, measure saturation, and scale the constrained resource.

## Reverse proxy and TLS

A reverse proxy or managed load balancer commonly:

- terminates TLS and manages certificates;
- routes hosts and paths;
- enforces request body and header limits;
- applies edge timeouts and rate limits;
- buffers or streams requests and responses;
- adds forwarding and request-ID headers;
- balances traffic across healthy replicas.

```mermaid
flowchart LR
    Client --> DNS
    DNS --> Edge[CDN or WAF]
    Edge --> LB[TLS load balancer]
    LB --> API1[Uvicorn replica]
    LB --> API2[Uvicorn replica]
    API1 --> DB[(PostgreSQL)]
    API2 --> DB
    API1 --> Redis[(Redis)]
    API2 --> Redis
```

### Minimal Nginx example

```nginx
upstream fastapi_backend {
    server api:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/tls/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/privkey.pem;

    client_max_body_size 10m;

    location / {
        proxy_pass http://fastapi_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Request-ID $request_id;
        proxy_connect_timeout 2s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
}
```

This is a starting point. WebSockets require `Upgrade` and `Connection` handling. Server-Sent Events and streaming responses may require buffering to be disabled. Large uploads are better streamed directly to object storage with signed URLs than passed through every application layer.

Align timeouts from outermost to innermost so the application stops work before a gateway gives up, and so graceful shutdown exceeds the legitimate request window. A proxy timeout is not cancellation-safe for every downstream side effect.

Use current TLS protocols and ciphers, automate certificate renewal, redirect cleartext HTTP where appropriate, and enable HSTS only after understanding its domain-wide effect. Managed load balancers often reduce certificate and patching burden.

### Forwarded headers

Any client can send `X-Forwarded-For` and `X-Forwarded-Proto`. Configure Uvicorn to trust only the direct proxies that overwrite or sanitize these headers. Incorrect trust affects client-IP rate limits, audit trails, secure redirect generation, and cookies.

## Health, readiness, and liveness

Different probes answer different questions:

- **Liveness**: is this process responsive enough to remain running?
- **Readiness**: should this instance receive new traffic now?
- **Startup**: has slow initialization completed, before liveness enforcement begins?
- **Dependency diagnostics**: what is degraded, for operators rather than load balancers?

```python
import asyncio

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
async def ready(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, bool] = {}
    try:
        async with asyncio.timeout(0.5):
            async with request.app.state.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    if not all(checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": checks}
    return {"status": "ready", "checks": checks}
```

Probe calls need very short timeouts. Do not make liveness depend on every downstream service: a shared database outage would cause every application replica to restart, adding load without repairing the database. Readiness should include only dependencies required to serve the traffic represented by the probe. Optional capabilities can be reported as degraded on an operator endpoint.

Secure diagnostic details. Public health responses should not reveal credentials, hostnames, versions with known vulnerabilities, or stack traces. Exclude high-frequency probes from ordinary access logs or sample them.

## Graceful startup and shutdown

On termination:

1. the load balancer should stop routing new work;
2. readiness changes to false;
3. the server drains in-flight requests within a deadline;
4. consumers stop fetching new messages and finish or safely requeue current work;
5. pools, clients, and telemetry exporters flush and close;
6. the platform sends a hard kill only after the grace period.

Account for load-balancer deregistration delay. If a container exits immediately after receiving SIGTERM, clients see resets. If it ignores termination indefinitely, deployments stall.

Startup should validate settings, initialize process-wide clients, and load required models. It should not run database migrations independently in every replica.

## Database migrations in deployment

Run migrations as a distinct, observable, single logical deployment step or job. The exact platform mechanism can be an init job, release command, or CI/CD stage. Running `alembic upgrade head` in every web container creates races and couples traffic readiness to schema locks.

Use expand-and-contract for rolling compatibility:

1. add nullable columns, new tables, or compatible indexes;
2. deploy code that can work with old and new forms;
3. backfill in bounded, resumable batches;
4. switch reads and writes;
5. verify adoption and data;
6. remove old columns or constraints in a later release.

During a rolling deploy, old and new application versions coexist. A migration safe only after every old replica stops cannot be applied first.

For large tables, analyze locks, transaction duration, replication lag, disk space, and index-build method. Backup does not guarantee an easy rollback; test restoration and forward repair.

## Deployment strategies

### Rolling

Replace instances gradually. It uses normal capacity efficiently but runs mixed versions. API, database, message, and cache schemas must be compatible across the overlap.

### Blue-green

Prepare a complete new environment and switch traffic. Rollback is quick while the old environment remains viable, but duplicate capacity costs more and shared database changes still require compatibility.

### Canary

Send a small, controlled share of traffic to the new version, observe service-level and business metrics, then increase. User or tenant stickiness may be necessary. A canary that receives only health checks proves little.

### Feature flags

Decouple code deployment from behavior release. Flags need ownership, defaults, audit, test coverage for important combinations, and removal dates. They do not make incompatible database changes safe.

Automated rollback should use signals strongly attributable to the release, such as error rate, latency, saturation, and critical business failure. Rolling back application code after an irreversible schema or external side effect may not restore the previous state.

## CI/CD pipeline

A representative pipeline is:

```mermaid
flowchart LR
    Commit --> Static[Format, lint, type check]
    Static --> Tests[Unit and integration tests]
    Tests --> Build[Build image once]
    Build --> Scan[SBOM, vulnerability, secret scan]
    Scan --> Sign[Sign and attest]
    Sign --> Stage[Deploy by digest to staging]
    Stage --> Smoke[Migration and smoke checks]
    Smoke --> Promote[Approval or policy gate]
    Promote --> Prod[Canary or rolling production]
    Prod --> Verify[Post-deploy SLO and business checks]
```

Key properties:

- pull requests cannot publish over a trusted production tag without authorization;
- deployment uses an immutable digest, not whatever a tag points to later;
- environment credentials come from workload identity or protected short-lived tokens;
- the pipeline records who approved and what was deployed;
- migrations and application rollout have explicit order and failure handling;
- rollback or roll-forward procedures are practiced;
- production verification checks a real critical path, without mutating customer data unexpectedly.

Run untrusted pull-request code with no production secrets. Treat third-party CI actions and base images as supply-chain dependencies.

## Capacity and autoscaling

Set CPU and memory requests/reservations based on measurement, plus hard limits according to platform behavior. Too-low CPU limits can throttle latency-sensitive workers; an out-of-memory kill gives no graceful cleanup.

Autoscaling signals can include:

- CPU for CPU-bound workloads;
- concurrency or request rate per instance;
- latency and saturation;
- queue oldest-message age for workers;
- active streaming connections;
- custom cost units for heterogeneous AI work.

Scaling the API does not scale PostgreSQL, a provider quota, or a fixed worker queue. Every new replica adds connection pools. Put maximum connections into a system-wide budget and use an external pooler where appropriate.

Keep stateless request handling where possible. Store sessions, uploads, and job status in shared durable systems. WebSockets may need connection-aware routing, a shared pub/sub layer, and draining behavior during rollout.

## Cloud deployment concepts

The same architecture maps to many providers. On AWS, common mappings are:

| Concern | AWS example | Engineering decision |
|---|---|---|
| Virtual machines | EC2 | Patch, process supervision, scaling, network, and capacity remain yours |
| Managed containers | ECS on Fargate or EC2 | Task definitions, load balancer, autoscaling, IAM roles, log routing |
| Kubernetes | EKS | Kubernetes control and ecosystem, with meaningful operational cost |
| HTTP load balancing | Application Load Balancer | TLS, health checks, routing, idle timeout, target draining |
| Relational database | RDS or Aurora PostgreSQL | Pool budget, failover, backup, parameter tuning, migrations |
| Object storage | S3 | Direct uploads, encryption, lifecycle, access policy, event delivery |
| Cache | ElastiCache for Redis-compatible engines | Topology, failover, TLS, eviction, maintenance |
| Queue/eventing | SQS, SNS, MSK, EventBridge | Delivery, ordering, replay, delay, retention, cost |
| Secrets | Secrets Manager or Parameter Store | IAM scope, rotation, caching, startup behavior |
| Telemetry | CloudWatch and/or OpenTelemetry backend | retention, cardinality, alerting, cross-service trace flow |

Use task or instance roles rather than static access keys. Restrict network paths with security groups and private subnets according to the threat model. Keep the database and caches off public interfaces.

### Lambda and serverless considerations

FastAPI can run behind an adapter in a function environment, but evaluate:

- cold starts and package/model size;
- connection reuse across warm invocations and database connection storms;
- request and response size, duration, and streaming limits of the front door;
- concurrency scaling beyond downstream capacity;
- background work, which must be handed to a durable service before return;
- WebSocket and long-lived connection support;
- cost at steady high traffic versus containers.

Serverless is a deployment model, not a universal performance improvement.

## Common deployment failures

- Shipping `--reload` or development credentials to production.
- Running as root with a writable application directory.
- Building a different artifact for each environment.
- Using `latest` as the only release identity.
- Starting migrations in every replica.
- Trusting all forwarded headers.
- Multiplying workers without multiplying the database connection budget.
- Using liveness checks that restart every replica during a shared dependency outage.
- Setting proxy timeout shorter than normal request duration without redesigning long work.
- Terminating instances before load-balancer draining completes.
- Baking secrets into image layers or CI output.
- Assuming a successful rollout means business behavior is correct.

## Production checklist

- Runtime image is minimal, non-root, reproducible, scanned, and identified by digest.
- Secrets are injected at runtime and absent from build context and layers.
- Development and production commands are distinct.
- Worker and replica counts match memory, CPU, and downstream pool budgets.
- TLS and forwarded-header trust terminate at documented boundaries.
- Liveness, readiness, startup, and diagnostic health have distinct semantics.
- Shutdown drains HTTP and workers within platform grace periods.
- Migrations use expand-and-contract and a single observable runner.
- CI builds once, records provenance, and promotes the same artifact.
- Rollout and rollback decisions use technical and business signals.
- Restore, incident, secret rotation, and rollback procedures have been exercised.

## Interview prompts

1. Why is one Uvicorn process per container often preferred under an orchestrator?
2. How do four workers affect database connection and memory planning?
3. Why should liveness usually not query the database?
4. Explain expand-and-contract migrations during a rolling deployment.
5. What is lost when forwarded headers are trusted from every client?
6. Compare rolling, blue-green, and canary releases.
7. Why should an image be promoted by digest rather than rebuilt for production?
8. What changes when deploying FastAPI to a function runtime rather than containers?

## Further reading

- [FastAPI: FastAPI in Containers](https://fastapi.tiangolo.com/deployment/docker/)
- [FastAPI: Server Workers](https://fastapi.tiangolo.com/deployment/server-workers/)
- [Uvicorn Deployment](https://www.uvicorn.org/deployment/)
- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker Build Best Practices](https://docs.docker.com/build/building/best-practices/)
- [Docker Compose Services](https://docs.docker.com/reference/compose-file/services/)
- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html)

## Related topics

- [Production Architecture](../../architecture/production-architecture.md)
- [Performance and Scalability](./performance-and-scalability.md)
- [Observability](./observability.md)
