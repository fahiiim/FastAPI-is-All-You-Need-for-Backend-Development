# Authorization and Multi-Tenant Isolation

Authorization decides whether a principal may perform an action on a resource in the current context. It is a domain policy evaluated at every access path, not a boolean attached to authentication.

A useful authorization question has at least four parts:

```text
Can principal P perform action A on resource R in context C?
```

Context can include tenant, resource state, authentication strength, time, network trust, or delegation. Checking only `is_admin` or only a token scope loses most of this information.

## Core rules

Build around these rules:

- Deny by default.
- Check every request, including reads, exports, bulk actions, background jobs, and internal tools.
- Scope the database query as part of authorization when possible.
- Use stable permissions rather than scattering role-name checks through routers.
- Keep tenant identity server-derived and immutable within one operation.
- Treat object identifiers as locators, never as proof of access.
- Record high-value decisions without logging sensitive resource contents.
- Test negative cases more heavily than the happy path.

Authentication failure is normally `401 Unauthorized`. An authenticated principal that lacks permission normally receives `403 Forbidden`. For resources whose existence must not be disclosed, return the same tenant-scoped `404 Not Found` for absent and inaccessible objects. Apply the policy consistently.

## Model permissions, then assign roles

A role is a convenient bundle. A permission names an allowed business capability.

```python
from enum import StrEnum


class Permission(StrEnum):
    ORDER_READ = "order:read"
    ORDER_CREATE = "order:create"
    ORDER_REFUND = "order:refund"
    MEMBER_INVITE = "member:invite"
    MEMBER_ROLE_CHANGE = "member:role_change"
    AUDIT_READ = "audit:read"
```

Endpoint and service policy should ask for `order:refund`, not for a role named `manager`. Product teams can change which roles grant that permission without rewriting application branches.

A tenant-aware RBAC schema might include:

```text
users(id, ...)
tenants(id, ...)
roles(id, tenant_id, name, is_system_role, ...)
permissions(code, ...)
role_permissions(role_id, permission_code)
memberships(tenant_id, user_id, role_id, status, ...)
```

Use uniqueness and composite foreign keys to prevent a membership from referencing another tenant's custom role. System role templates can be copied or referenced through an explicit design, but a nullable `tenant_id` with ambiguous global behavior is easy to misuse.

### Role hierarchy

Role inheritance reduces repetitive grants but makes effective access harder to reason about. A hierarchy must be acyclic, deterministic, and visible in administrative UI and audit output. It should not infer that a billing administrator is also a content administrator simply because one role sounds "higher."

Prefer a shallow set of role-to-permission assignments. Compute effective permissions in one policy component. If results are cached, membership and role changes need a bounded invalidation strategy.

### OAuth scopes are not the whole policy

An OAuth scope describes delegated capability granted to a client/token. It can be one input to authorization. It does not prove that the subject belongs to the tenant, owns a resource, satisfies a state transition, or still has the underlying account permission.

## FastAPI policy dependencies

A dependency can enforce coarse endpoint capability and return the already authenticated principal:

```python
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

AuthorizationDependency = Callable[..., Coroutine[Any, Any, Principal]]


def require_permissions(*required: Permission) -> AuthorizationDependency:
    async def dependency(
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Principal:
        granted = await authorization.effective_permissions(
            session,
            subject_id=principal.subject_id,
            tenant_id=principal.tenant_id,
        )
        if not set(required).issubset(granted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permission",
            )
        return principal

    return dependency


CanReadOrders = Annotated[
    Principal,
    Depends(require_permissions(Permission.ORDER_READ)),
]
```

This handles an endpoint-level permission. It does not replace resource-level policy. Avoid evaluating the same membership query in several nested dependencies; cache only within the request or through an invalidation-aware policy cache.

For a small codebase, an in-process policy service is usually clearer than a separate policy engine. A policy engine becomes useful when many services need one expressive policy language, centralized review, and decision logs. It adds availability, latency, policy rollout, and debugging concerns. Keep enforcement in every service even when decision logic is external.

## Resource-level authorization

Broken object-level authorization occurs when an API accepts an object ID and performs an action without checking that the principal can access that object. UUIDs do not solve it.

### Scope the lookup

```python
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_tenant_order(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    order_id: UUID,
) -> Order:
    stmt = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.id == order_id,
        Order.deleted_at.is_(None),
    )
    order = (await session.scalars(stmt)).one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order not found",
        )
    return order
```

