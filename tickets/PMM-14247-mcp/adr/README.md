# Architecture decision records

This folder records the architecture decisions for PMM's MCP endpoint (epic [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247)), one decision per file.

**Format.** Each record has these sections:
- **Context:** why a decision was needed;
- **Options:** what was considered;
- **Decision:** what was chosen;
- **Consequences:** what follows from it, good and bad.

The header gives the status, the date, the Jira tickets involved, and where the decision is implemented.

**Statuses:**
- **Proposed:** written and waiting for review by the PMM architects.
- **Accepted:** reviewed and in force.
- **Superseded by ADR-NN:** replaced; the record stays for history.

**Rules:**
- Never rewrite an accepted record to change its decision. Add a new ADR that supersedes it.
- Number records in sequence, as `ADR-NN-short-title.md`.

## Index

ADR-01 to ADR-10 started from decisions that were taken in the epic, in pull requests, and in `managed/services/mcp/DECISIONS.md` on `PMM-MCP-GA`, and that are implemented there. None had an architect review, so they start as Proposed; the review of this folder is that review. The first review revised ADR-05, ADR-08 and ADR-10. ADR-11 to ADR-18 are new designs from [spec.md](../spec.md).

| ADR | Title | Status | Implemented |
|---|---|---|---|
| [01](ADR-01-in-server-endpoint.md) | In-server endpoint | Proposed | #5942 |
| [02](ADR-02-base-and-port.md) | Base implementation and what to port | Proposed | #5942, phase 2 |
| [03](ADR-03-api-only-data-path.md) | Data only through the public API | Proposed | #5942 |
| [04](ADR-04-stateless-streamable-http.md) | Stateless Streamable HTTP | Proposed | #5942 |
| [05](ADR-05-read-only-tools.md) | Read-only tools | Proposed | #5942; per-caller limit in phase 2 |
| [06](ADR-06-off-by-default.md) | Off by default, switched per request | Proposed | #6068 |
| [07](ADR-07-sql-redaction.md) | Redaction of SQL literals | Proposed | #6068, phase 2 |
| [08](ADR-08-inventory-under-access-roles.md) | Inventory reads under Access Roles | Proposed | #5942 (rules only); filter in phase 4 |
| [09](ADR-09-metrics-via-datasource-proxy.md) | Metrics through the Grafana datasource proxy | Proposed | #5942 |
| [10](ADR-10-nginx-only.md) | `/mcp` only through nginx, with an Origin check | Proposed | #5942, #6068; Origin check next |
| [11](ADR-11-output-contract.md) | Output contract | Proposed | Phase 3; contract before the rest of phase 2 |
| [12](ADR-12-service-accounts-as-principals.md) | Service-account tokens are principals | Proposed | Phase 4 |
| [13](ADR-13-access-role-permissions.md) | Access-Role permissions | Proposed | PMM-15791, after the MCP release |
| [14](ADR-14-default-state.md) | Default state at release | Proposed | Off; nothing to change |
| [15](ADR-15-metrics-tools.md) | Metrics tools | Proposed | Phase 2b |
| [16](ADR-16-access-roles-on-pmm-apis.md) | Access Roles on PMM's service-scoped APIs | Proposed | Phase 4 |
| [17](ADR-17-alerts.md) | Alerts | Proposed | API in phase 4, tool in phase 2b |
| [18](ADR-18-advisors.md) | Advisors | Proposed | API in phase 4, tool in phase 2b |
