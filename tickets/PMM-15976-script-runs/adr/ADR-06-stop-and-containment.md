# ADR-06: Stop and containment: one control group per run

- Status: Proposed
- Date: 2026-11-18
- Tickets: PMM-15976
- Planned in: plans 01 and 03

## Context

A stop has to end every process a run started, and one run's failure must not reach pmm-agent, the exporters or the other runs. pmm-agent is the monitoring agent: if it stops, the host's monitoring stops.

Jobs today end a process with SIGKILL to the direct child only [V]. The prototype does more: it starts the script in its own process group, kills the group on a stop (SIGTERM, 5 s, SIGKILL), kills the script when pmm-agent dies, and afterward kills every process that still carries the run's id in its environment. Tested [V]:

- An ordinary child, and a grandchild in its own session, are ended by a stop.
- A child that leaves its session **and** clears its environment survives: it was alive 30 s later with PID 1 as its parent.
- In the first round, in containers, children that left their session lived on after a hard kill of pmm-agent: 3 of 3 at 30 s. The prototype's code has no clean-up of processes at start.
- **A run that fills the host's memory.** The kernel always killed that run. In 9 of 15 takes that was all. In 6 of 15 the whole pmm-agent unit stopped, with every run in flight and the host's monitoring, for about 92 s: every repeat within one agent lifetime (5 of 5) and 1 of 10 first ones. The test ran pmm-agent as its non-root package user on the 2 GiB Ubuntu host; a root pmm-agent and the Rocky host were not taken. The packaged unit holds pmm-agent, the exporters and every run in one control group, and systemd's default is to stop a unit when the kernel kills something in it for memory.

The spike also tried the fix by hand, on Ubuntu 24.04 with systemd 255 and cgroup v2, as the non-root `pmm-agent` user [V]:
- As packaged, pmm-agent cannot create a control group, and a systemd scope asks for interactive authorization.
- With `Delegate=memory pids` in a drop-in, it can. systemd then reports `OOMPolicy=continue` for the unit. A run in a group of its own, killed by that group's 300 MiB limit, was killed alone in 2 of 2 takes; pmm-agent and the exporters kept running.
- With `OOMPolicy=stop` set beside it, the same kill stopped the whole unit, in one take.
- A run that fills the host's memory inside a group with no limit was not tried.

Nomad gives each run a control group on hosts where its client is root, and HTCondor has one per run [I].

## Options

1. **Process group and environment mark only** (the prototype). Rejected as the only mechanism: the two escapes and the 6-of-15 finding stay.
2. **A launcher on the host that reparents and tracks children**, as the spike's 110-line Python launcher does. Rejected: it needs Python 3.9 on every host, and it is one more process per run (6 to 8 MiB each in the spike).
3. **A transient systemd scope per run.** Rejected: it needs a privilege pmm-agent does not have when it is not root, and it ties the mechanism to systemd's D-Bus API.
4. **A control group per run, below pmm-agent's own, by delegation.**

## Decision

Option 4, with option 1 as the fallback where a host offers no control group to use.

**PMM Client's unit** gains three lines:

```
Delegate=memory pids
OOMPolicy=continue
Environment=PMM_AGENT_RUN_GROUPS=1
```

The third line tells pmm-agent that its group is delegated. A root pmm-agent can create groups under any unit, so it must not conclude delegation from that.

**pmm-agent**, when the unit says its control group is delegated:
- moves itself and its other children into a group named `agent`, and enables the memory and pids controllers for the groups beside it;
- starts each run in a group of its own, named by the run id, with a limit on its number of processes;
- sets the group's `memory.max` from the run's `memory_max`, when given, and `memory.oom.group`, so that a memory kill takes the whole run;
- ends a stop with `cgroup.kill` on the group, after the grace period, and removes the group;
- when a run ends, however it ends, kills everything still in its group and removes the group;
- at start-up kills and removes every run group it finds.

**Every run**, contained or not, gets a high `oom_score_adj`: when the host itself runs out of memory, the kernel takes the run before the database or pmm-agent.

**Where that is not possible** (the Docker image of PMM Client, cgroup v1, a unit without the settings, a kernel without `cgroup.kill`), pmm-agent uses the process group and the environment mark, and reports `contained: false` for the host ([ADR-12](ADR-12-host-list.md)). At start-up it kills every process that still carries a run's mark. A run that asks for `memory_max` on such a host is not started: a limit that cannot be enforced is not silently dropped.

A stop itself is the same in both cases: SIGTERM to the process group, 5 s, then the kill. A stop needs no free slot.

## Consequences

- A stop reaches every process of a run, whatever session or environment it has.
- A run cannot leave a process behind. A task that must start a long-lived process hands it to the service manager.
- A run that fills its memory is killed alone, and pmm-agent, the exporters and the other runs go on. This needs the unit settings. The spike showed it for a kill by the run's own limit; test T5 runs 16 takes on each test host, 8 with a limit and 8 without.
- Leftovers of a pmm-agent that was killed are gone when it starts again.
- PMM Client's unit changes, for every install, on upgrade. `Delegate=` changes who owns the unit's control group and nothing else that a host's owner would see. It is the one change in this epic that touches every host whether or not it runs scripts; open question O1 of the spec asks for agreement.
- Hosts that are not contained keep the prototype's limits, and say so.
- The group is not a wall. A script that runs as pmm-agent's own user can move itself out of its group; one that runs as another user (ADR-07) cannot. Containment bounds accidents and ordinary children.
- `cgroup.kill` needs Linux 5.14 or later, and `OOMPolicy=` systemd 243 or later [I]. Rocky 9 and Ubuntu 24.04 have both. RHEL-compatible 8 has neither and gets the fallback; plan 03 lists what each supported distribution has.
- The code is not written. The spike estimated about 85 lines for creating the groups and setting a limit, across pmm-agent, pmm-managed and the executor. The stop, the sweep and the fallback are not in that figure; plan 03 is the plan.
