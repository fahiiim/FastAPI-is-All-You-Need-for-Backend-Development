# Security Policy

This repository contains educational reference implementations. They demonstrate security boundaries but are not a supported product and should not be deployed unchanged.

## Reporting a problem

Do not open a public issue for a vulnerability that could place users of a copied example at immediate risk. Use the private security-reporting channel configured on the repository. Include the affected file, conditions, impact, and a minimal reproduction without real credentials or personal data.

If private reporting is not configured on a fork, contact that fork's maintainers directly before public disclosure.

## Scope

Security corrections to documentation and examples are accepted. Dependency vulnerabilities should identify the affected version range and whether the example is actually reachable. A scanner result without exploitability context is useful as a lead, not a completed report.

## Example boundary

Each example README records deliberate omissions. In particular, local credentials, simplified API-key authentication, tutorial schema creation, and development Compose settings are not production defaults. Read the authentication, application-security, deployment, and production-checklist chapters before adapting an example.
