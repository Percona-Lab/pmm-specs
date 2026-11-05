# ADR-02: Base implementation and what to port

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15527, PMM-15529
- Implemented: `PMM-MCP-GA`, percona/pmm#5942; phase 2 in progress

## Context

#5942 provides the transport, authentication, error handling and redaction, with about 1,720 lines of tests. #4045 (Percona-authored, closed unmerged, 26,340 lines) bundled an AI chat backend. Its query handling has four features #5942 lacks: it resolves a `queryid` before acting, groups and filters QAN reports, publishes the QAN column catalogue, and fetches table definitions concurrently. #4045 is Percona's code, so it can be reused without a CLA.

## Options

1. Base on #4045 and strip the chat backend. Rejected: most of its 26,340 lines are the chat backend, and its polling has no deadline.
2. Base on #5942 and port selected parts of #4045.
3. Rewrite from scratch. Rejected: it discards #5942's transport, redaction and tests for no gain.

## Decision

Option 2.

**Ported:** resolve-first query metadata, flexible `pmm_top_queries` reporting, the QAN column catalogue, concurrent table fetch, `info_types`, total-row reporting.

**Not ported:**
- the chat backend;
- `responseActionOutput`, which polls on a 1 s ticker with no deadline; #5942's bounded polling under `PMM_MCP_ACTION_TIMEOUT` stays;
- `extractTablesFromExplainJSON`. It reads `real_table_name`, which pmm-agent parses from the SQL text and which names one table only. Tables are found by walking the plan instead ([spec §6.2](../spec.md#62-pmm_get_schema-from-a-queryid)).

## Consequences

- #5942's transport and redaction stay; query intelligence arrives in small PRs onto `PMM-MCP-GA`.
- Each ported piece is re-tested against #5942's API-only data path (ADR-03): #4045 called internal services directly, which this design does not.
