# FastAPI Backend Engineering

This handbook treats FastAPI as one part of a production backend system. Start with the [repository overview](../README.md), follow the [backend roadmap](../resources/backend-roadmap.md), or jump to the chapter that matches the failure or design decision in front of you.

The chapters use layered explanations: mechanism, implementation, production boundary, failure modes, and interview discussion. The examples are deliberately opinionated, while the architecture chapters state the assumptions behind those opinions.

## Common entry points

- [Understand an HTTP request end to end](01-fastapi-core/request-response-lifecycle.md)
- [Choose sync or async honestly](01-fastapi-core/async-concurrency.md)
- [Set transaction boundaries](02-data/alembic-and-transactions.md)
- [Design authentication and authorization separately](03-security/authentication-and-tokens.md)
- [Diagnose latency before adding infrastructure](04-production/performance-and-scalability.md)
- [Select a project structure](../backend-project-structure.md)
- [Work through production incidents](../interview/scenario-based.md)

## Repository promises

Every file contains working knowledge, not a placeholder. Recommendations describe their tradeoffs. Version-sensitive statements link to primary sources. The quality checker validates internal links, forbidden dash characters, empty headings, and placeholder language.
