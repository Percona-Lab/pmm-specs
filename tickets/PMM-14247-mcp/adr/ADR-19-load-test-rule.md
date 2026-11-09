# ADR-19: Load test pass rule and fleet size

- Status: Accepted (2026-11-09). Supersedes ADR-15's fleet-size bullet. The security design review settled a supported fleet size from the load test (spec §13); its agreement to this change is pending.
- Date: 2026-11-09
- Tickets: PMM-14247, PMM-15790

## Context

Spec §7.4's load test passed on two conditions: the load adds no rule-evaluation failure, and the dashboard probe's p95 under load is at most twice its baseline. The services of the passing run were to be stated as MCP's supported fleet size (ADR-15).

A preliminary run on 4 cores and 8 GB, with 53 MySQL services and about 2 days of data, five callers at the caps for 10 minutes:
- added no rule-evaluation failure;
- raised the dashboard probe's p95 from 45 ms to 163 ms, and VictoriaMetrics' CPU to 2.3 cores at most;
- made 13,723 MCP calls, 2,639 of them answered and the rest `rate_limited`.

It failed the 2× condition. That condition had no basis: no requirement or measurement set it. On a 45 ms baseline it fails at a latency no one notices on a dashboard.

The fleet-size rule would publish the services of one test server, about 50, as a product limit. That number says nothing about larger servers.

With the same load, MCP's share of VictoriaMetrics' query slots cut to a quarter and to an eighth (from half) gave 2.3× and 1.8×, with more calls `rate_limited`. Under load, Grafana's CPU, which proxies the dashboards' queries and MCP's alike (ADR-09), rose about 7×.

The load is the worst case a client within the caps can produce, not normal use. The question it answers is whether the caps protect the server.

## Decision

- **Pass rule.** The load test passes when the load adds no rule-evaluation failure, in Grafana's alerting or VMAlert, and no PMM Server component restarts during the run: VictoriaMetrics, VMAlert, Grafana, pmm-managed and qan-api2, read from their `process_start_time_seconds`. A process killed for memory counts as a restart. ClickHouse exports no such series, and the load test calls no QAN tool. On a failure, the caps are lowered and the test runs again.
- **Recorded, not judged.** The test records, as before:
  - the dashboard probe's p95;
  - VictoriaMetrics' CPU and memory;
  - the MCP call counts.

  A latency threshold is added only with a basis, such as a stated user requirement or a measurement of what users notice.
- **Fleet size.** MCP states no supported fleet size of its own, and PMM's sizing guide applies.
  - The series cap per selector bounds what one query reads, whatever the size of the fleet.
  - The per-replica limit follows VictoriaMetrics' own limit, which grows with the server's CPUs.

  `mcp.md` names the setup the load test passed on, as the setup tested, not as a limit.

## Alternatives

- **Keep the 2× rule.** Rejected: it has no basis, and it fails on latency no one notices.
- **An absolute latency threshold.** Not now: no number has a basis yet either.
- **A second run on a medium server** (8 to 16 cores, 31 to 200 nodes). Not required. The caps grow with the server and bound each read [I], but on a larger fleet, the cost of VictoriaMetrics' index and of the dashboards themselves is not measured. A later run can add that evidence.

## Consequences

- A cap that slows dashboards noticeably, without failing a rule or restarting a component, passes. The recorded numbers make it visible, and a review can lower the caps on them.
- How MCP behaves on large fleets is argued from the caps, not measured.
- The documentation shows no MCP-specific fleet limit.
