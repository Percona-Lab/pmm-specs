# Script runs in pmm-agent: roadmap and shared contract

- **Spec:** [spec.md](../spec.md), ADRs in [adr/](../adr/README.md). Read the spec before any plan; the plans argue from it and do not repeat its evidence.
- **Code base:** percona/pmm `main` at `122590fc6` and percona/pmm-extensions `main` at `285f3c96dc`. "Today" and line numbers without a commit refer to those.
- **Epic:** PMM-15976.
- **Marks:** [V], [I] and [D] as defined at the top of [spec.md](../spec.md): verified, inferred, and designed here but not built.

**Goal:** PMM Extensions runs its tasks on PMM Client hosts through pmm-agent, each run at most once and with its true outcome on record, and Nomad is gone from PMM one release later.

## How to execute these plans

- The plans are written for an AI coding agent using the superpowers skills (`writing-plans`, `executing-plans`, `subagent-driven-development`). Engineers can read them as checklists; steps use checkbox (`- [ ]`) syntax.
- A full-depth plan is executed task by task.
- A task-level plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts.
- **Nothing starts before the ADRs it rests on are Accepted.** Each plan names them. ADR-02 to ADR-14 are Proposed when this folder is first merged.
- **The prototype is a reference, not a base.** Branch `PMM-15696-proto` shows one way that worked. Each task is written again on the integration branch, test first. Copy a piece only where this folder says it is kept ([spec §7](../spec.md#7-what-the-prototype-is-and-what-changes)).

## Terms

- **Plan 0N:** a plan in this folder, by its number. **Step:** only a "Step N" checkbox inside a full-depth plan.
- **Run:** one execution of one script on one host. **Host:** a PMM node with a pmm-agent on it.
- **The caller:** PMM Extensions.
- **pmm-agent**, never just "agent". **Replica:** one pmm-managed instance; a server without HA has one.
- **Final state:** a state that never changes again ([spec §6.2](../spec.md#62-what-a-run-is)).
- **Contained:** the run has its own control group ([spec §6.5](../spec.md#65-containment)).
- **The integration branch:** `PMM-15976-script-runs` in percona/pmm.
- **Feature Build:** Jenkins builds PMM Server and Client images from the branches, through a draft PR in Percona-Lab/pmm-submodules.
- **Full-depth plan:** every task has its files, interfaces and checkbox steps. **Task-level plan:** tasks only, expanded before it starts.

## Plans and order

| Plan | Ticket | Repo | Needs | Depth |
|---|---|---|---|---|
| [01 The `run_script` job in pmm-agent](01-agent-run-script.md) | PMM-15977 | percona/pmm | ADR-02, 03, 04, 06, 07, 08, 11 | Full-depth |
| [02 Run records and the API in pmm-managed](02-managed-runs-api.md) | PMM-15978 | percona/pmm | plan 01 Task 1 (the protocol); ADR-03, 04, 05, 09, 10, 12, 13 | Full-depth |
| [03 Containment and host-side controls](03-containment.md) | PMM-15979 | percona/pmm | plan 01; ADR-06, 07, 09, 12 | Task-level |
| [04 The executor in PMM Extensions](04-extensions-executor.md) | PMM-15980 | percona/pmm-extensions | plan 02 Task 1 (the API definition); ADR-07, 08, 09, 11 | Task-level |
| [05 Switch-over and deprecation](05-switch-over.md) | PMM-15981 | both, and the docs | plans 01 to 04; ADR-14. Its last task, the merge into `main`, waits for plan 06's gate | Task-level |
| [06 Verification and release gate](06-verification.md) | PMM-15982 | percona/pmm-qa, Feature Builds | plans 01 to 05; ADR-13 | Task-level |
| [07 Remove Nomad](07-remove-nomad.md) | PMM-15983 | both, and the docs | the release that ships plans 01 to 06; ADR-14 | Task-level |
| No plan of its own: the follow-up of 07 that deletes the flags and settings 3.13.0 still accepts | PMM-15984 | both | 3.13.0 shipped | — |

Order:
- Plan 01 Task 1 (the protocol) first. Plan 02 Task 1 (the API definition) can be written beside it.
- Then plans 01 and 02 in parallel. Plan 03 follows plan 01, and plan 04 follows plan 02 Task 1: both can run while plans 01 and 02 finish.
- Plan 05 after plans 01 to 04. Plan 06 after plan 05, on a Feature Build.
- Plan 07 belongs to the release after the one that ships plans 01 to 06.

**Security design review.** It reads this folder before plan 02 Task 4 (the checks on who may call) and before plan 03. Plan 01 builds the process-group stop and the confined file read before the review; the review can change them. It looks at least at: who can start a run (ADR-09), which user a run gets (ADR-07), what a run may be told to do ([spec §6.2](../spec.md#62-what-a-run-is)), where secrets travel and rest ([spec §6.6](../spec.md#66-records-and-retention), [§9.1](../spec.md#91-who-can-start-a-run)), file reads ([spec §6.7](../spec.md#67-the-api)), and the fallback where a run is not contained (ADR-06). **Implementation review:** plan 06, on the code.

## Branch and PR rules

**percona/pmm.**
- One integration branch, `PMM-15976-script-runs`, cut from `main`. Plans 01 to 03 and the pmm part of plan 05 open their PRs into it. It merges into `main` once, for the release that ships script runs, after plan 06's gate.
- The reason: `main` is released every eight to twelve weeks, and a half-built job type or API must not ship in between.
- Keep the branch current: merge `main` into it at least weekly. Generated files are regenerated, never hand-merged.
- Default: one plan = one branch `PMM-<ticket>-<short-name>` = one PR. Titles are `PMM-<ticket> Short summary`, at most 50 characters. Sign off every commit (`git commit -s`). Review fixes are new commits.
- After a protocol, model or mock change: `make gen`. Before a PR: `make prepare-pr`.

**percona/pmm-extensions.**
- Plan 04 lands on `main`. It is safe there: the new executor is used only when the backend setting names it, and the code default stays `nomad` in 3.12.0: plan 05 changes only the bundle's profile.
- Follow that repository's own rules for branches, commits and changelog fragments.

**Docs.** In the same PRs as the code they describe. User docs under `documentation/docs/` are published from the release branch, so they stay private until the release.

## Shared contract

Names that more than one plan uses. A plan that needs to change one changes it here first, through a pmm-specs PR.

### Protocol (`api/agent/v1/agent.proto`), plan 01 Task 1

| Name | Kind | Purpose |
|---|---|---|
| `StartJobRequest.RunScript run_script` | new member of the `job` oneof | The request of [spec §6.2](../spec.md#62-what-a-run-is): `files`, `command`, `env`, `stdin`, `run_as`, `start_within`, `max_output_bytes`, `keep_files_for`, `memory_max`. The run's time limit is the existing `StartJobRequest.timeout` |
| `JobResult.RunScript run_script` | new member of the `result` oneof | `outcome` (enum), `exit_code`, `reason`, `dropped_output_bytes`, `started_at`, `finished_at` |
| `JobProgress.RunScript run_script` | new member of the `result` oneof | `started` (the process is running) and `logs` (chunks with `chunk_id`, `stream`, `data`) |
| `JobMessagesRequest` / `JobMessagesResponse` | agent to server, acknowledged | A batch of `JobProgress` and `JobResult` for `run_script` jobs. The response answers each item: stored, or discarded |
| `ListRunsRequest` / `ListRunsResponse` | server to agent | Every run id pmm-agent knows, with its phase (`waiting`, `running`, `delivering`), and the host facts: `user`, `contained`, `disabled`, the two limits. Sent on every connect, repeated until answered, and after any start that got no answer |
| `ReadRunFileRequest` / `ReadRunFileResponse` | server to agent | List `out/`, or read one file by offset and length |

All are additions. Field and oneof numbers are the next free ones at the time; plan 01 Task 1 checks them against `main` and against `buf breaking`.

Sensitive fields (`stdin`, the values of `env`, the content of `files`) are of a string kind **and** carry the `sensitive` option: log redaction on both sides covers only fields that are both (`utils/logger/protobuf.go:120-166`); plan 01 Task 1 proves it with a test that logs a request at debug level, which is where both sides log whole messages.

### States

`pending`, `queued`, `running`; final: `succeeded`, `failed`, `stopped`, `timed_out`, `expired`, `prepare_failed`, `not_started`, `lost`. The transitions are in [spec §6.2](../spec.md#62-what-a-run-is). The API enum is `RunState` with the prefix `RUN_STATE_`.

### pmm-agent settings, plans 01 and 03

| Flag | Environment variable | `pmm-agent.yaml` | Default |
|---|---|---|---|
| `--scripts-disabled` | `PMM_AGENT_SCRIPTS_DISABLED` | `scripts.disabled` | false |
| `--scripts-capacity` | `PMM_AGENT_SCRIPTS_CAPACITY` | `scripts.capacity` | 16 |
| `--scripts-queue` | `PMM_AGENT_SCRIPTS_QUEUE` | `scripts.queue` | 256 |

Set by pmm-agent for every run: `PMM_RUN_ID`, `PMM_RUN_DIR` (the working directory, where `files` are) and `PMM_RUN_OUTPUT_DIR` (`out/` inside it). A request may not set a name that starts with `PMM_RUN_` or `LD_`, nor `PATH`.

### pmm-managed, plan 02

| Name | Value |
|---|---|
| API package | `scripts.v1beta1`, service `ScriptsService`, REST under `/v1/scripts` |
| Tables | `script_runs`, `script_run_logs`, `script_stop_requests` |
| Version gate | `ScriptRunsSupportVersion` in `version/features.go`, set to the release that ships plan 01. While the integration branch builds under another version, plan 02 says where the gate is set |
| Host in `StartRun` | `pmm_agent_id`. `ListHosts` gives it for a node name |
| Hearing of a run's end | `ListRuns` with `final_after` and `wait`; `GetRun` with `wait` |
| Auth rule | `/v1/scripts`: admin. `/scripts.v1beta1.` gets the same rule as a safeguard; nginx does not expose it |
| The run's id | Chosen by the caller (a UUID). `StartRun` with an id that exists returns that record and starts nothing |
| Reasons for `not_started`, in the order they are checked | "pmm-agent is not connected"; "pmm-agent is too old to run scripts"; "script runs are switched off on this host"; "run_as needs a pmm-agent that runs as root"; "memory_max needs a host where runs are contained"; then what pmm-agent itself answered |
| Second token | Header `X-PMM-Scripts-Token`. Value: HMAC-SHA256, hex, keyed with the internal token the two already share, over the label `pmm-managed-scripts-token`. pmm-managed's internal token is what `ResolveExtensions` returns (`managed/services/om/extensions_connection.go:42-66`); PMM Extensions' is `settings.EXTENSIONS_INTERNAL_TOKEN`. One rule, in the bundle and outside it |
| Retention | 7 days after a run's final state, by a leader service |

### PMM Extensions, plan 04

| Name | Value |
|---|---|
| Backend value | `pmm_agent` in `TaskBackendEnum` |
| Settings | `TASKS.PMM_AGENT` (its own model), and `TASKS.DEFAULT_BACKEND`, which decides how the four seeded kinds are seeded and what a new task gets. A task row keeps its own backend, and a run is followed by the executor that started it |
| Time limit | PMM Extensions sends one with every run: 7 days, from one setting. No limit per task in the first release |
| Environment for payloads | `PMM_EXTENSIONS_TASK_TARGET`, `PMM_EXTENSIONS_TASK_DIR`, `PMM_EXTENSIONS_TASK_CONFIG_FILE`. No configuration in the environment |
| Step names in stored logs | Unchanged: `prepare-env`, `run-script` |
| Exit codes of the wrapper | Unchanged: 78 for "cannot be launched" |

### Limits

| Limit | Value | Where enforced |
|---|---|---|
| Content of `files` in one request | 1 MiB, text | pmm-managed, and again in pmm-agent |
| `stdin` | 1 MiB, text | the same |
| `command` and `env` together | 64 KiB | the same |
| A request from pmm-managed to pmm-agent | 10 s to answer | pmm-managed |
| Run time (`timeout`) | default 24 h, at most 7 days | pmm-managed sets the default; pmm-agent enforces |
| Wait for a slot (`start_within`) | default 1 h, at most 24 h | pmm-managed and pmm-agent |
| `memory_max` | at least 16 MiB; contained hosts only | pmm-managed checks the value, and the host from what pmm-agent reported; pmm-agent checks the host again |
| Runs at once on a host / waiting | 16 / 256 | pmm-agent |
| Output queue on the host | 4 MiB a run, 32 MiB a host | pmm-agent |
| Stored output of one run (`max_output_bytes`) | default 16 MiB, at most 100 MiB | pmm-agent counts; pmm-managed refuses more |
| Stored output of all runs | 1 GiB; the oldest finished runs' output goes first | pmm-managed's cleaner |
| The end of a run's output that is always kept | 64 KiB | pmm-agent |
| Processes in one run's group | 4,096 | pmm-agent, on contained hosts |
| `oom_score_adj` of a run | 1000 | pmm-agent |
| One batch of messages | 256 KiB | pmm-agent |
| Stop grace period | 5 s | pmm-agent |
| Shutdown | runs killed at once; 5 s for acknowledgments | pmm-agent |
| `out/` kept after the end (`keep_files_for`) | default 1 h, at most 24 h | pmm-managed and pmm-agent |
| One file read | 2 MiB | pmm-managed and pmm-agent |
| `GetRun` and `ListRuns` wait | at most 30 s | pmm-managed |

These are first values ([spec §13](../spec.md#13-risks-and-open-questions), O3). Each is a named constant in one place: the values that pmm-agent and pmm-managed both check are defined once, beside the protocol, and pmm-managed keeps only its own.

## Release gate

The release that ships script runs needs all of these, checked in plan 06:

- T1 to T26 of [spec §11](../spec.md#11-tests) pass on a Feature Build.
- The implementation security review has no open finding.
- A change of leader in PMM HA (T8) and an upgrade with a run in flight (T9) pass. Neither was tested in the spike.
- Memory on a database host with no run in flight is within 2 MiB of the same build with script runs disabled.
- The deprecation of Nomad is in the release notes, and `documentation/docs/reference/nomad.md` no longer says that Nomad will remain.
