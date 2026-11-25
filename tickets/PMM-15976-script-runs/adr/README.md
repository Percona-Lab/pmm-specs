# Architecture decision records

This folder records the architecture decisions for script runs in pmm-agent (epic [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)). Each file records one decision, with the rules that make it up.

**Format.** Each record has these sections:
- **Context:** why a decision was needed;
- **Options:** what was considered; each rejected option says why it was rejected;
- **Decision:** what was chosen;
- **Consequences:** what follows from it, good and bad.

The header gives the status, the date, the Jira tickets involved, and the plans that build it.

**Marks:** **[V]** means verified by reading the code, or measured in the spike [PMM-15696](https://perconadev.atlassian.net/browse/PMM-15696); **[I]** means inferred, or taken from upstream documentation, and not run. Paths without a repository are in percona/pmm at `122590fc6`.

**Numbers** such as limits and defaults are in [the roadmap](../plans/00-roadmap.md#limits); a record states the mechanism and points there, so tuning a value doesn't need a new record. The spike's measurements are in [spec §4](../spec.md#4-what-the-spike-measured).

**Statuses:**
- **Proposed:** written and waiting for review by the PMM architects.
- **Accepted:** reviewed and in force.
- **Superseded by ADR-NN:** replaced; the record stays for history.

**Rules:**
- Never rewrite an accepted record to change its decision. Add a new ADR that supersedes it.
- Number records in sequence, as `ADR-NN-short-title.md`.

## Index

[ADR-01](ADR-01-pmm-agent-replaces-nomad.md) records the choice made on 2026-11-17, when the results of the spike were reviewed. [ADR-02](ADR-02-job-type-on-the-jobs-channel.md) to [ADR-14](ADR-14-mixed-versions-and-nomad-removal.md) are the design that follows from it. They are Proposed until this folder's pull request is reviewed; [ADR-06](ADR-06-stop-and-containment.md), [ADR-07](ADR-07-run-as-user.md) and [ADR-09](ADR-09-who-may-start-a-run.md) also wait for the security design review ([roadmap](../plans/00-roadmap.md#plans-and-order)).

| ADR | Title | Status | Planned in |
|---|---|---|---|
| [01](ADR-01-pmm-agent-replaces-nomad.md) | pmm-agent replaces Nomad | Accepted | [Plans 01](../plans/01-agent-run-script.md) to [07](../plans/07-remove-nomad.md) |
| [02](ADR-02-job-type-on-the-jobs-channel.md) | A `run_script` job type on the Jobs channel | Proposed | [Plan 01](../plans/01-agent-run-script.md) |
| [03](ADR-03-at-most-once.md) | A run happens at most once, and a final state is final | Proposed | [Plans 01](../plans/01-agent-run-script.md), [02](../plans/02-managed-runs-api.md) |
| [04](ADR-04-acknowledged-delivery.md) | Acknowledged delivery with a bounded queue | Proposed | [Plans 01](../plans/01-agent-run-script.md), [02](../plans/02-managed-runs-api.md) |
| [05](ADR-05-run-records-and-retention.md) | Run records in their own tables, with retention | Proposed | [Plan 02](../plans/02-managed-runs-api.md) |
| [06](ADR-06-stop-and-containment.md) | Stop and containment: one control group per run | Proposed | [Plans 01](../plans/01-agent-run-script.md), [03](../plans/03-containment.md) |
| [07](ADR-07-run-as-user.md) | Which OS user a script runs as | Proposed | [Plans 03](../plans/03-containment.md), [04](../plans/04-extensions-executor.md) |
| [08](ADR-08-script-content-inline.md) | Script content travels inline; the host fetches nothing | Proposed | [Plans 01](../plans/01-agent-run-script.md), [04](../plans/04-extensions-executor.md) |
| [09](ADR-09-who-may-start-a-run.md) | Who may start a run, and the default state | Proposed | [Plans 02](../plans/02-managed-runs-api.md), [03](../plans/03-containment.md), [04](../plans/04-extensions-executor.md) |
| [10](ADR-10-api-shape.md) | A beta gRPC service behind grpc-gateway | Proposed | [Plan 02](../plans/02-managed-runs-api.md) |
| [11](ADR-11-one-execution-path.md) | One execution path; no unrecorded short call | Proposed | [Plans 01](../plans/01-agent-run-script.md), [04](../plans/04-extensions-executor.md) |
| [12](ADR-12-host-list.md) | The host list comes from the registry and the existing ping | Proposed | [Plans 02](../plans/02-managed-runs-api.md), [03](../plans/03-containment.md) |
| [13](ADR-13-high-availability.md) | No run state in a replica's memory | Proposed | [Plans 02](../plans/02-managed-runs-api.md), [06](../plans/06-verification.md) |
| [14](ADR-14-mixed-versions-and-nomad-removal.md) | Mixed versions, and the removal of Nomad in two releases | Proposed | [Plans 05](../plans/05-switch-over.md), [07](../plans/07-remove-nomad.md) |