Filtering by both tenant and ID is safer than loading by global ID and checking later. It avoids accidental disclosure and reduces the chance a later refactor forgets the comparison.

For owner or collaborator policy, push the authorization predicate into SQL:

```python
stmt = (
    select(Document)
    .outerjoin(
        DocumentGrant,
        (DocumentGrant.document_id == Document.id)
        & (DocumentGrant.subject_id == principal.subject_id),
    )
    .where(
        Document.tenant_id == principal.tenant_id,
        Document.id == document_id,
        (Document.owner_id == principal.subject_id)
        | (DocumentGrant.can_edit.is_(True)),
    )
)
```

For a collection endpoint, the same policy predicate must filter every returned row. Checking permission after fetching a page can produce short pages, wrong totals, data-dependent timing, and accidental serialization of forbidden rows.

### Separate capability from state transition

Permission to refund orders does not mean every order can be refunded. The service must also enforce order ownership/tenant, payment state, refund limits, and separation-of-duty rules.

```python
async def refund_order(
    session: AsyncSession,
    principal: Principal,
    order_id: UUID,
) -> RefundResult:
    async with session.begin():
        order = await order_repository.lock_authorized_for_refund(
            session,
            principal=principal,
            order_id=order_id,
        )
        if order.status != OrderStatus.PAID:
            raise InvalidOrderStateError
        if order.created_by == principal.subject_id and policy.requires_dual_control:
            raise SeparationOfDutiesError

        return await refunds.create(session, order=order, actor=principal)
```

When membership or resource state can change concurrently, check and mutate in one transaction at the isolation and locking level the invariant needs. A permission check performed minutes before a write is a time-of-check/time-of-use gap.

### ACL, ABAC, and relationship-based policy

- RBAC assigns permission bundles to roles. It is understandable and works well for organizational capabilities.
- ACLs attach principals or groups to individual resources. They are precise but can become large and difficult to audit.
- Attribute-based access control evaluates subject, resource, action, and context attributes. It is expressive but policy interactions become harder to explain.
- Relationship-based access control derives permission from graph relationships such as owner, parent team, or shared folder. It suits collaboration products but needs careful consistency and traversal limits.

Most systems combine these. For example, RBAC grants `document:read`, tenant membership establishes the boundary, and an ownership or sharing relationship grants access to one document. Write down precedence, especially for explicit denies and inherited grants.

## Multi-tenancy models

Multi-tenancy means one system serves multiple customer security boundaries. Tenant isolation includes data, caches, files, search, queues, logs, metrics, quotas, backups, and support tooling, not only SQL rows.

| Model | Isolation | Operational cost | Typical fit |
| --- | --- | --- | --- |
| Shared database, shared schema, `tenant_id` per row | Application and optional row-policy isolation | Lowest migration and connection overhead | Many small tenants with common schema |
| Shared database, schema per tenant | Namespace separation | Migrations and search-path management grow with tenants | Moderate tenant count with schema isolation requirements |
| Database per tenant | Stronger database boundary and independent restore | Connection pools, migrations, monitoring, and routing are expensive | Large or regulated tenants, data residency, custom lifecycle |
| Hybrid tiers | Matches cost to customer needs | Routing and feature parity become more complex | Broad customer size or compliance range |

No model eliminates application authorization. A database-per-tenant deployment can still route a request to the wrong database.

### Tenant resolution

Resolve tenant context from authenticated, server-validated state. A subdomain, path value, or `X-Tenant-ID` header is a request hint, not proof of membership.

A safe switch flow is:

1. Authenticate the subject.
2. Receive the requested tenant identifier.
3. Verify active membership and any client restrictions.
4. create a new session context or short-lived token bound to that tenant.
5. Audit the switch.

One operation should have one immutable tenant context. Avoid letting nested repository calls accept arbitrary tenant IDs from request models.

Validate hostnames against trusted configuration before subdomain-based resolution. Do not build password-reset links or issuer URLs from an untrusted `Host` or forwarded header. Configure proxy trust explicitly.

## Shared-schema database design

Put `tenant_id NOT NULL` on every tenant-owned table, including join tables, idempotency records, audit rows, outbox events, and background-job state. Include it in common indexes and uniqueness constraints:

