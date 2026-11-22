# ADR-07: Redaction of SQL literals

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22, revised 2026-11-06
- Tickets: PMM-14247, PMM-15528, PMM-15529
- Implemented: `PMM-MCP-GA`, percona/pmm#6068 (D9 in `DECISIONS.md`); D10 on `PMM-15529-top-queries-reporting`

## Context

Query examples, EXPLAIN bodies and agent error messages can carry literal values from customer data. Sending them to a model is a data-sharing decision. A Viewer already sees some of this in the PMM UI, but a model provider is a new recipient.

## Options

1. Send everything. Rejected: SQL literals can carry customer data, which would reach the model provider.
2. Mask literals by pattern. Rejected: a literal in a form the patterns miss leaks; fail-closed masking withholds what it doesn't recognize.
3. Mask fail-closed, with an opt-in for literal values.

## Decision

Option 3. `PMM_MCP_RAW_SQL` defaults to `false` and has no API setting, only the environment variable.

With it off:
- Statements are shown as fingerprints.
- In plan bodies, every string is masked with `?` unless it is known plan structure, a statistic, or a key that holds only names (table, index, column). MongoDB numbers are masked too; MySQL and PostgreSQL plan numbers are kept, because they are estimates and those engines print literals only inside expression strings. A field a new engine version adds is masked; a plan that can't be parsed is withheld.
- Agent errors are kept only when known to name only identifiers or hosts; otherwise they are withheld.
- A SQL fingerprint with a literal outside its comments is treated as a raw statement and withheld. When the engine of a report is unknown, a quote that either MySQL or PostgreSQL reads as a string withholds the fingerprint.
- `pmm_get_schema` DDL is not masked: disclosed in `mcp.md`; no switch.
- QAN dimension values in `pmm_top_queries` (`group_by=username`, `client_host`) are shown (D10): disclosed in `mcp.md`; no switch.
- Metric label values, and alert summaries and descriptions, are returned as stored: disclosed in `mcp.md`; no switch.

Turning off query examples in PMM removes one more source of literals. DDL and the other exceptions above still return what the database or the user stored, so no setting guarantees that no literal leaves the server.

## Consequences

- Triage still works on masked plans: access type, key and rows survive.
- Some useful detail is lost by default; `PMM_MCP_RAW_SQL=true` brings it back.
- Masking happens on the result value, before rendering, so structured content (ADR-11) can't carry what the text withholds.
- Amended 2026-11-20: in a MongoDB plan, the `comment` of a `command` or `originatingCommand` is masked whole, keys included, since an application can put anything there. A traditional MySQL plan whose lines have fewer `|`-separated cells than its header is withheld, as a plan that can't be parsed, and a one-column MySQL plan, such as the tree format, is masked as one text, so a literal across lines stays one literal (#6376).
- Amended 2026-11-22: with `PMM_MCP_RAW_SQL` off, MySQL's rewritten statement, Note 1003 of the `SHOW WARNINGS` that pmm-agent appends and format version 2's `query`, is replaced with a fixed text, and pmm-agent's `real_table_name`, the word after the statement's last `FROM `, is left out. MySQL names an unaliased expression after its own text, so in a MySQL plan a backquoted name, the traditional `Extra` column's included, and the value of a key that holds names are kept only when they are a plain name (letters, digits, `_` and `$`, not a number) or one of MySQL's own names (`<derived2>`, `<union1,2>`, `<auto_key0>`, …); any other is masked. A constant that is itself a plain name, such as a derived table's `'gold'` column, still shows as that column's name. In a MongoDB plan, the values of plan keys and an index's `keyPattern` are kept only on the plan's own containers (`queryPlanner`, `winningPlan`, `inputStage`, `inputStages`, `executionStats`, `serverInfo` and the like), so a compound text index's `indexPrefix` is masked. A PostgreSQL text plan is masked as one text, every line whatever its label, and keeps numbers only in a node's `(cost=...)` and `(actual ...)` groups. A live plan whose action output is over 4 MiB is withheld with a fixed text before it is parsed, whatever `PMM_MCP_RAW_SQL` says, and so is a stored plan of that size with it off. In fingerprints: a quoted name that doesn't close is read as a string, so the fingerprint is withheld; a text that starts with `db.` is read as MongoDB only when the service is not MySQL or PostgreSQL; a MongoDB fingerprint with a single quote, or a double quote that doesn't close, is withheld; and PostgreSQL 16's number forms (`1_000_000`, `0o17`, `0x1F`) are masked whole. pmm-agent's fixed `context deadline exceeded` error is kept. The masking is tested on plans captured from MySQL and Percona Server 5.7, 8.0 and 8.4 and from Percona Server for MongoDB 8.0 (percona/pmm#6381).
- Amended 2026-11-22: with `PMM_MCP_RAW_SQL` off, a bare `true`, `false` or `null` inside a MongoDB fingerprint's braces or brackets is masked like strings and numbers. pmm-agent masks only a top-level `$match`, so a `$match` nested in `$lookup`, `$facet` or `$unionWith` reaches the stored fingerprint with its values. A collection named `null` or `true` keeps its name (percona/pmm#6383).
