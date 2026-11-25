# ADR-03: A run happens at most once, and a final state is final

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plans 01 and 02

## Context

A task may be a backup, a restore or a change to a database. Running it twice, or reporting success for a run that was cut short, is worse than reporting that it was lost. Today both happen: after a 20-minute cut both test scripts ran twice, and after a restart of pmm-agent a script started again from line 1 while its record read success ([spec §3.3](../spec.md#33-what-today-gets-wrong)) [V].

The prototype never repeated a run. But it has two gaps [V]:
- pmm-managed asks about each open run in turn after a reconnect. A run that is still waiting for a slot in pmm-agent answers "not alive" and is marked lost, and its later result then turns the record into succeeded or failed (prototype `agent/runner/runner.go:318`, `managed/services/agents/scripts.go:722-723`).
- After a restore of PMM Server, the script of a run whose record is gone keeps running on the host, and nothing ends it.

Nothing about a run survives a restart of pmm-agent: the process is killed with it, and the output queue is in memory.

## Options

1. **Re-run after a failure of the infrastructure**, as Nomad's reschedule does. Rejected: it is the cause of the double runs.
2. **Keep runs alive across a pmm-agent restart**, with a state file and re-attachment to the process. Rejected for now: it needs a supervisor outside pmm-agent, which is the kind of component this epic removes.
3. **At most once, lost on restart, with per-run questions after a reconnect** (the prototype). Rejected: the two gaps above.
4. **At most once, lost on restart, with one list per connect.**

## Decision

Option 4.

- PMM never starts a run a second time. There is no retry in pmm-agent, pmm-managed or the protocol. A caller that wants another attempt starts a new run.
- The caller chooses the run's id. A second start with the same id returns the first's record and starts nothing, so a caller that lost an answer can ask again.
- A run that could not start is a record, in `not_started` or `expired`, with its reason.
- **A final state never changes.** The final states are `succeeded`, `failed`, `stopped`, `timed_out`, `expired`, `prepare_failed`, `not_started` and `lost`.
- **On every connect** pmm-agent first re-sends what was not acknowledged. pmm-managed then asks once for every run id pmm-agent knows: waiting, running, or finished with its result not yet acknowledged.
  - A record that is `queued` or `running` and is not in the answer becomes `lost`.
  - A run in the answer that has no open record is stopped.
  - A question that gets no answer within its deadline is asked again on the same stream until it is answered.
  - A record whose start is still in flight is not judged. A start that got no answer within its deadline stays `pending` until the next check, and then becomes `lost` if pmm-agent does not know it: the script may have started.
- A run stays in pmm-agent's answer until its result is acknowledged. So no run is marked lost while its result is on the way, and no result arrives after `lost`.
- A host that does not come back leaves its runs `queued` or `running`, shown as not connected. PMM does not guess an outcome. The record becomes `lost` when the agent is removed from the inventory.

## Consequences

- A restart of pmm-agent loses the runs in flight, and each record says so. A reload of its configuration does not: runs survive it, although it ends every job today. This includes package upgrades: in the spike, Ubuntu's daily automatic upgrade restarted pmm-agent between 6.5 and 8.5 hours into each 12-hour run [V].
- The 2 s wait per lost run of the prototype goes away; in the first round 20 lost runs took 40 s to close [V].
- A script that runs on after a restore of PMM Server is stopped at the next connect.
- A caller cannot tell from `lost` how far the script got. The output stored up to that point stays readable.
- A task that upgrades PMM Client or restarts pmm-agent ends itself part-way: stopping the unit ends every process in it. Such a task hands that step to the service manager.
- Long runs that must survive an agent restart are not served. If that need appears, it reopens option 2 in a new record.
