# ADR-05: Run records in their own tables, with retention

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 02](../plans/02-managed-runs-api.md)

## Context

A run needs a record on PMM Server: its state, its reason, its output until the caller has copied it, and stops that are not yet delivered.

pmm-managed has `jobs` and `job_logs` for backups [V]:
- `jobs` has one JSON column for the request and one for the result, a `done` flag and an `error` text, plus `retries` and `interval` for retried backups. It has no state, and no link from a job to its agent that is enforced (`managed/models/database.go:521-534`, `:652-664`).
- `job_logs` is keyed by `(job_id, chunk_id)` and has no column for the stream.
- Neither is ever cleaned: `CleanupOldJobs` exists and has no caller (`managed/models/job_helpers.go:156-160`).

The prototype stores runs in those tables. To do so it adds a column to `job_logs` when pmm-managed starts, outside the migration list, and changes how every job type's log chunk is inserted [V].

PMM Extensions is the system of record for task history. It keeps its own rows without limit, and its own copy of the output for 90 days (`app/tasks/config.py:234-236`, `app/tasks/celery.py:574-582` in percona/pmm-extensions) [V]. The spike's first round measured 2,449 kept runs at 3.4 MB of tables, and a line of output a second at 4.2 MB an hour [V].

## Options

1. **Reuse `jobs` and `job_logs`** (the prototype). Rejected: retention would have to delete from tables that hold backup history; a run needs fields those tables lack; and the change of the shared insert touches backups.
2. **Own tables.**
3. **No record in pmm-managed; relay everything to the caller as it arrives.** Rejected: delivery would then depend on PMM Extensions being up at every moment, and a held stop needs a home in any case.

## Decision

Option 2, through one entry at the end of the migration list in `managed/models/database.go`.

- `script_runs`: one row per run. It holds the state and its reason, the exit code, the times of each state, bytes stored and dropped, and the request without its secrets: file names with their sizes and SHA-256, the command, the names of the environment variables, the user, the limits.
- `script_run_logs`: `(run_id, chunk_id)` as the key, the stream, the data. Rows go when the run goes.
- `script_stop_requests`: stops not yet delivered.
- **Never stored:** the content of `files`, the values of `env`, and `stdin`.
- **Retention:** a finished run and its output are deleted 7 days after its final state, by a leader service, as the existing cleaner does for Action results (`managed/cmd/pmm-managed/main.go:1366`).
- One run's stored output is capped by `max_output_bytes`: 16 MiB by default, 100 MiB at most.
- All stored output together is held to 1 GiB: beyond that the cleaner deletes the output of the oldest finished runs first. The output of open runs is never deleted, so the total can pass 1 GiB for as long as open runs alone hold more than that (open question [O6](../spec.md#13-risks-and-open-questions) of the spec).
- A file can be marked sensitive. Its SHA-256 is then not stored either: the hash of a short secret can be guessed.

## Consequences

- Backup tables and backup code are not touched.
- PostgreSQL's growth is bounded by 7 days of runs, by the total cap, and by each open run's own cap while it runs. An install that runs one task a minute with 10 KiB of output holds about 100 MiB. The cap matters most in PMM HA, where PostgreSQL's volume is 10 GB by default.
- A caller that reads a run later than 7 days after its end gets "not found". PMM Extensions has its own copy by then.
- The command and the file names of a run are stored in clear. A caller must not put a secret in an argument or a file name; secrets go in `stdin` or a file's content.
- One more migration on a list that grows quickly: ten were added in the six weeks before this was written. The number is chosen when the PR is opened.
