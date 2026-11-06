# MCP (Model Context Protocol) endpoint in PMM Server

- **Epic:** [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247), "PMM is AI Ready - MCP [Tech Preview]"
- **Status:** phases 0 and 1 merged into the integration branch `PMM-MCP-GA` in percona/pmm; phase 2 in progress; phases 2b to 5 designed here, reviewed and merged in [pmm-specs#4](https://github.com/Percona-Lab/pmm-specs/pull/4). ADR status per record in the [ADR index](adr/README.md).
- **Integration branch:** `PMM-MCP-GA` in percona/pmm. Every phase PRs into it; it merges into `main` once, in phase 5.

| Phase | Ticket | Pull requests |
|---|---|---|
| 0 Unblock, cut `PMM-MCP-GA` | [PMM-15527](https://perconadev.atlassian.net/browse/PMM-15527) | [percona/pmm#5942](https://github.com/percona/pmm/pull/5942) (merged into `PMM-MCP-GA`) |
| 1 Harden | [PMM-15528](https://perconadev.atlassian.net/browse/PMM-15528) | [percona/pmm#6068](https://github.com/percona/pmm/pull/6068) (merged into `PMM-MCP-GA`) |
| 2 Query intelligence | [PMM-15529](https://perconadev.atlassian.net/browse/PMM-15529) | [percona/pmm#6099](https://github.com/percona/pmm/pull/6099), [#6100](https://github.com/percona/pmm/pull/6100), [#6101](https://github.com/percona/pmm/pull/6101) (open, stacked) |
| 2b Metrics, alerts and Advisors | [PMM-15790](https://perconadev.atlassian.net/browse/PMM-15790) | — |
| 3 Output contract | [PMM-15530](https://perconadev.atlassian.net/browse/PMM-15530) | — |
| 4 Service list and identity | [PMM-15531](https://perconadev.atlassian.net/browse/PMM-15531) | None yet; service-account tokens land on `main` through [PMM-15534](https://perconadev.atlassian.net/browse/PMM-15534) |
| 5 Land and release | [PMM-15532](https://perconadev.atlassian.net/browse/PMM-15532) | — |

Related tickets: PMM-15533, PMM-15534, PMM-15535, PMM-15536, PMM-15697, PMM-15702, PMM-15744; security-sensitive ones in [spec §14](spec.md#14-security-sensitive-items). Filed with this spec: PMM-15790 (phase 2b), PMM-15791 (Access-Role permissions, ADR-13), PMM-15792 (string settings as info metrics).

| Path | Content |
|---|---|
| [spec.md](spec.md) | Analysis and design: problem and goals, architecture as built, the rest of phase 2, phases 2b to 5, corrections to the tickets |
| [tool-contract.md](tool-contract.md) | The MCP tool contract (ADR-11): the rules every tool follows and one row per tool; written by plan 03 Task 1 and reviewed before the rest of plan 03 |
| [adr/](adr/README.md) | ADR-01 to ADR-10 start from decisions implemented on `PMM-MCP-GA`; ADR-11 to ADR-18 are new; ADR-16 is deferred |
| [plans/](plans/00-roadmap.md) | Roadmap and plans 01 to 08: plans 01 to 05 in full, plans 06 to 08 at task level |

Replaces `managed/services/mcp/DECISIONS.md` and `dev/docs/managed/mcp-access-roles-proposal.md` on `PMM-MCP-GA` (at `826945906`): [spec §5](spec.md#5-decisions-already-taken) maps each entry of `DECISIONS.md` to where it lives now, and [ADR-13](adr/ADR-13-access-role-permissions.md) replaces the proposal.
