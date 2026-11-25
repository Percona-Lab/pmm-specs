# ADR-04: Acknowledged delivery with a bounded queue

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plans 01 and 02

## Context

A run's output and its result have to reach PMM Server complete, in order and once, across network cuts and restarts of pmm-managed.

Jobs today send both without an acknowledgment. A message sent while the stream is dying is dropped without a trace, and nothing is sent again after a reconnect (`agent/client/client.go:409`, `agent/client/channel/channel.go:203`) [V]. The runner's channels are unbuffered and have one reader per connection, so a job also blocks while the connection is down (`agent/runner/runner.go:104-105`, `agent/client/client.go:401-417`) [V].

The prototype went through three forms [V]:
1. Plain job messages: 16 of 150 lines were lost over a 60-second cut (first round).
2. Acknowledged messages that the script waits for. A script that outlived the cut lost nothing, but stalled on its own full pipe for as long as the host was cut off. A script that ended during the cut lost output while its record read succeeded: 303 of 900 lines stored over a 20-minute cut (first round).
3. Acknowledged messages behind a queue in memory: a script that ended inside a 20-minute cut delivered 900 of 900 lines, and one inside a 75-minute cut 1,000 of 1,000, each stored once (second round).

Form 3 has three faults [V]: the queue has no bound; pmm-managed acknowledges even when its database write failed (prototype `managed/services/agents/handler.go:173-185`); and one message is in flight per host for all runs together, each carrying one chunk of at most 32 KiB.

## Options

1. **Block the script when the queue is full.** Nothing is dropped. Rejected: a script's speed and its end would depend on the network, and a time limit could expire on a script that did nothing wrong.
2. **Spool output to a file in the run directory** and send from the file. Rejected for now: nothing is lost up to the size of the disk, but it adds a full-disk case to a database host and a second cleanup path. It is the option to reopen if drops are seen in practice.
3. **A bounded queue in memory; beyond the bound, drop and count.**

## Decision

Option 3.

- The script never waits for the network.
- One run may hold 4 MiB of output that has not been acknowledged, and all runs of a host together 32 MiB. Output beyond that is dropped from the middle and counted: the start of a run's output and its last 64 KiB are kept, because a failing script prints its error last. A run whose `max_output_bytes` is under 128 KiB keeps half of it as its end. The first chunk after a gap carries the number of bytes dropped there; the result carries the run's total, and the record shows it.
- The kept ends are held beside the 32 MiB, one for each run pmm-agent knows. A run holds its place in the host's limits until its result is acknowledged, so their number is bounded: 272 runs at the default limits, 17 MiB.
- `max_output_bytes` caps what one run may store, in the same way.
- A chunk or a result travels in a request that pmm-managed answers. pmm-agent keeps it until the answer arrives and sends it again after a reconnect.
- pmm-managed stores first and answers second. Each item is answered as stored or as discarded, and pmm-agent sends again what got no answer. A chunk is stored once: `(run_id, chunk_id)` is the key.
- An item is discarded when its run has no open record, for example after a restore of PMM Server. pmm-managed then stops that run.
- An item whose store fails for a reason that no retry can fix is discarded and counted, so that one bad chunk cannot hold up a host's delivery.
- pmm-agent replaces NUL bytes as it replaces bytes that are not valid UTF-8: PostgreSQL does not store a NUL in a text column [I].
- pmm-managed accepts a message for a run only from the agent the run was sent to.
- One request carries up to 256 KiB of chunks and results, from any runs of that host.
- On shutdown pmm-agent kills every run at once and waits at most 5 s for acknowledgments.

The numbers are in [the roadmap's limits](../plans/00-roadmap.md#limits).

## Consequences

- Complete output across the cuts the spike tested, with pmm-agent's memory bounded whatever scripts print: 32 MiB of queued output and the kept ends, 49 MiB above its base at the default limits.
- Output can be lost when a script prints more than 4 MiB while its host is cut off. The record says how much. Before this, the choice was between losing it silently and growing without limit.
- A slow PostgreSQL slows delivery but loses nothing: pmm-agent re-sends what was not answered.
- Output is text. Bytes that are not valid UTF-8, and NUL bytes, are replaced.
- Backups keep today's delivery (ADR-02).
