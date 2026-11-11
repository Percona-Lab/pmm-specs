# PMM specs

Specs, implementation plans and architecture decision records (ADRs) for [Percona Monitoring and Management](https://github.com/percona/pmm). Code stays in the component repos; the design behind it lives here.

Layout and rules: [AGENTS.md](AGENTS.md).

## Index

| Folder | Topic | Status |
|---|---|---|
| [PMM-14247-mcp](tickets/PMM-14247-mcp/) | MCP endpoint in PMM Server | Phases 0–1 merged into `PMM-MCP-GA`; design for phases 2–5; ADR-05, 10, 17 and 18 proposed, ADR-16 deferred, the rest accepted |
| [PMM-15567-otel](tickets/PMM-15567-otel/) | OpenTelemetry logs and traces | Design; ADRs partly accepted |
| [PMM-15785-qan-clickhouse-db](tickets/PMM-15785-qan-clickhouse-db/) | QAN database consistency across ClickHouse replicas (PMM HA) | Design, in review |
| [PMM-15832-release-coordinator](tickets/PMM-15832-release-coordinator/) | AI release coordinator; Helm chart branching | ADR-01 proposed |
