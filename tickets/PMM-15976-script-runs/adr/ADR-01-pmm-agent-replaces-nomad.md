# ADR-01: pmm-agent replaces Nomad

- Status: Accepted (2026-11-17), at the review of the PMM-15696 spike results
- Date: 2026-11-18
- Tickets: PMM-15976, PMM-15696
- Planned in: plans 01 to 07

## Context

PMM Extensions runs every task on PMM Client hosts through HashiCorp Nomad, which PMM embeds: a server in PMM Server and a client beside every pmm-agent. Nomad releases since 1.7 are under the Business Source License 1.1, and PMM is AGPL-3. Nomad in PMM also needs a public address and an extra port to start, does not cluster in PMM HA, and adds a daemon of about 100 MiB to every host ([spec §3.1](../spec.md#31-nomad-in-pmm-today)).

Measured on PMM 3.10.0 as released, a script can run twice, or be cut short, while its record reads success: after a 20-minute network cut, after a restart of pmm-agent, and after a host is away for over an hour ([spec §3.3](../spec.md#33-what-today-gets-wrong)) [V].

The spike PMM-15696 found 104 options, screened and graded them, and tested three beside Nomad on rented machines. Its figures are in [spec §4](../spec.md#4-what-the-spike-measured).

## Options

1. **Keep Nomad as it is.** Rejected: the license, and the measured failures above.
2. **Keep Nomad and fix how PMM drives it.** With 165 added lines (a launcher, three access controls and a changed task definition) Nomad passed the 20-minute cut in the spike. Rejected: the license stays. On that footing a restart of pmm-agent still ran scripts twice, and the output before a stop was still lost. It would also need three controls shipped in PMM's templates, four more fixes that are not written, three task kinds that are not built, and a restart of every host's client to give back the memory it keeps for each run (0.85 MiB a run, with no ceiling by 500 runs) [V].
3. **HTCondor** (Apache 2.0). The least memory of the options that add a process: 23 to 24 MiB on a host. Rejected: one run costs about 2.4 s whatever it does, so a command took 9.1 s through PMM Extensions on the set-up its passes stand on. It adds 82 packages (262 MB) on Rocky 9, a listening port and a sudo rule to every database host, and a run stopped while its host is cut off holds its slot for 32 to 36 minutes [V].
4. **Velociraptor** (AGPL 3.0). As fast as the pmm-agent job through PMM Extensions (1.0 s). Rejected: it is a forensics agent, which a customer's security tooling may flag; its host process holds as much memory as Nomad's (89 to 107 MiB) and grew after runs for a reason the spike did not establish; an out-of-memory kill of one run stopped its whole service [V].
5. **A job type inside pmm-agent**, driven by pmm-managed over the stream the agent already holds. It adds no process, port or package to a host. Through PMM Extensions a call took 1.0 s against Nomad's 2.1 to 2.9 s. Each run in flight cost at most 0.5 to 0.7 MiB on the host (the script's own processes) against 52 to 68 MiB in Nomad's own processes. Its code does not exist in a release: the prototype is about 1,900 lines in percona/pmm without tests [V].

Jenkins and Dagu were built and dropped after the first round ([spec §4.4](../spec.md#44-why-the-others-were-not-chosen)). Forty-eight more options passed the rules and were not built, and 51 failed a rule.

## Decision

Option 5. PMM Extensions' tasks run through pmm-agent, and Nomad is removed from PMM.

## Consequences

- PMM Client hosts lose a daemon, and PMM Server loses a service, a port and a certificate authority.
- The license question ends when the removal ships (ADR-14).
- The executor becomes PMM's own code. Its design, review, tests and upkeep are PMM's work; ADR-02 to ADR-14 and the plans are that work.
- The monitoring agent now also runs customers' scripts. What a run can do to pmm-agent has to be bounded (ADR-04, ADR-06).
- The prototype left open points: a memory kill that can stop the whole unit, a child that escapes a stop, a script that runs on after a restore, HA and upgrades untested, two of four task kinds not carried ([spec §4.5](../spec.md#45-what-the-spike-left-open-for-the-pmm-agent-job)). Each has a decision and a test in this folder.
- Clients older than the release that ships the job cannot run tasks through pmm-agent (ADR-14).
