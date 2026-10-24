# ADR-07: Redaction of SQL literals

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528, PMM-15529
- Implemented: `PMM-MCP-GA`, percona/pmm#6068 (D9 in `DECISIONS.md`); D10 on `PMM-15529-top-queries-reporting`

## Context

Query examples, EXPLAIN bodies and agent error messages can carry literal values from customer data. Sending them to a model is a data-sharing decision. A Viewer already sees some of this in the PMM UI, but a model provider is a new recipient.

## Options

1. Send everything.
2. Mask literals by pattern.
3. Mask fail-closed, with an opt-in for literal values.

## Decision

Option 3. `PMM_MCP_RAW_SQL` defaults to `false` and has no API setting, only the environment variable.

With it off:
- Statements are shown as fingerprints.
- In plan bodies, every string is masked with `?` unless it is known plan structure, a statistic, or a key that holds only names (table, index, column). MongoDB numbers are masked too; MySQL and PostgreSQL plan numbers are kept, because they are estimates and those engines print literals only inside expression strings. A field a new engine version adds is masked; a plan that can't be parsed is withheld.
- Agent errors are kept only when known to name only identifiers or hosts; otherwise they are withheld.
- A SQL fingerprint with a literal outside its comments is treated as a raw statement and withheld. When the engine of a report is unknown, a quote that either MySQL or PostgreSQL reads as a string withholds the fingerprint.
- `pmm_get_schema` DDL is not masked.
- QAN dimension values in `pmm_top_queries` (`group_by=username`, `client_host`) are shown (D10): Viewers already see them in QAN, and this ADR is about SQL literals.
- Metric label values, alert summaries and descriptions, and Advisor texts are returned as stored: they are not SQL statements, and the same caller sees them in PMM.

Operators who need a hard guarantee also turn off query examples in PMM.

## Consequences

- Triage still works on masked plans: access type, key and rows survive.
- Some useful detail is lost by default; `PMM_MCP_RAW_SQL=true` brings it back.
- Masking happens on the result value, before rendering, so structured content (ADR-11) can't carry what the text withholds.
