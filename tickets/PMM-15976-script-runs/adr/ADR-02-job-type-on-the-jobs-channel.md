# ADR-02: A `run_script` job type on the Jobs channel

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 01](../plans/01-agent-run-script.md)

## Context

pmm-managed and pmm-agent talk over one bidirectional gRPC stream. Three existing mechanisms could carry a script [V]:

- **Actions** (`StartActionRequest`): 21 fixed kinds, such as EXPLAIN and pt-summary. Output is collected in memory and sent as one message; pmm-managed overwrites it and deletes it after about 30 minutes. They are open to a lower role than Jobs (`managed/services/grafana/auth_server.go:61,93-94`). The default time limit is 10 s.
- **Jobs** (`StartJobRequest`): four kinds, all backups and restores. They run for as long as they need, send log chunks that are stored in `job_logs`, and need the Admin role through `/v1/backups`.
- **Supervised processes** (`SetStateRequest`): exporters, vmagent, and today the Nomad client. pmm-agent keeps them running and restarts them.

None was built for arbitrary scripts. Jobs send their results and logs without an acknowledgment and never re-send them (`agent/client/client.go:409`); a stop kills only the direct child; pmm-managed never asks which jobs an agent still has; and `jobs` and `job_logs` are never cleaned ([spec §6.1](../spec.md#61-a-new-job-type)).

## Options

1. **A new Action kind.** Rejected: Actions are short and their output is one message. Actions are open to a lower role than Jobs, and a script must never inherit that rule.
2. **A supervised process per run.** Rejected: the supervisor keeps a process alive and restarts it. A run must happen at most once ([ADR-03](ADR-03-at-most-once.md)).
3. **A new job type, `run_script`, on the Jobs path**, with its own rules for delivery, stop and reconnect.
4. **A separate gRPC service or a second stream for scripts.** Rejected: a second connection to authenticate, keep alive and reason about in HA, for no gain. The spike measured a whole run of a small script at 0.07 s over the existing stream, called directly.

## Decision

Option 3.

- `run_script` is a new member of `StartJobRequest`'s oneof, with its own result and progress members. It shares two of the Jobs path's requests, `StartJobRequest` and `StopJobRequest`. In pmm-agent it has a manager of its own: it is not one of the runner's jobs.
- It does **not** use the Jobs path's delivery. Its messages travel in an acknowledged request ([ADR-04](ADR-04-acknowledged-delivery.md)).
- It has its own slots and queue in pmm-agent, apart from the runner's 32, so scripts cannot delay Actions.
- The rules of [ADR-03](ADR-03-at-most-once.md) to [ADR-06](ADR-06-stop-and-containment.md) apply to `run_script` only. The four backup jobs keep their behavior: this epic does not change how backups are delivered, stopped or stored.

## Consequences

- The protocol change is additions only, which is what `buf breaking` allows.
- An agent below the version gate is never sent the new type ([ADR-14](ADR-14-mixed-versions-and-nomad-removal.md)).
- Two delivery behaviors exist side by side on one channel until backups move to the acknowledged path. That move is outside this epic; the mechanism is written so that they can.
- The prototype changed how every job type's log chunk is inserted. That change is not carried: run output has its own table ([ADR-05](ADR-05-run-records-and-retention.md)).
