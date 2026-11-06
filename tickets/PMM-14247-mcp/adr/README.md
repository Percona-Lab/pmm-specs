# Architecture decision records

This folder records the architecture decisions for PMM's MCP endpoint (epic [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247)). Each file records one decision, with the rules that make it up.

**Format.** Each record has these sections:
- **Context:** why a decision was needed;
- **Options:** what was considered; each rejected option says why it was rejected;
- **Decision:** what was chosen;
- **Consequences:** what follows from it, good and bad.

The header gives the status, the date, the Jira tickets involved, and where the decision is implemented. **Replaces:** names a document the record takes over, when there is one.

**References:** `#NNNN` is a pull request in percona/pmm; `pmm-specs#N` one in this repository.

**Marks:** **[V]** means verified by reading the code, the ticket or the pull request; **[I]** means inferred, or taken from upstream documentation, and not run.

**Numbers** such as caps and limits are in [spec §8](../spec.md#8-phase-3-output-contract); a record states the mechanism and points there, so tuning a value doesn't need a new record.

**Statuses:**
- **Proposed:** written and waiting for review by the PMM architects.
- **Accepted:** reviewed and in force.
- **Deferred:** taken out of this epic; the record stays as input for the ticket named in it, and opens with a `## Deferred` section saying why and what that ticket must settle.
- **Superseded by ADR-NN:** replaced; the record stays for history.

**Rules:**
- Never rewrite an accepted record to change its decision. Add a new ADR that supersedes it.
- Number records in sequence, as `ADR-NN-short-title.md`.

## Index

ADR-01 to ADR-10 started from decisions that were taken in the epic, in pull requests, and in `managed/services/mcp/DECISIONS.md` on `PMM-MCP-GA`, and that are implemented there. None had an architect review, so they started as Proposed; the review of this folder in [pmm-specs#4](https://github.com/Percona-Lab/pmm-specs/pull/4) served as their architect review. pmm-specs#4 was approved and merged on 2026-11-05, and ADR-01 to ADR-04, ADR-06 to ADR-09 and ADR-11 to ADR-15 were accepted the same day. ADR-05, ADR-10, ADR-17 and ADR-18 stay Proposed until the open questions in [spec §13](../spec.md#13-risks-and-mitigations) that they depend on are settled; a later pmm-specs PR accepts each. ADR-11 to ADR-18 are new designs from [spec.md](../spec.md). The reviews of pmm-specs#4 revised ADR-03, ADR-05, ADR-08, ADR-10, ADR-15, ADR-17 and ADR-18, and deferred ADR-16.

| ADR | Title | Status | Implemented or planned in |
|---|---|---|---|
| [01](ADR-01-in-server-endpoint.md) | In-server endpoint | Accepted | #5942 |
| [02](ADR-02-base-and-port.md) | Base implementation and what to port | Accepted | #5942, plan 01 |
| [03](ADR-03-api-only-data-path.md) | Data only through the public API; MCP narrows, never widens | Accepted | #5942; narrowing in plans 04, 06 and 07 |
| [04](ADR-04-stateless-streamable-http.md) | Stateless Streamable HTTP | Accepted | #5942 |
| [05](ADR-05-read-only-tools.md) | Read-only tools | Proposed | #5942; limits and cancel in plan 02 |
| [06](ADR-06-off-by-default.md) | Off by default, switched per request | Accepted | #6068 |
| [07](ADR-07-sql-redaction.md) | Redaction of SQL literals | Accepted | #6068, plan 01 |
| [08](ADR-08-inventory-under-access-roles.md) | Service list from Access-Role-filtered metric series | Accepted | Plan 06 |
| [09](ADR-09-metrics-via-datasource-proxy.md) | Metrics through the Grafana datasource proxy | Accepted | #5942 |
| [10](ADR-10-nginx-only.md) | `/mcp` only through nginx, with an Origin check | Proposed | #5942, #6068; Origin check in plan 02 |
| [11](ADR-11-output-contract.md) | Output contract | Accepted | Plan 03 |
| [12](ADR-12-service-accounts-as-principals.md) | Service-account tokens are principals | Accepted | PMM-15534, on `main` |
| [13](ADR-13-access-role-permissions.md) | Access-Role permissions | Accepted | PMM-15791, after the MCP release |
| [14](ADR-14-default-state.md) | Default state at release | Accepted | Off; nothing to change |
| [15](ADR-15-metrics-tools.md) | Metrics tools | Accepted | Plan 05 |
| [16](ADR-16-access-roles-on-pmm-apis.md) | Access Roles on PMM's service-scoped APIs | Deferred | A PMM ticket not yet filed, on `main`, outside this epic |
| [17](ADR-17-alerts.md) | Alerts | Proposed | Plan 07 |
| [18](ADR-18-advisors.md) | Advisors | Proposed | Nothing to build: `pmm_advisors` is out of the Tech Preview |