```sql
ALTER TABLE projects
    ADD CONSTRAINT projects_tenant_id_id_uq UNIQUE (tenant_id, id);

ALTER TABLE tasks
    ADD CONSTRAINT tasks_project_tenant_fk
    FOREIGN KEY (tenant_id, project_id)
    REFERENCES projects (tenant_id, id)
    ON DELETE CASCADE;

CREATE UNIQUE INDEX projects_tenant_slug_uq
ON projects (tenant_id, slug)
WHERE deleted_at IS NULL;
```

The composite foreign key prevents a task in tenant A from pointing to a project in tenant B. The unique index allows two tenants to use the same slug while protecting uniqueness inside each tenant.

A repository base class that adds tenant filters can reduce repetition, but hidden query mutation is not proof of isolation. Raw SQL, joins, bulk updates, new repositories, and maintenance scripts can bypass it. Prefer explicit predicates plus database constraints and tests.

### PostgreSQL row-level security

PostgreSQL row-level security (RLS) can add a database enforcement layer:

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE ROW LEVEL SECURITY;

CREATE POLICY orders_tenant_isolation ON orders
USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
```

Set context transaction-locally after beginning the transaction:

```python
from sqlalchemy import text


async def set_tenant_context(
    session: AsyncSession,
    tenant_id: UUID,
) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
```

The third argument to `set_config` makes the value local to the transaction. This is critical with pooled connections. Set it at every transaction boundary before tenant data is accessed, and fail closed when it is absent.

RLS needs careful threat modeling and testing:

- table owners normally bypass RLS unless forced;
- roles with `BYPASSRLS` bypass policies;
- privileged migrations and maintenance jobs need separate, explicit roles;
- policy expressions affect query planning and performance;
- views, functions, foreign keys, backups, and replication need review;
- a connection-local setting can leak across requests if it is not transaction-local and reset;
- RLS does not isolate caches, files, search indexes, or downstream APIs.

Use a minimally privileged application database role. RLS is defense in depth, not a reason to remove tenant predicates from application queries.

## Isolation beyond PostgreSQL

### Caches

Every tenant-owned cache key includes tenant and authorization-relevant dimensions:

```text
v3:tenant:<tenant-id>:project:<project-id>:viewer-class:<class>
```

A globally keyed `project:<id>` cache can return another tenant's object if IDs collide or routing fails. Do not cache an authorization decision longer than the membership/role staleness policy. Invalidation events must themselves carry verified tenant context.

### Object storage and uploads

Use server-generated object keys under tenant prefixes, but do not rely on a prefix alone. Record ownership in the database and authorize every upload completion, download, and signed-URL creation. Keep signed URLs short-lived and scope them to one object and operation. Storage credentials used by the API should be limited by bucket and action.

### Search

Index tenant identity as a mandatory field and add it to every search filter in trusted server code. Search results are another list authorization path. Indexing delay means deleted or newly restricted content may remain discoverable; define deletion and permission-update propagation behavior.

### Queues and jobs

A job payload carries an immutable tenant ID and actor/system context. The worker reloads current authorization if the action requires it. Do not let a user-controlled payload select arbitrary storage credentials or database routing. Dead-letter queues and retries must retain tenant metadata without exposing sensitive payloads.

### Observability

Tenant identifiers are useful log and metric dimensions, but raw high-cardinality tenant IDs can overwhelm metric systems or expose customer information. Put tenant ID in access-controlled structured logs and traces; use bounded tiers or sampled dimensions for metrics. Never put access tokens or secrets in any of them.

## Administrative and support access

Platform operators are a distinct security domain. Avoid a universal `is_superuser` branch scattered across code.

Elevated access should be:

- granted through a separate, narrowly scoped role;
- protected by strong and recent authentication;
- time-bound and approval-bound where risk warrants it;
- explicit about target tenant and reason;
- visible to the operator throughout the session;
- fully audited, with alerts for sensitive actions;
- unable to silently impersonate a customer identity.

For support impersonation, retain both the real operator and effective subject in the principal and audit record. Do not issue an indistinguishable customer token.

Background maintenance should use named system principals with purpose-specific permissions, not `subject_id = NULL` as a magic bypass.

## Audit authorization decisions

High-value audit records commonly include:

- event time and request/correlation ID;
- real actor and effective actor;
- tenant, action, and resource type/ID;
- allow or deny decision and stable reason code;
- authentication method and recent-auth status;
- relevant role/policy version;
- source service and safe network/device context.

Audit logs must be access-controlled, integrity-protected, retained according to policy, and scrubbed of secrets and unnecessary personal data. An audit log that an application administrator can silently rewrite is weak evidence.

## Common failure modes

**Checking a role in the router only**

Workers, GraphQL resolvers, internal calls, and future endpoints bypass it. Enforce core policy in the service or policy layer and use route dependencies for early rejection.

**Loading by ID, then checking tenant**

One missed check becomes cross-tenant access. Scope the lookup itself and return a non-revealing result.

**Trusting tenant ID from a header**

The client selects another tenant. Treat it only as a requested context and verify membership server-side.

**Caching by resource ID only**

Authorized data crosses tenants or viewer classes. Namespace and include authorization dimensions.

**Long-lived permissions in JWTs**

Removed users retain access until token expiry. Shorten tokens or consult revocable current state according to risk.

**A role called `admin` means everything**

Privilege grows invisibly and violates least privilege. Use explicit permissions and separate tenant, billing, security, and platform administration.

**Bulk endpoint checks only the first object**

Mixed authorized and unauthorized IDs leak or mutate data. Apply authorization to the whole SQL operation and define all-or-nothing or per-item results.

**RLS connection context leaks**

A pooled connection retains tenant A for tenant B. Use transaction-local context, transaction tests, and a fail-closed policy.

## Testing authorization

Create a policy matrix before writing tests:

| Principal | Same tenant | Permission | Relationship | Expected |
| --- | --- | --- | --- | --- |
| Anonymous | N/A | N/A | N/A | 401 |
| Member | Yes | Yes | Allowed | Success |
| Member | Yes | No | Allowed | 403 |
| Member | Yes | Yes | Not allowed | 404 or 403 by policy |
| Member | No | Yes in own tenant | Any | Non-revealing 404 |
| Disabled member | Yes | Formerly yes | Any | Deny |
| Support actor | Explicit elevation | Narrow grant | Target tenant | Success and audit |

Exercise every operation type: get, list, search, count, create with parent IDs, update, delete, bulk mutation, export, file access, and background processing.

Include tests that:

- substitute another tenant's UUID in every path and body identifier;
- combine same-tenant parent IDs with cross-tenant child IDs;
- verify pagination cursors cannot switch tenant or filter scope;
- change membership during a session and measure revocation behavior;
- attempt mass assignment of owner, tenant, and role fields;
- verify cache keys and invalidation events contain tenant context;
- run RLS checks using the actual minimally privileged application role;
- verify missing RLS context returns no rows and rejects writes;
- ensure support actions retain real actor identity in audits.

Static route tests are insufficient. Test repository/service entry points and worker handlers because HTTP is only one caller.

## Interview discussion

**RBAC versus ABAC?**

RBAC is easier to explain and administer for stable job capabilities. ABAC handles context and resource attributes but creates more complex policy interactions. Mature systems often use RBAC for coarse capability and explicit resource or attribute checks for the final decision.

**How do you prevent cross-tenant access?**

Derive tenant context from authenticated membership, include `tenant_id` in every owned row and query, use composite constraints, namespace non-database systems, test adversarial substitutions, and optionally add PostgreSQL RLS under a non-bypass role.

**Is a random UUID an authorization control?**

No. It reduces easy enumeration but can leak through logs, links, analytics, or another endpoint. Every object access still requires authorization.

**What is the risk of permissions in a JWT?**

They remain valid until expiry even after membership changes, propagate sensitive structure, and can diverge across services. State the accepted staleness or perform a current-state check for sensitive actions.

**When would you choose database-per-tenant?**

When isolation, residency, independent backup/restore, or very large-tenant workload control justifies routing, pool, migration, and operational cost. It is an infrastructure boundary, not a replacement for authorization.

## Authoritative references

- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP API Security Top 10: Broken Object Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/)
- [OWASP API Security Top 10: Broken Function Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa5-broken-function-level-authorization/)
- [PostgreSQL row security policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL `CREATE POLICY`](https://www.postgresql.org/docs/current/sql-createpolicy.html)
- [NIST RBAC model](https://csrc.nist.gov/projects/role-based-access-control)
