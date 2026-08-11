# Application Security for FastAPI Services

Application security is the discipline of preserving confidentiality, integrity, and availability across every trust boundary. Framework validation is one control. It does not address authorization, unsafe database queries, browser behavior, secret leakage, unbounded work, vulnerable dependencies, or malicious files.

Start with a lightweight threat model for each material feature:

1. What data and operations are valuable?
2. Which users, services, networks, and stores cross trust boundaries?
3. How could an attacker spoof, tamper, disclose, exhaust, or deny them?
4. Which controls prevent, detect, and help recover from those outcomes?
5. What evidence will show the controls still work?

Revisit the model for authentication, file processing, webhooks, tenant isolation, administrative tooling, and every integration that fetches a user-supplied URL.

## Validation and data minimization

Pydantic validates structure and types at the HTTP boundary. Domain invariants and authorization still belong in services and the database.

```python
from pydantic import BaseModel, ConfigDict, Field


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=100)
    biography: str | None = Field(default=None, max_length=2000)
```

Separate input models by use case. Binding a request directly to an ORM model can let clients mass-assign `tenant_id`, `owner_id`, `role`, `is_admin`, price, or workflow state. `extra="forbid"` makes an unexpected security-sensitive field an error instead of silently ignoring it.

Validation principles:

- allow known formats, lengths, ranges, counts, and enum values;
- canonicalize once where identity depends on canonical form;
- preserve the original where evidence or display requires it;
- avoid regexes with catastrophic backtracking;
- set aggregate limits, not only per-field limits;
- validate again when data crosses into a different interpreter or trust domain.

Rejecting unexpected input also controls cost. A valid list of one million UUIDs is still an availability problem.

Return only fields in a dedicated response model. An ORM entity can contain password hashes, recovery state, internal risk scores, deleted flags, or tenant metadata that should never be serialized.

## SQL injection

SQL injection occurs when untrusted input changes SQL syntax rather than remaining data. Use SQLAlchemy expressions or driver parameters:

```python
stmt = select(User).where(
    User.tenant_id == principal.tenant_id,
    User.normalized_email == normalized_email,
)
user = await session.scalar(stmt)
```

Do not do this:

```python
# Vulnerable: the value becomes part of SQL syntax.
statement = text(f"SELECT * FROM users WHERE email = '{email}'")
```

Parameters protect values. Column names, table names, operators, and sort direction usually cannot be bound as values, so select them through fixed mappings:

```python
SORT_FIELDS = {
    "created_at": User.created_at,
    "display_name": User.display_name,
}

sort_column = SORT_FIELDS[requested_sort]
stmt = select(User).order_by(sort_column.asc(), User.id.asc())
```

Stored procedures and query builders can still be vulnerable if they concatenate SQL. Least-privileged database roles limit impact but do not make injection acceptable. The application role should not own tables, bypass row security, create extensions, or perform migrations.

Test malicious metacharacters as ordinary data and review every use of `text()`, raw driver calls, and dynamic identifiers. Do not expose raw database errors to clients.

## Command, template, and path injection

The same principle applies whenever data enters an interpreter.

- Pass subprocess arguments as a sequence and keep shell execution disabled.
- Do not construct shell pipelines from upload names or URLs.
- Use template autoescaping and never treat user input as template source.
- Use a safe YAML loader and never unpickle untrusted data.
- Use server-generated storage keys rather than joining an upload filename to a filesystem path.
- Resolve and verify a filesystem target remains inside an intended directory before access.

```python
import subprocess

result = subprocess.run(
    ["file", "--brief", "--mime-type", trusted_temporary_path],
    check=True,
    capture_output=True,
    text=True,
    timeout=5,
    shell=False,
)
```

Even without `shell=True`, an invoked program may interpret option-like filenames. Use `--` where the program supports it, generate paths yourself, and isolate high-risk parsers.

## Cross-site scripting

XSS is execution of attacker-controlled script in a browser under a trusted origin. JSON APIs can participate in XSS when their data is inserted into HTML, returned with a misleading content type, or displayed by an administrative frontend.

Controls belong at the output context:

- use framework escaping for HTML text and attribute contexts;
- avoid injecting JSON into inline scripts;
- sanitize user-authored rich HTML with a maintained allowlist sanitizer;
- use `Content-Type: application/json` and `X-Content-Type-Options: nosniff`;
- deploy a restrictive Content Security Policy for HTML frontends;
- avoid dangerous DOM sinks such as `innerHTML` for untrusted strings;
- protect cookies with `HttpOnly`, while recognizing that XSS can still send authenticated requests.

