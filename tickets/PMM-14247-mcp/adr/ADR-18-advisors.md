# ADR-18: Advisors

- Status: Proposed
- Date: 2026-10-24
- Tickets: PMM-14247, PMM-15790, PMM-15531
- Implemented: not yet (API in phase 4, tool in phase 2b)

## Context

PMM Advisors run checks against each service and report failures by severity, security checks included. `/v1/advisors` requires Editor (`auth_server.go:84-86`). `ListFailedServices` and `GetFailedChecks` (`managed/services/management/checks.go:54`, `:117`) return results for every service, with no Access Role filter.

## Options

1. Open the Advisor reads to Viewers.
2. Keep Editor, and apply Access Roles to the results (ADR-16).
3. Leave Advisors out of MCP.

## Decision

Option 2.
- **API.** `GET /v1/advisors/failedServices` and `GET /v1/advisors/checks/failed` apply ADR-16's matcher to each result's service. Summaries count visible results only. The role stays Editor.
- **Tool.** `pmm_advisors` returns failed checks per service: the check, its severity, summary, description and read-more link. It filters by service and severity, and pages (ADR-11). With Advisors disabled in PMM's settings, it says so; the contract sets the code.
- **Read only.** Running checks (`checks:start`) and changing them stay out (ADR-05).

Option 1 would be a second PMM-wide permission change, for results that include security findings.

## Consequences

- An Editor with a restricted role sees only their services' results, in the PMM UI too.
- A Viewer token gets `unauthorized` from `pmm_advisors`; `mcp.md` says that Advisors need an Editor token.
- Advisor texts are returned as written (ADR-07). Their exposure to a model provider is part of the security review.
