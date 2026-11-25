# ADR-11: One execution path; no unrecorded short call

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plan 01 (by what it leaves out); plan 04 for the caller

## Context

Fast answers to small read commands were one of the goals of the replacement: a call through Nomad takes 2.1 to 2.9 s today [V].

The prototype has two ways to run something [V]:
- **A run:** a record, stored output, a queue, a stop. One run of a fetched `echo` script took 0.07 s at pmm-managed's API on the rented machines, and 1.0 s through PMM Extensions.
- **A short call:** a script runs and its output comes back in the answer. No record, no stored output, no queue, no stop, at most a minute, its own limit of eight at once. It measured 6.2 ms in one process on the first round's rig, and was not measured on the rented machines. Its only access control is an optional list of checksums on the host. Nothing in PMM Extensions uses it.

Where the 1.0 s goes: PMM Extensions notices that a run ended by checking once a second. With a check on each run the same call took 0.3 s, with about 25 lines; that check helps only a task sent in the API request itself [V].

## Options

1. **Keep both paths.** Rejected: the short call is a second way to execute a program on a host, with weaker rules than the first: no record of what ran, and no stop. Each rule of this folder would need a second form for it.
2. **Keep the short call and give it a record.** Rejected: it is then a run.
3. **One path, and remove the waiting around it.**

## Decision

Option 3.

- Everything that executes on a host is a run, with a record.
- `GetRun` and `ListRuns` can wait (ADR-10), so a caller hears of a run's end when it happens, without polling.
- PMM Extensions keeps one `ListRuns` call open and updates each run it returns. That serves every run, including the ones a caller is waiting on: inventory and topology probes, and the connectivity check.

## Consequences

- One set of rules for who may run what, what is recorded, and how it is stopped.
- A small script takes about 0.07 s at the API, plus what PMM Extensions adds. The prototype has no figure for a read command: it did not carry that kind. Test T17 sets the bar at 0.5 s through PMM Extensions.
- That is slower than the short call's few milliseconds. No caller needs those today; a pmm-agent Action, PMM's existing fast path, takes 122 ms for a MySQL read [V].
- Every small call leaves a record for 7 days (ADR-05). At one a second that is about 600,000 rows; plan 02 sizes the tables and their indexes for it.
- If a caller later needs answers in milliseconds, that is a new record, and the answer may be an Action rather than a script.