Do not globally HTML-escape data before database storage. Encoding depends on whether the output is HTML text, an attribute, JavaScript, CSS, or a URL. Early generic encoding corrupts data and can still be wrong for the eventual context.

A backend that renders Jinja templates should rely on autoescaping and review every explicit `safe` operation. Markdown and SVG are active-content risks and require tailored sanitization or isolated delivery.

## CORS is a browser read policy

Cross-Origin Resource Sharing tells browsers which origins may read cross-origin responses. It is not authentication, a firewall, or protection from non-browser clients. A disallowed site may still cause certain requests; the browser mainly blocks its script from reading the response.

Configure exact trusted origins:

```python
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

api = FastAPI()
api.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["api.example.com", "api.internal.example.com"],
)

# Wrap the whole application so error responses also receive CORS handling.
app = CORSMiddleware(
    app=api,
    allow_origins=["https://app.example.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)
```

An origin is scheme, host, and port. `https://app.example.com` and `http://app.example.com` are different. Do not reflect any `Origin` header without an exact allowlist. Wildcard subdomain matching can trust an abandoned or attacker-controlled subdomain.

Credentialed CORS requires explicit origins. Keep methods and headers narrow enough to reveal mistakes during development. Validate production behavior with preflight `OPTIONS` requests and actual credentialed requests.

CORS does not prevent CSRF. HTML forms can send certain cross-origin requests without reading the response, and cookie credentials can be attached automatically.

## CSRF for cookie-authenticated applications

Cross-Site Request Forgery makes a browser send an authenticated request chosen by another site. It matters when credentials are attached automatically, especially cookies and some client-certificate deployments.

Use several controls:

- no state changes through `GET`, `HEAD`, or `OPTIONS`;
- `SameSite=Lax` or `Strict` cookies when product flows allow it;
- a server-bound synchronizer token or correctly signed double-submit token;
- exact `Origin` validation on unsafe methods, with a carefully defined fallback policy;
- custom request headers for JavaScript clients, combined with narrow CORS;
- recent authentication for highly sensitive changes.

Example synchronizer-token dependency:

```python
import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def require_csrf(
    request: Request,
    browser_session: Annotated[BrowserSession, Depends(get_browser_session)],
) -> None:
    if request.method in SAFE_METHODS:
        return

    supplied = request.headers.get("X-CSRF-Token")
    if supplied is None or len(supplied) > 512:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")

    supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
    if not hmac.compare_digest(supplied_digest, browser_session.csrf_digest):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")

    origin = request.headers.get("Origin")
    if origin != "https://app.example.com":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")
```

Generate the CSRF token with a cryptographic random generator, bind its digest to the server-side session, and rotate it with session trust changes. For form submissions, accept the same token in a form field. Define how clients without an `Origin` header are handled rather than silently skipping the check.

A bearer token explicitly placed in an `Authorization` header is not automatically attached by a normal cross-site form, so traditional CSRF risk differs. XSS and token theft remain. If the bearer token is stored in a cookie, cookie CSRF rules apply.

## Security headers and transport

Terminate only modern TLS at a trusted edge and preserve end-to-end encryption according to the network threat model. Redirecting HTTP is helpful for navigation but does not make a credential already sent over HTTP secret. Clients should begin with HTTPS.

Useful response headers depend on content:

- `Strict-Transport-Security` at the HTTPS edge after deployment is ready for its scope;
- `X-Content-Type-Options: nosniff`;
- a restrictive `Content-Security-Policy` for HTML;
- `Referrer-Policy` appropriate to the frontend;
- `Cache-Control: no-store` for responses containing credentials or highly sensitive data;
- clickjacking protection through CSP `frame-ancestors` for HTML.

Do not add browser headers blindly to every API response and assume the application is secure. HSTS and CSP need deployment-specific review. Configure which reverse proxies are trusted to supply forwarded scheme and client address. An attacker-controlled forwarded header can corrupt HTTPS redirects, origin checks, rate limits, and audit records.

Disable or protect interactive API documentation in environments where it exposes sensitive operations or schemas. Security through obscurity is not the goal; reducing unauthenticated attack surface is.

## Secrets management

Secrets include database credentials, API keys, cookie keys, JWT signing keys, webhook secrets, encryption keys, and third-party credentials.

