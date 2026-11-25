# ADR-07: Which OS user a script runs as

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 03](../plans/03-containment.md); [plan 01 Task 7](../plans/01-agent-run-script.md#task-7-readrunfile-confined) for the file read; [plan 04](../plans/04-extensions-executor.md) for PMM Extensions

## Context

- Packaged pmm-agent runs as root: its systemd unit has no `User=` (`build/packages/config/pmm-agent.service`) [V]. The packages do create a `pmm-agent` user, which owns the files. In the Docker image of PMM Client, pmm-agent runs as uid 1002 [V].
- Under Nomad today a task runs as the Nomad client's user, which is pmm-agent's: root on a packaged install. Every step is started with an empty `User` [V, `app/tasks/db/seed.py` in percona/pmm-extensions].
- Tasks need it. A MySQL restore stops the server and rewrites its data directory. Setting up a MongoDB host installs packages. A task that needs root says so by putting `sudo` in front of its interpreter, and PMM Extensions warns when a host cannot elevate [V].
- pmm-agent starts no child as another user today [V]. The decision for PMM's OpenTelemetry collector is to start it as the `pmm-agent` user even when pmm-agent is root ([PMM-15567 ADR-08](../../PMM-15567-otel/adr/ADR-08-file-read-trust.md)).
- The spike ran the prototype mostly as a non-root pmm-agent, through a drop-in added for the test. Root work then went through a sudo rule that named a launcher. It also has a `run_as` field, about 30 lines, used in the first round on a root pmm-agent [V].

## Options

1. **Always pmm-agent's own user.** Parity with Nomad. Rejected as the only choice: on a packaged install every script would be root, including the many that need less.
2. **Always the non-root `pmm-agent` user**, as the collector. Rejected: restores and installs stop working on every host until its owner adds sudo rules, and a sudo rule wide enough for those tasks gives little.
3. **pmm-agent's own user by default; a run may name another user.**
4. **A list of allowed users in `pmm-agent.yaml`.** Rejected for now: a root pmm-agent that may run a script as root gains nothing from being forbidden to run one as `mysql`. Naming a user is meant to lower a run's privileges.

## Decision

Option 3.

- With `run_as` empty, a script runs as the user pmm-agent runs as.
- With `run_as` set, pmm-agent must be root. It looks the user up, gives the run directory to that user, and starts the script with that user's uid, gid, supplementary groups and home directory. The run directory's parents can be traversed by that user. An unknown user ends the run as `prepare_failed`, with the reason.
- A pmm-agent that is not root does not get such a run: pmm-managed knows which user each pmm-agent runs as, and records the run as `not_started`.
- The lookup reads the host's own user files. A user that exists only in a directory service is not found [I].
- pmm-agent reports the user it runs as when it connects, and the host list shows it.
- The file read for a run opens files without following links and reads only regular files with a link count of 1, so that a script running as a lesser user cannot make pmm-agent read a file for it ([spec §6.7](../spec.md#67-the-api)).
- No launcher and no sudo rule ships with PMM Client. A host whose owner runs pmm-agent as another user gets scripts as that user; root work there is the owner's to allow.

## Consequences

- Tasks that need root keep working on packaged installs, with nothing to configure. This is today's behavior.
- How much less than root a named user is depends on the host. That is its owner's knowledge, and the reason the choice is per task.
- PMM Extensions can ask for less than root, task by task. In the first release it does not: every task runs as it does today, and [plan 04](../plans/04-extensions-executor.md) adds the per-task setting. A task that does not ask for root is not moved to another user on its own, because it may depend on root today without saying so.
- On a packaged install, whoever can start a run can run a program as root on that host. [ADR-09](ADR-09-who-may-start-a-run.md) is what limits who that is, and `scripts.disabled` lets a host's owner refuse it.
- A script is not sandboxed beyond its user and its control group: it sees the host's file system and network as that user does. [Spec §14](../spec.md#14-not-in-scope) lists this as out of scope.
- Open question [O2](../spec.md#13-risks-and-open-questions) of the spec asks whether the default should be the non-root user instead.
