# ADR-18: Advisors

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26, 2026-11-02 and 2026-11-06
- Tickets: PMM-14247, PMM-15790
- Implemented: nothing to build; `pmm_advisors` is out of the Tech Preview

## Context

PMM Advisors run checks against each service and report failures by severity, security checks included. `/v1/advisors` requires the Editor Grafana role (`auth_server.go:84-86`) [V]. `ListFailedServices` and `GetFailedChecks` (`managed/services/management/checks.go:54`, `:117`) return results for every service, with no Access Role filter [V].

## Options

1. Open the Advisor reads to Viewers. Rejected: a PMM-wide permission change, for results that include security findings.
2. Keep Editor, and narrow the results in MCP to the caller's service list (ADR-03). Rejected after the security design review, for the reasons under Decision; its design is kept below for a later ticket.
3. Keep Editor, and apply Access Roles in the Advisors API with a PMM-wide matcher (ADR-16). Rejected for this epic: ADR-16 is deferred.
4. Leave Advisors out of MCP. Failed checks are part of a triage, so this costs something.

## Decision

Option 4, after the security design review (spec §3.1): `pmm_advisors` is out of the Tech Preview, and plan 07 doesn't build it.
- **What it would send.** Advisor texts say what a check found, and can carry account details and the security posture of a monitored database. `pmm_advisors` would send them to the model provider as written (ADR-07), with no switch to withhold them.
- **The token it needs.** An Editor token in an AI client also carries write access to alerting (rules, contact points, silences) and to Advisor checks (running and disabling them), while the client reads text that can carry injected instructions (ADR-11). Recommending a separate token doesn't bound what that token can do.

Viewers can already read fleet-wide counts of failed Advisor checks through PMM's metrics. That is accepted, and this decision doesn't change it.

Bringing Advisor results to MCP needs a new ADR that settles both points, for example by withholding descriptions unless an operator opts in.

### Option 2 as designed, kept for a later ticket

- **Source.** `pmm_advisors` calls the existing `GET /v1/advisors/checks/failed` with the caller's credentials (ADR-03); the role stays Editor.
- **Narrowing.** MCP keeps the results whose service is in the caller's list (ADR-08), and summaries count only those. A result for a service outside the list is dropped.
- Narrowed, not filtered: not a security boundary (ADR-03). Filtering Advisor results by Access Role is PMM-wide work (ADR-16, deferred).
- **Tool.** `pmm_advisors` returns failed checks per service: the check, its severity, summary, description and read-more link. It filters by service and severity, and pages (ADR-11). With Advisors disabled in PMM's settings, it answers `invalid_input` with "Advisors are disabled in PMM's settings".
- **Read only.** Running checks (`checks:start`) and changing them stay out (ADR-05).

## Consequences

- No MCP tool needs an Editor token: a Viewer service-account token covers every tool (ADR-08).
- A triage through MCP doesn't see failed Advisor checks; PMM's Advisors page still shows them.
- No Advisor text reaches a model provider through MCP.