Production rules:

- never commit secrets to Git, images, example configuration, test fixtures, or generated documentation;
- obtain them from a managed secret store or workload identity at runtime;
- grant each workload only the secrets and actions it needs;
- separate development, staging, and production credentials;
- keep secrets out of command arguments, URLs, exception messages, logs, traces, and metrics;
- support rotation with an overlap window where protocols require it;
- inventory owners, consumers, expiry, and last rotation;
- revoke and investigate exposed secrets instead of merely deleting the Git line.

Environment variables are a delivery mechanism, not a complete secret manager. They can leak through diagnostics, child processes, crash reports, or platform visibility. Use platform facilities appropriate to the threat model and restrict who can inspect workloads.

Pydantic's `SecretStr` reduces accidental string representation, but application code can still reveal it:

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    database_url: SecretStr
    cursor_signing_key: SecretStr
```

Never log `settings.model_dump()` wholesale. Build an explicit safe startup summary such as environment name, feature flags, and non-secret endpoints.

Secret scanning in CI and pre-commit hooks is useful, but it is detection, not permission to commit realistic credentials. Keep an incident playbook for history rewriting, rotation, dependent-system review, and notification.

## File uploads

An upload is untrusted bytes, an untrusted filename, and often an expensive parser request. Validate at multiple layers.

### Layered controls

1. Reject excessive request bodies at the CDN, reverse proxy, or ASGI boundary before application parsing.
2. Require authentication, authorization, tenant quota, and rate/concurrency limits.
3. Cap multipart part count, field size, file count, and total bytes.
4. Ignore the client filename for storage; retain a sanitized display name only if needed.
5. Check extension and declared type as weak signals, then inspect file signatures/content.
6. Stream into a private quarantine area with a byte counter and digest.
7. Scan and parse in an isolated worker with CPU, memory, time, and decompression limits.
8. Promote only accepted content to a non-executable private store.
9. Serve downloads with authorization, safe content type, and `Content-Disposition`.

`UploadFile` avoids loading the entire file into Python memory, but by the time a route runs the multipart parser may already have accepted and spooled the body. Edge and parser limits remain necessary.

```python
import hashlib
from dataclasses import dataclass
from typing import Protocol

from fastapi import UploadFile

CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class UploadTooLargeError(Exception):
    pass


class AsyncObjectSink(Protocol):
    async def write(self, chunk: bytes) -> None: ...
    async def finish(self) -> str: ...
    async def abort(self) -> None: ...


@dataclass(frozen=True, slots=True)
class StoredUpload:
    size: int
    sha256_hex: str
    object_key: str


async def stream_to_quarantine(
    upload: UploadFile,
    sink: AsyncObjectSink,
) -> StoredUpload:
    digest = hashlib.sha256()
    size = 0

    try:
        while chunk := await upload.read(CHUNK_SIZE):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise UploadTooLargeError
            digest.update(chunk)
            await sink.write(chunk)

        object_key = await sink.finish()
        return StoredUpload(
            size=size,
            sha256_hex=digest.hexdigest(),
            object_key=object_key,
        )
    except Exception:
        await sink.abort()
        raise
    finally:
        await upload.close()
