# Source Catalog

Chapters cite the specific pages that support version-sensitive claims. This catalog records the primary authorities used across the repository and the topic each one governs.

## Python and protocols

- [Python documentation](https://docs.python.org/3/): language, typing, `asyncio`, multiprocessing, logging, and standard-library behavior.
- [ASGI specification](https://asgi.readthedocs.io/en/latest/specs/main.html): application and server interface.
- [HTTP Semantics, RFC 9110](https://www.rfc-editor.org/rfc/rfc9110): methods, status semantics, fields, and caching terminology.
- [HTTP Caching, RFC 9111](https://www.rfc-editor.org/rfc/rfc9111): cache behavior and validators.
- [OAuth 2.0 Authorization Framework, RFC 6749](https://www.rfc-editor.org/rfc/rfc6749): protocol roles and grants.
- [JSON Web Token, RFC 7519](https://www.rfc-editor.org/rfc/rfc7519): JWT claims representation.

## FastAPI stack

- [FastAPI documentation](https://fastapi.tiangolo.com/): routing, dependencies, security helpers, response handling, deployment, and testing.
- [Starlette documentation](https://www.starlette.io/): ASGI middleware, requests, responses, lifespan, background tasks, WebSockets, and test client behavior.
- [Pydantic documentation](https://docs.pydantic.dev/latest/): Pydantic v2 validation, serialization, settings, fields, and model configuration.
- [Uvicorn documentation](https://www.uvicorn.org/): ASGI server settings, process management, proxy headers, and deployment behavior.

## Data systems

- [PostgreSQL documentation](https://www.postgresql.org/docs/current/): SQL behavior, constraints, indexes, MVCC, transactions, locking, and query plans.
- [SQLAlchemy 2.0 documentation](https://docs.sqlalchemy.org/en/20/): Core, ORM mappings, sessions, async extension, relationships, and loading.
- [Alembic documentation](https://alembic.sqlalchemy.org/en/latest/): migrations, autogeneration, operations, and cookbook patterns.
- [Redis documentation](https://redis.io/docs/latest/): data types, expiration, transactions, persistence, clustering, and client patterns.

## Security

- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/): practical controls for authentication, passwords, sessions, file uploads, logging, secrets, REST, and webhooks.
- [OWASP API Security Top 10](https://owasp.org/API-Security/): common API risk categories and mitigations.
- [NIST Digital Identity Guidelines](https://pages.nist.gov/800-63-4/): identity proofing, authentication, and federation guidance.

## Deployment and operations

- [Docker documentation](https://docs.docker.com/): image builds, Compose, runtime, and build best practices.
- [NGINX documentation](https://nginx.org/en/docs/): reverse proxy, TLS, buffering, and upstream configuration.
- [OpenTelemetry documentation](https://opentelemetry.io/docs/): signals, context propagation, semantic conventions, collectors, and instrumentation.
- [pytest documentation](https://docs.pytest.org/en/stable/): fixtures, parametrization, monkeypatching, and test configuration.
- [Celery documentation](https://docs.celeryq.dev/en/stable/): workers, tasks, retries, routing, and schedules.
- [RabbitMQ documentation](https://www.rabbitmq.com/docs): exchanges, queues, acknowledgements, reliability, and consumer behavior.
- [Apache Kafka documentation](https://kafka.apache.org/documentation/): topics, partitions, offsets, consumer groups, and delivery model.

## Cloud concepts

- [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html): operational, security, reliability, performance, cost, and sustainability review concepts.
- [Amazon ECS documentation](https://docs.aws.amazon.com/ecs/): managed container scheduling concepts.
- [Amazon RDS documentation](https://docs.aws.amazon.com/rds/): managed relational database operations.
- [Elastic Load Balancing documentation](https://docs.aws.amazon.com/elasticloadbalancing/): health checks, listeners, routing, and load-balancer behavior.
- [Amazon S3 documentation](https://docs.aws.amazon.com/s3/): object storage, multipart upload, policies, and lifecycle.

## OpenAI and AI backends

- [OpenAI developer quickstart](https://developers.openai.com/api/docs/quickstart): SDK and Responses API starting point.
- [OpenAI streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses): Responses API streaming event model.
- [OpenAI background mode](https://developers.openai.com/api/docs/guides/background): long-running provider-managed responses.
- [OpenAI webhooks](https://developers.openai.com/api/docs/guides/webhooks): events and signature verification.
- [OpenAI vector embeddings](https://developers.openai.com/api/docs/guides/embeddings): embedding requests and similarity concepts.
- [OpenAI production best practices](https://developers.openai.com/api/docs/guides/production-best-practices): project, security, scaling, and operational guidance.

## Citation policy

Use the canonical project documentation or specification for externally verifiable behavior. Architecture recommendations are identified as decisions and include assumptions rather than borrowing authority from a citation. A source link is checked for relevance before merge; it is not evidence merely because it is official.

The web changes. When a cited API changes, update the explanation and example together, then run the repository quality checks.

[Back to documentation map](../README.md)
