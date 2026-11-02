# ADR-18: Advisors

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26 and 2026-11-02
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (plan 07)

## Context

PMM Advisors run checks against each service and report failures by severity, security checks included. `/v1/advisors` requires the Editor Grafana role (`auth_server.go:84-86`) [V]. `ListFailedServices` and `GetFailedChecks` (`managed/services/management/checks.go:54`, `:117`) return results for every service, with no Access Role filter [V].

## Options

1. Open the Advisor reads to Viewers. Rejected: a PMM-wide permission change, for results that include security findings.
2. Keep Editor, and narrow the results in MCP to the caller's service list (ADR-03).
3. Keep Editor, and apply Access Roles in the Advisors API with a PMM-wide matcher (ADR-16). Rejected for this epic: ADR-16 is deferred.
4. Leave Advisors out of MCP. Rejected: failed checks are part of a triage.

## Decision

Option 2.
- **Source.** `pmm_advisors` calls the existing `GET /v1/advisors/checks/failed` with the caller's credentials (ADR-03); the role stays Editor.
- **Narrowing.** MCP keeps the results whose service is in the caller's list (ADR-08), and summaries count only those. A result for a service outside the list is dropped.
- Narrowed, not filtered: not a security boundary (ADR-03). Filtering Advisor results by Access Role is PMM-wide work (ADR-16, deferred).
- **Tool.** `pmm_advisors` returns failed checks per service: the check, its severity, summary, description and read-more link. It filters by service and severity, and pages (ADR-11). With Advisors disabled in PMM's settings, it answers `invalid_input` with "Advisors are disabled in PMM's settings".
- **Read only.** Running checks (`checks:start`) and changing them stay out (ADR-05).

## Consequences

- A Viewer token gets `unauthorized` from `pmm_advisors`; `mcp.md` says that Advisors need an Editor token.
- To use `pmm_advisors`, users give an AI client an Editor token, which can also create alert rules, change and run Advisor checks, and write Grafana dashboards, rules and silences [I]. The implementation review lists the full surface. `mcp.md` recommends a separate Editor token used only where Advisor results are needed. This is a risk the security review accepts or rejects.
- Advisor texts are returned as written (ADR-07). Their exposure to a model provider is part of the security review.