```

The sink should use a server-generated tenant-scoped key and private access policy. On limit failure, clean up partial multipart uploads and temporary files.

Content-type headers and extensions are attacker-controlled. File signatures improve detection but do not prove safety. Archives can expand far beyond compressed size or contain traversal paths. Images, PDFs, office files, audio/video codecs, and antivirus engines are substantial parsers and should run outside the request process when risk or cost warrants it.

For direct-to-object-storage uploads, issue a short-lived policy restricted to one generated key, size range, and expected operation. A client-reported completion does not prove the object is valid. The server must inspect stored metadata, scan it, and change database state from `quarantined` to `ready` only after checks pass.

Serve user HTML and SVG from a separate untrusted origin or force download. Do not make an uploaded filename part of a response header without safe encoding.

## Rate limits, concurrency limits, and quotas

Rate limiting controls request frequency. It cannot replace authentication, authorization, input bounds, or capacity planning.

Choose keys based on abuse and cost:

- account or subject for login and user actions;
- API key or OAuth client for integrations;
- tenant for fair shared-resource use;
- IP/network as one signal, recognizing NAT and proxy behavior;
- route and operation cost;
- global protection for an endangered dependency.

A token bucket permits controlled bursts. A sliding window gives closer adherence to a rolling rate. Fixed windows are simple but permit boundary bursts. Distributed replicas need an atomic shared decision, often a Redis script or a gateway facility. An in-process dictionary enforces a different limit per worker and loses state on restart.

Return `429 Too Many Requests` and a useful `Retry-After` when the client can safely retry. Avoid revealing sensitive account existence through different rate-limit behavior.

Also cap concurrency. Ten simultaneous 30-second report queries can be more damaging than one hundred cached GET requests. Use per-tenant semaphores/leases, worker queues, database statement timeouts, and workload isolation for high-cost tasks.

Decide failure behavior per control:

- failing open preserves availability but removes protection;
- failing closed protects a sensitive operation but can turn limiter failure into an outage;
- local emergency limits provide imperfect fallback.

Authentication, password reset, payment, and expensive AI/file operations often deserve a conservative policy. Health checks and internal recovery paths need separate treatment. Monitor allowed, denied, store errors, decision latency, and top bounded dimensions without creating high-cardinality metric explosions.

Client IP is trustworthy only after the application is configured with the exact proxy chain it trusts. Never accept the leftmost `X-Forwarded-For` value from any caller by default.

## SSRF and outbound requests

Server-Side Request Forgery occurs when the application fetches an attacker-influenced destination. It can reach cloud metadata, internal admin services, localhost, or privileged network paths.

Prefer identifiers over arbitrary URLs. If arbitrary fetching is necessary:

- allow only required schemes, normally HTTPS;
- use an allowlist of destinations where possible;
- resolve DNS and reject loopback, private, link-local, multicast, and reserved IPv4 and IPv6 ranges;
- defend against DNS rebinding by controlling resolution and the actual connected address;
- revalidate every redirect or disable redirects;
- cap redirects, response bytes, decompressed bytes, and total time;
- use network egress policy so application validation is not the only barrier;
- use a dedicated HTTP client without ambient cloud or internal credentials;
- do not reflect detailed connection failures.

String checks such as blocking URLs containing `127.0.0.1` are inadequate. Alternate IP encodings, IPv6, redirects, and attacker-controlled DNS bypass them.

## Webhook verification and replay

Verify webhook signatures over the exact raw body before parsing or modifying it. Bind the signature to a timestamp or provider event ID, enforce a narrow replay window, and store processed event IDs under a unique constraint.

```python
import hashlib
import hmac


def verify_webhook(
    *,
    raw_body: bytes,
    timestamp: str,
    supplied_signature: str,
    secret: bytes,
) -> bool:
    signed = timestamp.encode("ascii") + b"." + raw_body
    expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)
