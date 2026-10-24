# MCP endpoint in PMM Server

- **Epic:** [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247), "PMM is AI Ready - MCP [Tech Preview]"
- **Status:** phases 0 and 1 merged into the integration branch `PMM-MCP-GA` in percona/pmm; phase 2 in progress; phases 2b to 5 designed here. ADR status per record in the [ADR index](adr/README.md).
- **Integration branch:** `PMM-MCP-GA` in percona/pmm. Every phase PRs into it; it merges into `main` once, in phase 5.

| Phase | Ticket | Pull requests |
|---|---|---|
| 0 Unblock, cut `PMM-MCP-GA` | [PMM-15527](https://perconadev.atlassian.net/browse/PMM-15527) | [percona/pmm#5942](https://github.com/percona/pmm/pull/5942) (merged into `PMM-MCP-GA`) |
| 1 Harden | [PMM-15528](https://perconadev.atlassian.net/browse/PMM-15528) | [percona/pmm#6068](https://github.com/percona/pmm/pull/6068) (merged into `PMM-MCP-GA`) |
| 2 Query intelligence | [PMM-15529](https://perconadev.atlassian.net/browse/PMM-15529) | [percona/pmm#6099](https://github.com/percona/pmm/pull/6099) (open); branches `PMM-15529-top-queries-reporting`, `PMM-15529-schema-multi-table` |
| 2b Metrics, alerts and Advisors | [PMM-15790](https://perconadev.atlassian.net/browse/PMM-15790) | — |
| 3 Output contract | [PMM-15530](https://perconadev.atlassian.net/browse/PMM-15530) | — |
| 4 Identity and Access Roles | [PMM-15531](https://perconadev.atlassian.net/browse/PMM-15531) | — |
| 5 Land and release | [PMM-15532](https://perconadev.atlassian.net/browse/PMM-15532) | — |

Related tickets: PMM-15533, PMM-15534, PMM-15535, PMM-15536, PMM-15702, PMM-15703; filed with this spec: PMM-15791 (Access-Role permissions, ADR-13), PMM-15792 (string settings as info metrics).

| Path | Content |
|---|---|
| [spec.md](spec.md) | Analysis and design: architecture as built, the rest of phase 2, phases 3 to 5, corrections to the tickets |
| [adr/](adr/README.md) | ADR-01..10 start from decisions implemented on `PMM-MCP-GA` (ADR-05, 08 and 10 revised in review); ADR-11..18 are new |
| `plans/` | Roadmap and per-phase implementation plans; added after the spec is reviewed |

Replaces `managed/services/mcp/DECISIONS.md` and `dev/docs/managed/mcp-access-roles-proposal.md` on `PMM-MCP-GA` (at `826945906`); [spec §5](spec.md#5-decisions-already-taken) maps each of their entries to where it lives now.
