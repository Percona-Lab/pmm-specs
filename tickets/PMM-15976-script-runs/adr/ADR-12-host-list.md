# ADR-12: The host list comes from the registry and the existing ping

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 02](../plans/02-managed-runs-api.md); [plan 03](../plans/03-containment.md) for the host facts

## Context

PMM Extensions has to know which hosts can run a task, and why one cannot. Today it reads Nomad's node list and takes the nodes that are ready with a healthy `raw_exec` driver [V].

In PMM Nomad clients are named by their PMM node name (`managed/services/agents/nomad.go:35`) [V], so the names PMM Extensions has stored as targets are PMM node names.

What pmm-managed knows about an agent [V]:
- Whether its stream is registered. After a silent network loss that stays true for a long time: the spike's first round measured 953 s, until the kernel's TCP retries gave up.
- A ping every 10 s with a 5 s limit (`managed/services/agents/handler.go:40,44`). A failed ping is logged and nothing else happens.
- Its version, sent when it connects.

The prototype adds a loop that asks every connected agent a question every 2 s and keeps the answers in memory, on every replica, whether or not anyone runs scripts [V]. It moved the wait for a silent host off the path that starts a task: starting a task with one host silently cut took 1.06 times as long as with every host connected, where the first form had cost 2 s more for every task while a host was cut [V].

## Options

1. **The registry's connected flag alone.** Rejected: a silently cut host reads as usable for up to a quarter of an hour.
2. **A probe loop for scripts** (the prototype). Rejected: constant traffic to every agent for a feature most hosts may never use, and a per-replica cache.
3. **The registry, the ping PMM already sends, and facts the agent reports when it connects.**

## Decision

Option 3. `ListHosts` returns one entry per pmm-agent:

| Field | Source |
|---|---|
| `node_name`, `node_id`, `pmm_agent_id`, `address` | The inventory |
| `connected` | The in-memory registry of the replica that answers: the lookup a start uses, so the list and a start agree |
| `responsive` | Any message received from pmm-agent is proof of life. pmm-managed pings every 10 s; with nothing received for 30 s the host reads as not answering. A ping that fails because pmm-managed's own loop is busy does not count against the host |
| `can_run`, `reason` | False with a reason: not connected, not answering, too old, being checked, script runs switched off on the host |
| `user`, `contained`, the two limits | Reported by pmm-agent in its answer to the list of runs that pmm-managed asks for on every connect ([ADR-03](ADR-03-at-most-once.md)) |

A host is named by its PMM node name.

## Consequences

- No new traffic. A silently cut host shows as not answering within about 30 s.
- The names PMM Extensions has stored keep working.
- A caller sees why a host cannot run a task, including the two reasons Nomad could not give: the host's owner switched it off, and the client is too old.
- `contained: false` tells a caller that a host has the fallback's limits ([ADR-06](ADR-06-stop-and-containment.md)).
- pmm-managed records when it last heard from each pmm-agent. It still does not drop a connection on a failed ping: that stays as it is.
- In HA the registry is the leader's, and calls go to the leader. A host whose stream is held by another replica reads as not connected; that limit is PMM's own ([ADR-13](ADR-13-high-availability.md)).