```

Follow the provider's exact canonicalization and signature specification instead of inventing this illustrative format. Store receipt durably, acknowledge within the provider timeout, and process idempotently in a worker when handling can be slow. Signature validation proves possession of the shared secret, not that the event is new.

## Errors, logs, and observability

Client responses should use stable public errors and never include stack traces, SQL, filesystem paths, secret values, or internal hostnames. Log enough safe context to investigate:

- request/correlation ID;
- authenticated subject, tenant, and credential fingerprint, not credential;
- route template, status, duration, and response size;
- authorization decision and stable reason;
- rate-limit decision;
- dependency error class and safe operation identifier.

Redact `Authorization`, cookies, passwords, API keys, session IDs, signed URLs, reset tokens, CSRF tokens, and sensitive body fields at ingestion. Redaction after data reaches several sinks is unreliable. Limit body logging by default and use allowlists for fields.

Protect logs from unauthorized reading and tampering, define retention, and avoid alert rules that include raw request bodies. Security events need synchronized clocks and correlation across edge, application, database, and workers.

## Dependencies and build integrity

A service inherits vulnerabilities from Python packages, base images, system libraries, JavaScript documentation assets, and build actions.

- Lock direct and transitive dependencies with hashes where tooling supports it.
- Update intentionally and review security advisories from authoritative sources.
- Build from minimal maintained base images and rebuild for patched system packages.
- Generate a software bill of materials when organizational risk warrants it.
- Verify artifact provenance and deploy immutable images.
- Run containers and processes as a non-root user with a read-only filesystem where feasible.
- Remove compilers, package caches, test secrets, and development servers from runtime images.
- Separate dependency vulnerability findings from exploitability and remediation urgency.

Automated scanners produce both gaps and false positives. They supplement code review, threat modeling, tests, and incident readiness.

## Security testing strategy

Security tests should be ordinary regression tests, not a one-time penetration-test artifact.

### Request boundary

- extra privileged fields are rejected;
- boundary sizes and aggregate counts are enforced;
- malformed JSON, multipart, encodings, and duplicate parameters fail predictably;
- content types are enforced;
- error responses contain no internals.

### Browser behavior

- allowed and denied CORS preflights behave as configured;
- credentialed responses never use an unsafe wildcard origin;
- state-changing cookie requests fail without a valid CSRF token and origin;
- cookies carry expected flags;
- rendered untrusted content is encoded or sanitized by context;
- security headers are present on success and error responses where intended.

### Injection and outbound access

- SQL metacharacters remain bound data;
- sort/filter identifiers come only from allowlists;
- filenames cannot traverse directories or become shell options;
- SSRF tests cover redirects, IPv4, IPv6, DNS changes, response limits, and cloud metadata ranges;
- untrusted serialized input never reaches unsafe deserializers.

### Upload and availability

- edge and application byte limits agree;
- oversized, truncated, polyglot, misleading-type, and nested archive samples are quarantined or rejected;
- parser time/memory failures cannot take down request workers;
- partial uploads are cleaned;
- distributed rate limits remain atomic under concurrent tests;
- per-tenant quotas and concurrency isolation prevent one tenant from exhausting shared work.

### Operational controls

- secrets do not appear in Git history, images, logs, traces, or exception reporting;
- rotation overlap and retirement work;
- the application database and cloud identities cannot perform administrative actions;
- backups, revocation, and incident procedures are exercised.

Use dependency-aware dynamic testing against a staging environment that mirrors proxy, TLS, CORS, storage, and identity configuration. A local `TestClient` cannot prove edge request-size enforcement or forwarded-header trust.

## Common failure modes

**`allow_origins=["*"]` during development reaches production**

The browser trust boundary is broader than intended. Use environment-specific exact allowlists and configuration tests.

**CORS is treated as CSRF protection**

Some cross-origin requests can still be sent even when responses cannot be read. Protect cookie-authenticated unsafe methods with CSRF controls.

**Pydantic validation is treated as SQL injection protection while raw SQL uses f-strings**

Valid strings can still contain SQL syntax. Parameterize values and allowlist identifiers.

**Only the Python route checks upload size**

The proxy or multipart parser already accepted and spooled the body. Enforce limits before and during parsing, then again while streaming.

**Rate limiting by IP only**

Distributed attackers bypass it and shared networks suffer collateral damage. Combine identity, tenant, client, network, cost, and behavior signals.

**Secrets are deleted from the latest commit**

They remain in history and may already be copied. Revoke and rotate first, then follow the repository incident procedure.

**A URL blocklist protects against SSRF**

Redirects, IPv6, DNS rebinding, and alternate representations bypass string blocklists. Combine strict destination policy with network egress controls.

**Detailed exception text is returned to help clients debug**

It exposes schema, paths, dependencies, and sometimes secrets. Return stable public codes and correlate them with protected server diagnostics.

## Interview discussion

**What does CORS protect?**

It controls whether browser scripts from an origin can read cross-origin responses. It does not authenticate clients, block direct HTTP calls, or by itself stop CSRF.

**When is CSRF relevant?**

When the browser automatically attaches credentials to a request, especially cookies. Use safe-method semantics, SameSite, an anti-CSRF token, and origin validation appropriate to the client architecture.

**How would you secure file uploads?**

Apply edge and parser size limits, authenticate and quota the caller, stream to private quarantine under a generated name, inspect actual content, scan and parse in isolation, protect against archive bombs, then promote only accepted content and authorize every download.

**How do you prevent SQL injection in dynamic sorting?**

Bound parameters handle values, not identifiers. Map a small public enum to known SQLAlchemy columns and direction methods. Never concatenate the client string.

**Would a rate limiter fail open or closed?**

It depends on the operation and threat model. A sensitive credential endpoint may fail closed; a low-risk read may use a local fallback. The decision should be explicit, monitored, and tested under limiter-store failure.

## Authoritative references

- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP Cross Site Scripting Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [OWASP Server Side Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
- [Starlette middleware documentation](https://www.starlette.io/middleware/)
- [FastAPI request files](https://fastapi.tiangolo.com/tutorial/request-files/)
- [HTTP `429 Too Many Requests`, RFC 6585](https://www.rfc-editor.org/rfc/rfc6585#section-4)
