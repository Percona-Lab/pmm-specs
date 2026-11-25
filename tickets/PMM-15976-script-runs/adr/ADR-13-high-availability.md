# ADR-13: No run state in a replica's memory

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plan 02; tested in plan 06

## Context

Nomad in PMM does not cluster: three replicas form three separate Nomad servers, each with its own certificate authority ([spec §3.1](../spec.md#31-nomad-in-pmm-today)) [V]. Nothing in that set-up carries a task across a change of leader; this is read from the code, and was not tested.

How PMM HA works [V]:
- One replica is the leader, by Raft. HAProxy sends all traffic to it, from the API and from agents (`documentation/docs/install-pmm/HA-clustered.md:102-103`).
- The replicas share PostgreSQL.
- A call that needs an agent finds it in the memory of the replica that holds its stream, and fails as "not currently connected" anywhere else (`managed/services/agents/registry.go:577-585`). Nothing forwards a call between replicas.
- A leader that loses leadership does not drop its agents: the code that would is commented out (`managed/cmd/pmm-managed/main.go:1024-1029`).
- Some services run on the leader only, through `AddLeaderService`.

The prototype keeps a cache of host answers in each replica's memory and runs retention on every replica. HA was not tested in the spike for any option.

## Options

1. **Tie a run to the replica that started it.** Rejected: a change of leader would lose every run in flight, which is the gap the design is meant to close.
2. **Forward calls between replicas.** Rejected: that is a change to PMM HA itself, larger than this epic.
3. **Keep everything about a run in PostgreSQL and on its host, and let the reconnect do the rest.**

## Decision

Option 3.

- A run's record, its output and a held stop are rows in PostgreSQL.
- A run executes on its host and does not depend on any replica being up.
- After a change of leader, agents reconnect to the new leader. pmm-agent re-sends what was not acknowledged, and the check of ADR-03 runs there.
- Retention is a leader service.
- The host list reads the registry of the replica that answers, which is the leader.
- A call that waits is answered by the replica that received it, and re-reads the database every second, so it returns whichever replica stored the result.
- The internal token of ADR-09 is set with `PMM_EXTENSIONS_TOKEN`, to the same value on every replica. PMM Extensions is not part of the HA set-up today; that work is PMM-15287.

## Consequences

- A change of leader loses no run and repeats none, as long as the hosts reach the new leader. The output written during the change arrives after the reconnect, up to the queue's bound (ADR-04).
- Two limits of PMM HA remain. While an agent's stream is still held by a demoted leader, a start for that host is `not_started` with "not connected", and a stop is held until the agent reconnects.
- A `GetRun` that waits can return early when its replica stops being the leader. The caller asks again.
- None of this is measured yet. Test T8 is a release gate: a change of leader with runs in flight, on the three-replica chart, driven through the API with the token set as above. Its bar includes a new run that starts after the change.
