# Plan 01: The `run_script` job in pmm-agent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, as [00](00-roadmap.md#how-to-execute-these-plans) describes. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pmm-agent runs one program per `run_script` request, at most once, with a fixed environment, its own slots and queue, a time limit and a stop that reaches the process group. Its output and its result reach pmm-managed in acknowledged batches through a bounded queue that never makes the script wait and that keeps the start and the end of a run's output. pmm-agent answers `ListRunsRequest` with every run it knows, serves the files of `out/` without following links, removes run directories, keeps its runs across a configuration reload, and on shutdown kills every run at once and waits at most 5 s for acknowledgments.

**Architecture:** Task 1 adds the protocol of the [shared contract](00-roadmap.md#protocol-apiagentv1agentproto-plan-01-task-1) to `api/agent/v1/agent.proto`, the limits both sides check, and every case the tree needs to build and lint with the new messages; plan 02 builds on it. Everything else is a new package, `agent/runner/scripts`, with one `Manager` per pmm-agent process: it is created before the configuration loop of `agent/commands/run.go` and lives until the process ends, so a reload does not touch its runs. It is not a `jobs.Job` under `runner.Runner`: only the two request messages (`StartJobRequest`, `StopJobRequest`) are shared with backup jobs. The runner's slots (32 by default, `agent/runner/runner.go:43`) serve Actions too, and its `Send` path is the unacknowledged one ([ADR-02](../adr/ADR-02-job-type-on-the-jobs-channel.md)). The client routes `StartJobRequest{run_script}`, `StopJobRequest`, `ListRunsRequest` and `ReadRunFileRequest` to the `Manager`, and a new per-connection loop, `processScriptMessages`, sends what the `Manager`'s outbox holds and applies the answers. Pure parts (request checks, the outbox, batching) are unit-tested on values; process tests start real `/bin/sh` processes on Linux. No new interface and no mock: the client holds a `*scripts.Manager` as it holds a `*runner.Runner`. `ListRunsRequest` of the agent protocol is not the API's `ListRuns` RPC of plan 02, which returns the runs that became final after a cursor; the names are alike, and nothing in pmm-agent serves the API.

**Tech Stack:** Go 1.27 (`go.mod:3`), protobuf through buf (`api/buf.yaml`, `go tool buf`), `golang.org/x/sys/unix`, logrus, kingpin v2, testify.

**Spec:** [spec §6.1–§6.4](../spec.md#61-a-new-job-type), [§6.5 Stop](../spec.md#65-containment) (the process-group part), [§6.7 file reads](../spec.md#67-the-api), [§7](../spec.md#7-what-the-prototype-is-and-what-changes), [§9.1 Secrets](../spec.md#91-who-can-start-a-run), [§9.3](../spec.md#93-versions); [ADR-02](../adr/ADR-02-job-type-on-the-jobs-channel.md), [ADR-03](../adr/ADR-03-at-most-once.md), [ADR-04](../adr/ADR-04-acknowledged-delivery.md), [ADR-06](../adr/ADR-06-stop-and-containment.md), [ADR-07](../adr/ADR-07-run-as-user.md), [ADR-08](../adr/ADR-08-script-content-inline.md), [ADR-11](../adr/ADR-11-one-execution-path.md); names and limits in [00](00-roadmap.md#shared-contract). Ticket PMM-15977.

## Global Constraints

The roadmap's branch rules and shared contract apply. In addition:

- **Code base:** percona/pmm `main` at `122590fc6` or later, through the integration branch `PMM-15976-script-runs`. Two branches and two PRs into it:
  - `PMM-15977-run-script-protocol` for Task 1, PR `PMM-15977 Add the run_script protocol`, merged first, because plan 02 starts from it ([00](00-roadmap.md#plans-and-order));
  - `PMM-15977-run-script` for Tasks 2 to 10, cut after the first PR is merged.
- **The security design review.** Task 4 (the process-group stop) and Task 7 (the confined file read) build parts of ADR-06 and ADR-07 before the review ([00](00-roadmap.md#plans-and-order)); the review can change them, and a change comes back to this plan through a pmm-specs PR.
- **Nothing outside `run_script` changes behavior.** `agent/runner/runner.go`, `agent/runner/jobs/` and `processJobsResults` (`agent/client/client.go:401-417`) stay as they are; backup jobs keep their unacknowledged delivery (ADR-02).
- **Not in this plan (plan 03):** control groups, the unit file, `run_as`, `--scripts-disabled`, the leftover-process sweep at start-up and by the environment mark, and the host facts of `ListRunsResponse` (`user`, `contained`, `disabled`, `capacity`, `queue`). Until plan 03:
  - a request with `run_as` set is refused with `run_as needs a pmm-agent that runs as root` when pmm-agent is not root, and ends `prepare_failed` with `run_as is not supported by this pmm-agent` when it is;
  - a request with `memory_max` set is refused with `memory_max needs a host where runs are contained`, because no run is contained before plan 03;
  - the host facts are left at their zero values. The integration branch is not released in between.
- **`oom_score_adj` is this plan's.** Every run gets `oom_score_adj` 1000 where the process is started (Task 4), contained or not; plan 03 does not repeat it.
- **Limits are named constants in one place:** a new file `api/agent/v1/scripts.go`, beside the protocol. pmm-managed (plan 02) imports the values both sides check and keeps only its own.
- **Linux only.** On other systems `Manager.Start` refuses every run at once with `script runs need Linux`, which pmm-managed records as `not_started`; pmm-agent already builds elsewhere through stubs such as `utils/pdeathsig/pdeathsig.go` (`//go:build !linux`) [V].
- **Version gate.** pmm-managed sends `run_script` only to pmm-agents at or above the gate of plan 02, which names the release that ships this plan. Nothing in pmm-agent checks a version.
- **pmm-managed waits at most 10 s** for the answer to each request it sends for script runs: start, stop, list, read file (plan 02). Every handler here answers from memory, or from one read of at most 2 MiB, well inside that.
- **The request loop never waits.** `processChannelRequests` (`agent/client/client.go:568-655`) is the only reader of the channel's requests, and a handler that blocks there stalls the connection (`agent/AGENTS.md`, "The request loop must never block indefinitely"). `Start`, `Stop` and `ListRuns` return at once; `ReadRunFile` is answered from its own goroutine.
- **Code form.** The sketches below follow the repository's rules (root `AGENTS.md`, Code Style; `.golangci.yml`): no named results, comments above a line, not beside it. New files carry the license header of their tree (`.licenserc.yaml`): AGPL-3.0 under `api/` and `managed/`, Apache-2.0 under `agent/` and `utils/`.
- **Tests:** single packages with `go test -race -count=1 -run '<names>' ./agent/runner/scripts/` from the repository root (one Go module, `go.mod`); the whole agent with `cd agent && make test` (`agent/Makefile:66`, race detector, `-p 1`). The agent's tests run with `-timeout=80s` per package (`agent/Makefile:64`), so the package's tests together stay well under 80 s under `-race`: the grace period, the drain time, the shutdown budget and the keep period come from `Config` (Task 6), and tests set them to tens of milliseconds; only Task 4's escalation test waits for the real 5 s. The agent CI job runs on an Ubuntu host, not in a container (`.github/workflows/agent.yml:34,82`) [V], so process tests run there. Before each PR: `make gen` (runs `buf breaking` against `api/descriptor.bin`, `api/Makefile:6`), `make check` (buf lint, golangci-lint, go-sumtype, `Makefile.include:49-52`), `make prepare-pr` (`Makefile.include:75`).

## Review Focus

1. **A script that prints during a long cut.** Expected: the script never blocks; pmm-agent holds at most 4 MiB for the run and 32 MiB for the host; the start of the run's output and its last 64 KiB reach pmm-managed, and the result says how many bytes were dropped between them (T14). Tests: `TestOutboxBoundPerRun`, `TestOutboxBoundPerHost`, `TestOutboxKeepsTail` (Task 5).
2. **A result that overtakes its own output.** Expected: a run's result goes into a batch only when every earlier item of that run is answered, so a partial store can never leave a final record with output still to come. Test: `TestBatchHoldsResultUntilChunksAcked` (Task 5).
3. **pmm-managed answers part of a batch.** Expected: items answered `stored` or `discarded` leave the outbox; items with no answer go again in a later batch, after a delay. A discarded result takes its run out of `delivering`. Tests: `TestAcknowledgeAnswers` (Task 5), `TestScriptMessagesRetriedWithoutAnswer`, `TestScriptMessagesDiscarded` (Task 8).
4. **A reconnect with messages in flight.** Expected: the same messages are sent first on the next connection, and nothing is lost or reordered (T1, T2 on the host side). Test: `TestScriptMessagesResentAfterReconnect` (Task 8).
5. **A pmm-managed replica that does not know `JobMessagesRequest`** (mixed versions in HA). Expected: pmm-agent waits, with a growing pause, before it sends again. Test: `TestScriptMessagesUnimplementedBacksOff` (Task 8).
6. **A run still waiting for a slot when pmm-managed asks.** Expected: it is in `ListRunsResponse` as `waiting`, so it is never marked lost by mistake (ADR-03). Test: `TestListRunsPhases` (Task 6).
7. **A stop of a waiting run, and a wait longer than `start_within`.** Expected: `stopped` and `expired` respectively, without a slot and without a process. Tests: `TestStopWhileWaiting`, `TestExpiredWhenNoSlot` (Task 6).
8. **A script that ignores SIGTERM, a grandchild that keeps the pipes open, and a script that does not read its `stdin`.** Expected: SIGKILL to the group after the grace period; the run ends at most 2 s after its process, whatever holds the pipes. Tests: `TestStopEscalatesToKill`, `TestRunEndsWhileGrandchildHoldsPipe`, `TestRunEndsWithUnreadStdin` (Task 4).
9. **A request that sets `PATH`, `LD_PRELOAD` or `PMM_RUN_ID`, or whose `command` and `env` exceed 64 KiB, or whose `start_within` exceeds 24 h.** Expected: refused before anything is written. Tests: `TestParseRequestRefusedEnv`, `TestParseRequestSizes`, `TestParseRequestLimits` (Task 3).
10. **Output with NUL bytes or bytes that are not UTF-8.** Expected: both replaced, so that one chunk cannot fail its store for ever. Test: `TestPumpReplaces` (Task 5).
11. **A file read through a symbolic link, a hard link, a FIFO, a directory or `..`.** Expected: an error, and no file outside `out/` is read. Test: `TestReadRunFileConfined` (Task 7).
12. **`systemctl stop pmm-agent` with runs in flight.** Expected: every run is killed at once and ends `lost` with `pmm-agent was stopped`; pmm-agent waits at most 5 s for acknowledgments and exits, inside supervisord's `stopwaitsecs = 10` on PMM Server's own pmm-agent (`managed/services/supervisord/pmm_config.go:188`); what was acknowledged before the exit is all there is. Tests: `TestShutdownWithinDeadline`, `TestShutdownWithoutConnection` (Task 9).
13. **A configuration reload with runs in flight.** Expected: the runs go on; their output and results reach pmm-managed over the connection after the reload. Tests: `TestScriptMessagesSurviveNewClient` (Task 8), `TestCleanupTmpKeepsRunScript` (Task 9).
14. **The same `job_id` sent twice.** Expected: the second start is refused; one process. Test: `TestDuplicateStartRefused` (Task 6).
15. **A command that names one of its own files.** Expected: `["sh", "wrapper.sh"]` finds `wrapper.sh`, because the working directory is the run directory. Test: `TestProcessFindsItsFiles` (Task 4).
16. **A run that fills the host's memory.** Expected: the kernel picks the run first, through `oom_score_adj` 1000 (the measurement is T5, plan 06). Test: `TestOOMScoreAdj` (Task 4).
17. **Secrets in logs.** Expected: `stdin`, `env` values and file contents never appear in pmm-agent's or pmm-managed's message logs (T13, the log part). Test: `TestRedactRunScript` (Task 1).

---

### Task 1: The protocol, the shared limits, and a tree that builds

**Files:**
- Modify: `api/agent/v1/agent.proto` (`StartJobRequest` :521-616, `JobResult` :632-665, `JobProgress` :668-688, `AgentMessage` :735-765, `ServerMessage` :767-795)
- Modify: `api/agent/v1/agent.go` (payload methods :66-252, `sealed()` list :254-286, the interface checks from :288)
- Create: `api/agent/v1/scripts.go` (the limits; AGPL-3.0 header)
- Modify: `agent/client/channel/channel.go` (`runReceiver` switch :389-451), `managed/services/agents/channel/channel.go` (`runReceiver` switch :270-343)
- Modify: `managed/services/agents/handler.go` (the request switch :120-176, which has no `default`, so go-sumtype requires a case for every request payload)
- Generated by `make gen`: `api/agent/v1/agent.pb.go`, `agent.pb.validate.go` and the gRPC file next to them. Never edited by hand.
- Test: `utils/logger/protobuf_test.go` (next to `TestRedactMessage` :342), `agent/client/channel/channel_test.go`, `managed/services/agents/channel/channel_test.go`

**Interfaces:**

Numbers are taken after the highest one in each oneof at `122590fc6` [V]: `StartJobRequest.job` uses 11–14, `JobResult.result` 10 and 12–15, `JobProgress.result` 11, 12 and 20, `AgentMessage.payload` up to 22, `ServerMessage.payload` up to 20. Gaps are not filled, whether or not they held a removed field. Re-check against the `main` the branch is cut from.

```proto
// In StartJobRequest:
  // RunScript runs one program on the host, once (spec §6.2). StartJobRequest.job_id is the
  // run's id, chosen by the caller.
  message RunScript {
    // File is written into the run directory before the start.
    message File {
      // A name without a path.
      string name = 1;
      // Text: valid UTF-8. A string, not bytes: the log redaction covers string fields only.
      string content = 2 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
      // Owner bits only: 0400, 0500, 0600 or 0700. 0 means 0600.
      uint32 mode = 3;
      // pmm-managed stores neither the content nor its hash. pmm-agent treats the file like any other.
      bool sensitive = 4;
    }
    repeated File files = 1;
    // The program and its arguments. pmm-agent never passes them through a shell.
    repeated string command = 2;
    map<string, string> env = 3 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
    // Text, written to the process's standard input, which is then closed.
    string stdin = 4 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
    // Empty means pmm-agent's own user.
    string run_as = 5;
    google.protobuf.Duration start_within = 6;
    int64 max_output_bytes = 7;
    google.protobuf.Duration keep_files_for = 8;
    // Bytes; 0 means no limit.
    int64 memory_max = 9;
  }
  // oneof job:
    RunScript run_script = 15;

// In JobResult:
  message RunScript {
    enum Outcome {
      OUTCOME_UNSPECIFIED = 0;
      OUTCOME_SUCCEEDED = 1;
      OUTCOME_FAILED = 2;
      // Stopped on request.
      OUTCOME_STOPPED = 3;
      OUTCOME_TIMED_OUT = 4;
      OUTCOME_EXPIRED = 5;
      OUTCOME_PREPARE_FAILED = 6;
      // pmm-agent ended the run itself because it was stopping.
      OUTCOME_LOST = 7;
    }
    Outcome outcome = 1;
    // -1 when the process did not exit by itself, or never started.
    int32 exit_code = 2;
    string reason = 3;
    int64 dropped_output_bytes = 4;
    google.protobuf.Timestamp started_at = 5;
    google.protobuf.Timestamp finished_at = 6;
  }
  // oneof result:
    RunScript run_script = 16;

// In JobProgress:
  message RunScript {
    enum Stream {
      STREAM_UNSPECIFIED = 0;
      STREAM_STDOUT = 1;
      STREAM_STDERR = 2;
    }
    message Chunk {
      // Counts up from 0 per run, over both streams.
      uint32 chunk_id = 1;
      Stream stream = 2;
      string data = 3;
    }
    // The process is running.
    bool started = 1;
    repeated Chunk logs = 2;
  }
  // oneof result:
    RunScript run_script = 21;

// JobMessagesRequest is an AgentMessage: a batch of run_script progress and results. pmm-managed answers it.
message JobMessagesRequest {
  message Message {
    oneof message {
      JobProgress progress = 1;
      JobResult result = 2;
    }
  }
  repeated Message messages = 1;
}

// JobMessagesResponse is a ServerMessage: one answer per item of the request.
message JobMessagesResponse {
  enum Answer {
    // No answer: pmm-agent sends the item again.
    ANSWER_UNSPECIFIED = 0;
    ANSWER_STORED = 1;
    // The item is not stored and will not be; pmm-agent drops it.
    ANSWER_DISCARDED = 2;
  }
  // In the order of JobMessagesRequest.messages. A missing tail means no answer.
  repeated Answer answers = 1;
}

// ListRunsRequest is a ServerMessage asking for every run pmm-agent knows.
message ListRunsRequest {}

// ListRunsResponse is an AgentMessage.
message ListRunsResponse {
  enum Phase {
    PHASE_UNSPECIFIED = 0;
    PHASE_WAITING = 1;
    PHASE_RUNNING = 2;
    // Finished; the result is not answered yet.
    PHASE_DELIVERING = 3;
  }
  message Run {
    string job_id = 1;
    Phase phase = 2;
  }
  repeated Run runs = 1;
  // Host facts, filled by plan 03.
  string user = 2;
  bool contained = 3;
  bool disabled = 4;
  uint32 capacity = 5;
  uint32 queue = 6;
}

// ReadRunFileRequest is a ServerMessage: list out/, or read one file of it.
message ReadRunFileRequest {
  string job_id = 1;
  // Empty lists the directory.
  string name = 2;
  int64 offset = 3;
  // At most 2 MiB; 0 means 2 MiB.
  int64 length = 4;
}

// ReadRunFileResponse is an AgentMessage.
message ReadRunFileResponse {
  message File {
    string name = 1;
    int64 size = 2;
  }
  string error = 1;
  bytes data = 2;
  // Size of the whole file.
  int64 size = 3;
  repeated File files = 4;
}

// AgentMessage.payload, a request from pmm-agent and two responses:
    JobMessagesRequest job_messages = 23;
    ListRunsResponse list_runs = 24;
    ReadRunFileResponse read_run_file = 25;
// ServerMessage.payload, a response from pmm-managed and two requests:
    JobMessagesResponse job_messages = 21;
    ListRunsRequest list_runs = 22;
    ReadRunFileRequest read_run_file = 23;
```

- Go names to expect from generation: `agentv1.StartJobRequest_RunScript` (the message) and `agentv1.StartJobRequest_RunScript_` (the oneof wrapper), and the same pattern for `JobResult` and `JobProgress`.
- `api/agent/v1/agent.go`: `JobMessagesRequest` is an `AgentRequestPayload` (`AgentMessageRequestPayload`); `ListRunsResponse` and `ReadRunFileResponse` are `AgentResponsePayload`; `JobMessagesResponse` is a `ServerResponsePayload`; `ListRunsRequest` and `ReadRunFileRequest` are `ServerRequestPayload`. Each gets `sealed()` and a line in the interface checks.
- **The channels.** Both `runReceiver` switches get every new case here, and plan 02 does not touch them: requests become `ServerRequest`/`AgentRequest`, responses go to `publish`.
- **`managed/services/agents/handler.go`.** The request switch gets `case *agentv1.JobMessagesRequest:`, which logs a warning that script messages are not handled yet and sends no answer. pmm-managed never sends `run_script` before plan 02's gate exists, so no pmm-agent sends the request; plan 02 Task 6 replaces the case with the real handling. `make check` names any other switch that go-sumtype requires to grow; each gets the same kind of stub in this task.
- `api/agent/v1/scripts.go` (new file): every limit of [the roadmap's table](00-roadmap.md#limits) that pmm-agent applies, and those that both sides check. pmm-managed imports these and defines only its own (plan 02):

```go
const (
	RunScriptMaxFilesBytes         = 1 << 20
	RunScriptMaxStdinBytes         = 1 << 20
	RunScriptMaxCommandEnvBytes    = 64 << 10
	RunScriptDefaultTimeout        = 24 * time.Hour
	RunScriptMaxTimeout            = 7 * 24 * time.Hour
	RunScriptDefaultStartWithin    = time.Hour
	RunScriptMaxStartWithin        = 24 * time.Hour
	RunScriptDefaultMaxOutputBytes = 16 << 20
	RunScriptMaxOutputBytes        = 100 << 20
	RunScriptDefaultFileMode       = 0o600
	RunScriptDefaultKeepFilesFor   = time.Hour
	RunScriptMaxKeepFilesFor       = 24 * time.Hour
	RunScriptDefaultCapacity       = 16
	RunScriptDefaultQueue          = 256
	RunScriptRunQueueBytes         = 4 << 20
	RunScriptHostQueueBytes        = 32 << 20
	RunScriptKeptTailBytes         = 64 << 10
	RunScriptMaxBatchBytes         = 256 << 10
	RunScriptStopGrace             = 5 * time.Second
	RunScriptShutdownTimeout       = 5 * time.Second
	RunScriptMaxReadBytes          = 2 << 20
	RunScriptOOMScoreAdj           = 1000
	RunScriptPidsMax               = 4096

	RunScriptIDEnv        = "PMM_RUN_ID"
	RunScriptDirEnv       = "PMM_RUN_DIR"
	RunScriptOutputDirEnv = "PMM_RUN_OUTPUT_DIR"
)
```

- `files[].content` and `stdin` are text: `string` fields, so the redaction covers them and Go's protobuf refuses one that is not valid UTF-8 [I]. Binary content is not carried in the first release.

- [ ] **Step 1: Write the failing redaction test.** `TestRedactRunScript` in `utils/logger/protobuf_test.go`: a `ServerMessage` with a `StartJobRequest` whose `run_script` has `stdin`, one `env` value and one file content each set to a distinct secret. `prototext.Format(logger.RedactMessage(msg))` contains none of the three secrets, and still contains the env name, the file name and the command. This is the format both channels log whole messages in, at debug level (`agent/client/channel/channel.go:338-345`, `managed/services/agents/channel/channel.go:228-232, 263-267`) [V]; `RedactMessage` walks lists and maps of messages (`utils/logger/protobuf.go:55-101`) and redacts string, repeated-string and map-string values that carry the option (`:120-166`) [V].
- [ ] **Step 2: Write the failing channel tests.**
  - `agent/client/channel/channel_test.go`: `TestServerRequestListRuns`, `TestServerRequestReadRunFile` (the fake server sends the request; `channel.Requests()` yields the payload with its id); `TestJobMessagesAcknowledged` (`SendAndWaitResponse(ctx, &agentv1.JobMessagesRequest{...})` returns the server's `*agentv1.JobMessagesResponse`). Use the existing `setup(t, connect, ...)` helper, as `TestAgentRequest` (:165) does.
  - `managed/services/agents/channel/channel_test.go`: `TestAgentRequestJobMessages` (the agent's request reaches `Requests()`), `TestServerRequestListRuns` (`SendAndWaitResponse` returns the agent's `*agentv1.ListRunsResponse`), `TestServerRequestReadRunFile`.
- [ ] **Step 3: Run them:** `go test -count=1 -run TestRedactRunScript ./utils/logger/ && go test -race -count=1 -run 'ListRuns|ReadRunFile|JobMessages' ./agent/client/channel/ ./managed/services/agents/channel/` → FAIL to compile (`undefined: agentv1.StartJobRequest_RunScript`, `agentv1.ListRunsRequest`).
- [ ] **Step 4: Implement.** The proto additions above, with a comment on every message and field; `agent.go`; `scripts.go`; the channel cases; the `handler.go` stub. Run `make gen`. It runs `go tool buf breaking --against descriptor.bin` first (`api/Makefile:6`) and must report nothing.
- [ ] **Step 5: Run again:** the commands of Step 3 → PASS. `go tool buf lint -v api` → no findings (nested enum values carry the enum's prefix and a `_UNSPECIFIED` zero, as `SYSTEM_SERVICE_*` at `agent.proto:348-352` does). `make check` → no new findings, go-sumtype included (`Makefile.include:52`). `go build ./...` → the whole tree builds.
- [ ] **Step 6: Commit** `PMM-15977 Add the run_script protocol`, signed off (`git commit -s`). Open the PR from `PMM-15977-run-script-protocol` into `PMM-15976-script-runs` and merge it before Task 2's branch is cut.

---

### Task 2: Settings for slots and queue

**Files:**
- Modify: `agent/config/config.go` (`Config` :172-203, flags next to `runner-capacity` :502-505)
- Modify: `documentation/docs/use/commands/pmm-agent.md` (the options table from :45)
- Test: `agent/config/config_test.go` (`TestGet` :116, `TestMergeFlags` :615)

**Interfaces:**
- `type Scripts struct { Capacity uint16 \`yaml:"capacity,omitempty"\`; Queue uint16 \`yaml:"queue,omitempty"\` }` and a field `Scripts Scripts \`yaml:"scripts,omitempty"\`` in `Config`. Plan 03 adds `Disabled` to the same struct.
- Flags `--scripts-capacity` (`PMM_AGENT_SCRIPTS_CAPACITY`) and `--scripts-queue` (`PMM_AGENT_SCRIPTS_QUEUE`), `Uint16Var`, **no kingpin default**: 0 means the default of `api/agent/v1/scripts.go`, as `runner-capacity` does (`agent/runner/runner.go:88-90`) [V]. A flag default would overwrite the file's value on `MergeFlags` (`config.go:403-425`, which handles the one setting that has a default) [V].
- The values are read when pmm-agent starts. A reload does not change them (Task 9).

- [ ] **Step 1: Write failing tests.** In `TestGet`: a config file with `scripts: {capacity: 4, queue: 8}` gives 4 and 8; the flags win over the file; the environment variables are read. In `TestMergeFlags`: a file with `scripts.capacity: 4` and no flag keeps 4.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestGet|TestMergeFlags' ./agent/config/` → FAIL (unknown field `Scripts`).
- [ ] **Step 3: Implement** the struct, the field and the two flags. Add both flags to the options table of `pmm-agent.md`, with their variables, defaults, and that a change applies after a restart of pmm-agent.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `PMM-15977 Add script slot and queue settings`.

---

### Task 3: Checking a request

**Files:**
- Create: `agent/runner/scripts/request.go`
- Test: `agent/runner/scripts/request_test.go`

**Interfaces:**

```go
// Request is a checked run_script request with every default applied.
type Request struct {
	JobID          string
	Files          []File
	Command        []string
	Env            map[string]string
	Stdin          string
	RunAs          string
	Timeout        time.Duration
	StartWithin    time.Duration
	MaxOutputBytes int64
	KeepFilesFor   time.Duration
	MemoryMax      int64
}

// File is one file of a request.
type File struct {
	Name    string
	Content string
	Mode    os.FileMode
}

// ParseRequest refuses a request that must not start. Its error text becomes StartJobResponse.error,
// which pmm-managed records as not_started with that reason (plan 02).
func ParseRequest(jobID string, timeout *durationpb.Duration, p *agentv1.StartJobRequest_RunScript) (*Request, error)
```

Rules, each with its own error text:
- `jobID` is one path component: not empty, not `.` or `..`, no `/` and no NUL. It names the run directory. pmm-managed sends the caller's UUID.
- `command` has at least one element; no element holds a NUL.
- Each file name is one path component, is not `out` (the output directory), and appears once. All contents together are at most `RunScriptMaxFilesBytes`. Mode: 0 becomes 0600; otherwise one of 0400, 0500, 0600 and 0700; anything else is refused.
- An `env` name is not empty and holds no `=` or NUL; a value holds no NUL. Refused names: `PATH`, any name starting with `PMM_RUN_`, any name starting with `LD_` ([spec §6.2](../spec.md#62-what-a-run-is)). That is hygiene, not a control: the command may be any program.
- `stdin` is at most `RunScriptMaxStdinBytes`.
- `command` and `env` together are at most `RunScriptMaxCommandEnvBytes`, counted as the bytes of every command element plus every env name and value. With 1 MiB of files and 1 MiB of `stdin`, this keeps a request well under gRPC's default receive limit of 4 MiB, which nothing in `agent/` raises [I].
- `timeout`: `handleStartJobRequest` refuses an invalid or absent duration with `CheckValid` before this is called (`agent/client/client.go:792-795`) [V]; an explicit 0 becomes `RunScriptDefaultTimeout`; above `RunScriptMaxTimeout` is refused. pmm-managed always sends one.
- `start_within`: 0 becomes `RunScriptDefaultStartWithin`; negative, or above `RunScriptMaxStartWithin`, is refused.
- `max_output_bytes`: 0 becomes `RunScriptDefaultMaxOutputBytes`; negative, or above `RunScriptMaxOutputBytes`, is refused.
- `keep_files_for`: 0 becomes `RunScriptDefaultKeepFilesFor`; negative, or above `RunScriptMaxKeepFilesFor`, is refused.
- `memory_max`: negative is refused. Whether the host can apply it is the `Manager`'s check (Task 6); the 16 MiB floor is pmm-managed's.

pmm-managed applies the same constants first; pmm-agent checks again and applies the defaults to a zero, so that a run never goes without a limit.

- [ ] **Step 1: Write failing tests.** `TestParseRequestDefaults` (explicit zero values become the constants); `TestParseRequestRefusedEnv` (table: `PATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `PMM_RUN_ID`, `PMM_RUN_X`, `A=B`, an empty name → each refused; `PMM_RUNNER`, `MY_LD_X` → accepted); `TestParseRequestFiles` (`../x`, `a/b`, `out`, `.`, a duplicate name, mode 0644, mode 0200, 1 MiB + 1 byte in total → refused; mode 0400 and two files of 512 KiB → accepted); `TestParseRequestSizes` (a command of 32 KiB and env of 32 KiB + 1 byte → refused; exactly 64 KiB → accepted; stdin 1 MiB + 1 byte → refused); `TestParseRequestLimits` (timeout 7 days + 1 s, `start_within` 24 h + 1 s, `keep_files_for` 24 h + 1 s, `max_output_bytes` 100 MiB + 1, negative values, empty command, a NUL in an argument → refused; each maximum exactly → accepted); `TestParseRequestJobID` (`""`, `..`, `a/b` → refused).
- [ ] **Step 2: Run:** `go test -race -count=1 -run TestParseRequest ./agent/runner/scripts/` → FAIL (package does not exist).
- [ ] **Step 3: Implement** `request.go`.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `PMM-15977 Check run_script requests`.

---

### Task 4: The run directory, the process and the stop

**Files:**
- Create: `agent/runner/scripts/process_linux.go`, `agent/runner/scripts/process_other.go` (`//go:build !linux`)
- Test: `agent/runner/scripts/process_linux_test.go`

**Interfaces:**

```go
// runDirs names a run's directories.
type runDirs struct {
	run string
	out string
}

// prepare creates <base>/<job_id>/ (0700) with out/ (0700) inside, and writes the files into the
// run directory with O_CREAT|O_EXCL|O_NOFOLLOW. base is <TempDir>/run-script/ (0711, traversal
// only), which the Manager creates.
func prepare(base string, req *Request) (*runDirs, error)

// resolveProgram finds command[0]: relative to the run directory when it contains a "/" and is not
// absolute, as given when absolute, otherwise in fixedPath.
func resolveProgram(name, runDir string) (string, error)

// process is one started program.
type process struct { /* cmd, pid, exited, stdin writer, stdout and stderr read ends */ }

func startProcess(req *Request, dirs *runDirs) (*process, error)

// stop sends SIGTERM to the process group, waits up to grace for the program to exit,
// then sends SIGKILL to the group.
func (p *process) stop(grace time.Duration)

// kill sends SIGKILL to the process group at once (shutdown, Task 9).
func (p *process) kill()

// wait returns the exit code (-1 when killed by a signal) and a reason for a signal.
func (p *process) wait() (int32, string)
```

What `startProcess` sets [V, prototype `agent/runner/jobs/run_script_job.go:147-191` on branch `PMM-15696-proto`, unless marked]:
- `cmd.Dir = dirs.run`, where the files are: `command: ["bash", "wrapper.sh"]` finds its file. `out/` is the subdirectory for results. The prototype ran in `out/` (:150) [V]; this is a change.
- `cmd.Env` = `PATH=<fixedPath>`, `HOME=<pmm-agent's HOME>`, `LANG=C.UTF-8`, `PMM_RUN_ID=<job_id>`, `PMM_RUN_DIR=<run dir>`, `PMM_RUN_OUTPUT_DIR=<out dir>`, then the request's `env`. Nothing else of pmm-agent's environment. `fixedPath` is the prototype's `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` (prototype :58). The request may set `HOME` and `LANG`; `os/exec` keeps the last of two equal names [I].
- **stdin** is an `os.Pipe`: the child gets the read end; pmm-agent writes the request's `stdin` from a goroutine of its own and closes the write end when done, or when the run ends. `cmd.Stdin` is never a Go reader, so `Wait` does not wait for a copy that a script that never reads its `stdin` would hold up [I, `os/exec`].
- `SysProcAttr{Setpgid: true, Pdeathsig: SIGKILL}`. `Start` and `Wait` run in one goroutine under `runtime.LockOSThread()`, because Pdeathsig fires when the thread that forked the child exits (prototype :170-182). This pins one OS thread per running script: 16 at most.
- **`oom_score_adj`**: right after `Start`, pmm-agent writes `RunScriptOOMScoreAdj` (1000) to `/proc/<pid>/oom_score_adj`, so that when the host runs out of memory the kernel takes the run before the database or pmm-agent ([spec §6.2](../spec.md#62-what-a-run-is)). Raising the value needs no privilege [I]. Children inherit it; a child forked in the instant between the start and the write keeps pmm-agent's own value [I]. This is the only place it is set, contained or not; plan 03 does not repeat it. A failed write is logged and the run goes on.
- stdout and stderr are `os.Pipe` write ends, closed in pmm-agent after `Start`.
- `resolveProgram` does not use `exec.LookPath`, which searches pmm-agent's own `PATH` [I, stdlib], but walks `fixedPath`.

The end of a run, however it ends:
- On a stop or the time limit: `stop(grace)` with `RunScriptStopGrace` [V, prototype :334-342]. A stop needs no slot.
- After the program has exited and **before it is reaped**: pmm-agent learns of the exit with `waitid(P_PID, pid, WEXITED|WNOWAIT)`, sends SIGKILL to the process group for any member still in it, and only then reaps the leader. While the leader is unreaped its process group id cannot be given to another process [I], so the kill cannot reach a stranger. Plan 03 adds the kill of everything left in the run's control group, or carrying its mark.
- The output readers get 2 s after that; then the read ends are closed (prototype `drainGracePeriod`, :56).
- Everything in the run directory is removed except `out/`: the request's files and anything else the script left there. `out/` is removed at once when empty, otherwise when `keep_files_for` has passed (Task 6 owns the timer).

Outcomes this task produces: `succeeded` (exit 0), `failed` (any other exit, or a signal not sent by pmm-agent: `exit_code -1`, reason `killed by signal <name>`), `stopped`, `timed_out`, and `prepare_failed` when a directory or a file cannot be written, the program does not resolve, `run_as` is set on a root pmm-agent (until plan 03), or `Start` fails.

The time limit runs from the start of the process, not from the request: the wait for a slot is `start_within`'s (Task 6).

`process_other.go` declares `runDirs`, `prepare`, `resolveProgram`, `process`, `startProcess` and the methods, each returning `errors.New("script runs need Linux")`, so that `manager.go` builds everywhere; the `Manager` refuses the run before any of them is called (Task 6).

- [ ] **Step 1: Write failing tests** (real processes, `/bin/sh`):
  - `TestPrepareModes`: the run directory and `out/` are 0700, a file without a mode is written into the run directory with 0600; a second `prepare` with the same id fails.
  - `TestProcessFindsItsFiles`: files `wrapper.sh` and `args.json`, command `["sh", "wrapper.sh"]`; the wrapper reads `args.json` by its plain name, writes `$PMM_RUN_OUTPUT_DIR/r`, and `pwd` prints `$PMM_RUN_DIR` → succeeded; after the end only `out/r` is left.
  - `TestProcessEnvironment`: a script that prints `env` shows exactly the six fixed names plus the request's, and no variable of the test process (set `PMM_TEST_LEAK=1` with `t.Setenv` before).
  - `TestProcessStdin`: `cat` gets the request's `stdin` and then end of file.
  - `TestRunEndsWithUnreadStdin`: 1 MiB of `stdin`, a script that starts `setsid sleep 300 < /dev/stdin &` and exits at once → the run ends within 2 s.
  - `TestOOMScoreAdj`: a script that prints `/proc/self/oom_score_adj` prints 1000, and so does a child it starts.
  - `TestResolveProgram`: `sh` resolves to a file under `fixedPath`; `no-such-program` fails; `./x.sh` resolves against the run directory.
  - `TestStopEscalatesToKill`: a script that traps SIGTERM and sleeps ends by SIGKILL between 5 s and 6 s after `stop(RunScriptStopGrace)`. This is the one test that waits for the real grace period.
  - `TestStopReachesTheGroup`: a script that starts `sleep 300 &` and waits; after `stop` (grace 50 ms) no process with the run's process group id is left.
  - `TestRunEndsWhileGrandchildHoldsPipe`: `setsid sleep 300 &` keeps stdout open; the run ends within 2 s of the script's exit. (The grandchild itself is plan 03's: it left the group.)
  - `TestPdeathsig`: a helper process (re-exec of the test binary with `-test.run=TestHelperProcess`) starts a run and exits with `os.Exit`; the run's process is gone within 2 s.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestPrepare|TestProcess|TestRunEndsWith|TestOOMScoreAdj|TestResolve|TestStop|TestRunEndsWhile|TestPdeathsig' ./agent/runner/scripts/` → FAIL (undefined: `prepare`, `startProcess`).
- [ ] **Step 3: Implement** `process_linux.go` and `process_other.go`.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `PMM-15977 Start and stop run_script processes`.

---

### Task 5: Output, the bounded outbox and batches

**Files:**
- Create: `agent/runner/scripts/output.go`, `agent/runner/scripts/outbox.go`
- Test: `agent/runner/scripts/output_test.go`, `agent/runner/scripts/outbox_test.go`

**Interfaces:**

```go
// outbox holds every message not yet answered, in order, for all runs of the host.
type outbox struct { /* mutex, entries, per-run state and tail buffer, bytes per run, bytes in total, a signal for "not empty" */ }

func newOutbox(runBytes, hostBytes, tailBytes int64) *outbox

// addOutput hands one piece of a run's output to the outbox. While the run is within its bounds
// the piece is queued as a chunk; beyond them it goes to the run's tail buffer (Rules below).
// It never blocks.
func (o *outbox) addOutput(jobID string, stream agentv1.JobProgress_RunScript_Stream, data string)

// addStarted is never dropped and does not count toward the bounds.
func (o *outbox) addStarted(jobID string, at time.Time)

// addResult moves the run's tail buffer into the queue as chunks, then queues the result with
// the run's dropped count. Neither is dropped.
func (o *outbox) addResult(jobID string, r *agentv1.JobResult_RunScript)

// next blocks until there is something to send, then builds a batch of at most maxBytes
// (proto.Size) from the head of the outbox. A run's result is included only when no earlier
// message of that run is still in the outbox. The same entries come back until answered.
func (o *outbox) next(ctx context.Context, maxBytes int) (*agentv1.JobMessagesRequest, error)

// acknowledge removes every entry of batch answered ANSWER_STORED or ANSWER_DISCARDED, and frees
// their bytes. Entries answered ANSWER_UNSPECIFIED, or beyond the end of resp.answers, stay.
// It returns the job ids whose result was answered.
func (o *outbox) acknowledge(batch *agentv1.JobMessagesRequest, resp *agentv1.JobMessagesResponse) []string

// pump reads r in pieces of at most 32 KiB, carries a rune split by a read to the next one,
// replaces invalid UTF-8 and NUL bytes with U+FFFD, and hands each piece to emit.
func pump(r io.Reader, emit func(string))
```

Rules:
- **Chunks:** one per read, at most 32 KiB read [V, prototype :54, :434-466]. `chunk_id` counts up from 0 per run over both streams [V, prototype :385], and is taken only when a chunk is queued, so ids have no gaps.
- **Replacement:** invalid UTF-8 and NUL become U+FFFD ([spec §6.3](../spec.md#63-delivery-of-output-and-results)): PostgreSQL does not store a NUL in a text column [I]. Every byte count below is of the text after replacement, which is what pmm-managed stores, so the two sides count the same bytes. A 32 KiB read can grow to 96 KiB this way (three bytes for each byte replaced); a batch of 256 KiB still holds at least one chunk.
- **The bounds:** a run may hold `RunScriptRunQueueBytes` (4 MiB) of unanswered output, and the host `RunScriptHostQueueBytes` (32 MiB); a run's output in total is capped by its `max_output_bytes`. Each run's last `RunScriptKeptTailBytes` (64 KiB) is reserved inside its 4 MiB and inside its `max_output_bytes`, so neither cap is exceeded.
- **What is dropped, and what is kept ([ADR-04](../adr/ADR-04-acknowledged-delivery.md)):** while a run is within its bounds, its output is queued as it comes; that is the start of its output. Output that finds a bound full goes into the run's tail buffer, which holds the newest 64 KiB; what it pushes out is counted in `dropped_output_bytes`. When answers free room in the queue, the tail buffer is moved into the queue first, then output is queued as it comes again. At the end of the run, `addResult` moves what the tail buffer holds into the queue before the result. So the start of the output and its last 64 KiB always reach pmm-managed, and a failing script's last lines with them. None of this ever blocks the reader: the script never waits for the network.
- **Batches:** the 256 KiB counts `proto.Size` of each entry, envelope included.

- [ ] **Step 1: Write failing tests** (pure, no process; small bounds through `newOutbox`):
  - `TestPumpReplaces`: a 3-byte rune split over two reads arrives whole; `"\xff"` and `"\x00"` each become `"\uFFFD"`, the replacement character.
  - `TestOutboxBoundPerRun`: run bound 96 KiB with a 32 KiB tail: three 32 KiB pieces → two queued, the third in the tail buffer; a fourth pushes the third out (32 KiB counted as dropped); after the first two are answered, the tail is queued next, with the next ids and no gap.
  - `TestOutboxBoundPerHost`: two runs share a host bound; the second's output goes to its tail buffer while the first holds the queue.
  - `TestOutboxKeepsTail`: 200 pieces of 1 KiB with `max_output_bytes` 64 KiB and a 16 KiB tail → what is queued is the first 48 KiB and, after `addResult`, the last 16 KiB, in order; the result's `dropped_output_bytes` is the 136 KiB between them.
  - `TestOutboxResultNeverDropped`: a full outbox still takes `addStarted` and `addResult`.
  - `TestBatchSize`: 20 chunks of 32 KiB → the first batch holds 7 and is at most 256 KiB.
  - `TestBatchHoldsResultUntilChunksAcked`: chunks 0–2 and the result of run A → the first batch holds the chunks only; after they are answered, the next holds the result.
  - `TestBatchKeepsOrderAcrossRuns`: entries of runs A and B interleaved come out in the order they were added.
  - `TestAcknowledgeAnswers`: a batch of 4 answered `[STORED, UNSPECIFIED, DISCARDED]` → entries 1 and 3 stay and are first in the next batch; a discarded result is reported like a stored one.
  - `TestNextBlocksUntilNotEmpty`: `next` returns on `ctx` cancel with `ctx.Err()`, and returns as soon as an entry is added.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestPump|TestOutbox|TestBatch|TestAcknowledge|TestNext' ./agent/runner/scripts/` → FAIL (undefined: `newOutbox`).
- [ ] **Step 3: Implement** `output.go` and `outbox.go`.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `PMM-15977 Queue run_script output with a bound`.

---

### Task 6: The `Manager`: slots, queue, stop, list, directories

**Files:**
- Create: `agent/runner/scripts/manager.go`
- Test: `agent/runner/scripts/manager_linux_test.go`

**Interfaces:**

```go
// Config configures a Manager. A zero value means the default of api/agent/v1/scripts.go.
// Tests set the durations to tens of milliseconds.
type Config struct {
	Capacity        uint16
	Queue           uint16
	TempDir         string
	StopGrace       time.Duration
	DrainGrace      time.Duration
	ShutdownTimeout time.Duration
}

// New removes <TempDir>/run-script/ and everything in it, then creates it again (0711),
// before any run can start.
func New(cfg Config) *Manager

// Run serves the queue until ctx is done, then kills what is left and removes <TempDir>/run-script/.
// It is started once per process, with the process's root context (Task 9).
func (m *Manager) Run(ctx context.Context)

// Start checks the request (Task 3) and queues it. It returns at once. Its error is the refusal.
func (m *Manager) Start(jobID string, timeout *durationpb.Duration, p *agentv1.StartJobRequest_RunScript) error

// Stop reports whether jobID is a run of this Manager. It stops a waiting or running run;
// a delivering run is left alone.
func (m *Manager) Stop(jobID string) bool

// ListRuns returns every run that is waiting, running, or delivering. Host facts are plan 03's.
func (m *Manager) ListRuns() *agentv1.ListRunsResponse

// NextBatch and Acknowledge expose the outbox to the client (Task 8).
func (m *Manager) NextBatch(ctx context.Context) (*agentv1.JobMessagesRequest, error)
func (m *Manager) Acknowledge(batch *agentv1.JobMessagesRequest, resp *agentv1.JobMessagesResponse)
```

The life of a run in the `Manager`:
- **Refused by `Start`**, with nothing kept, in this order: not Linux (`script runs need Linux`); a `Manager` that is shutting down (Task 9); a request `ParseRequest` refuses; a `job_id` the `Manager` already knows, in any phase or with its `out/` still kept (`run <job_id> is already known`), so that nothing starts twice; `run_as` set on a pmm-agent that is not root (`run_as needs a pmm-agent that runs as root`; pmm-managed already decides this from the host facts, and pmm-agent checks again); `memory_max` set on a host that is not contained (`memory_max needs a host where runs are contained`; in this plan no host is contained, plan 03 makes it depend on the host); `Capacity` running and `Queue` waiting already (`pmm-agent already has <n> script runs waiting`). The texts match the roadmap's shared contract.
- **Known** from the moment `Start` accepts it, before the `StartJobResponse` is sent. A start whose answer is lost on the way is therefore in pmm-managed's next `ListRunsRequest` answer and proceeds; a start pmm-agent never received is not, and plan 02 records it `lost`.
- **Waiting** until one of the `Capacity` slots is free, in arrival order. These slots are the `Manager`'s own, not the runner's ([spec §6.2](../spec.md#62-what-a-run-is)). When `start_within` passes first, the run ends `expired`. A stop ends it `stopped`. Neither takes a slot or starts a process.
- **Running** from the slot on: `prepare` and `startProcess` (Task 4), then `addStarted`, the two pumps into `addOutput`, the time limit. `prepare_failed` goes straight to delivering.
- **Delivering** once the process and its readers are done: the slot is freed, `addResult` queues the tail and the result with `finished_at` and the dropped count.
- **Forgotten** when `Acknowledge` reports its result answered, `stored` or `discarded`. A small entry stays until `keep_files_for` passes, with the `out/` removal timer, so that `ReadRunFile` (Task 7) and a repeated `Start` still know the id: a run whose `out/` was empty and removed at once lists no files rather than an error. The timer is in memory; after a restart `New` removes everything.

- [ ] **Step 1: Write failing tests** (real processes, small limits and durations through `Config`):
  - `TestSlotsAndQueue`: capacity 2, queue 3; six runs of `sleep 0.3` → two running, three waiting, the sixth refused with the reason. Separately, 32 runs of `true` with capacity 16 never use the runner (no `runner.Runner` in the test).
  - `TestExpiredWhenNoSlot`: capacity 1, a `sleep 1` run, then a run with `start_within` 100 ms → `OUTCOME_EXPIRED`, `exit_code -1`, no `started_at`, and no process started for it.
  - `TestStopWhileWaiting` → `OUTCOME_STOPPED`, no process started.
  - `TestStopWhileRunning` → `OUTCOME_STOPPED` within the grace period; `TestTimedOut` (timeout 200 ms, `sleep 5`) → `OUTCOME_TIMED_OUT`.
  - `TestOutcomes`: `exit 0` → succeeded, `exit 3` → failed with 3, `kill -9 $$` → failed, -1, reason names SIGKILL; `no-such-program` → prepare_failed; `run_as: "nobody"` → refused with the root reason when the test is not root, prepare_failed when it is.
  - `TestMemoryMaxRefused`: `memory_max` 64 MiB → refused with the reason; nothing written.
  - `TestListRunsPhases`: one waiting, one running, one finished but not answered → `PHASE_WAITING`, `PHASE_RUNNING`, `PHASE_DELIVERING`; after `Acknowledge`, the third is gone.
  - `TestDuplicateStartRefused`: two `Start` calls with one id → the second returns the error; one process (the script appends to a file in `out/`; one line). The same after the first run's result was answered, while its entry is kept.
  - `TestRunDirRemoval`: after the end, the run directory holds only `out/`; with an empty `out/` nothing is left and the listing is empty; with a file and `keep_files_for` 200 ms, `out/` is gone 1 s later.
  - `TestNewRemovesOldRunDirs`: a leftover `<TempDir>/run-script/x/out/f` is gone after `New`.
  - `TestOrder`: progress `started`, then chunks in order, then the result, as `NextBatch` yields them.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestSlots|TestExpired|TestStopWhile|TestTimedOut|TestOutcomes|TestMemoryMax|TestListRuns|TestDuplicate|TestRunDir|TestNewRemoves|TestOrder' ./agent/runner/scripts/` → FAIL (undefined: `New`).
- [ ] **Step 3: Implement** `manager.go`.
- [ ] **Step 4: Run** the same command → PASS. Then `cd agent && make test` → PASS within the 80 s per package.
- [ ] **Step 5: Commit** `PMM-15977 Run scripts in their own slots and queue`.

---

### Task 7: `ReadRunFile`, confined

**Files:**
- Create: `agent/runner/scripts/files_linux.go`, `agent/runner/scripts/files_other.go` (`//go:build !linux`)
- Test: `agent/runner/scripts/files_linux_test.go`

**Interfaces:**

```go
// ReadRunFile lists the regular files of a run's out/, or reads one of them. It never follows a
// symbolic link, and reads nothing but a regular file inside out/ with a link count of 1.
func (m *Manager) ReadRunFile(req *agentv1.ReadRunFileRequest) *agentv1.ReadRunFileResponse
```

- The run must be one the `Manager` knows (running, delivering, or with its entry still kept, Task 6); any other id is an error, `unknown run`. The path is never built from the request alone.
- Every step is opened relative to the one before, with `unix.Openat` and `O_NOFOLLOW|O_CLOEXEC`: `<TempDir>/run-script` (`O_DIRECTORY`), then `<job_id>` (`O_DIRECTORY`), then `out` (`O_DIRECTORY`), then the file (`O_RDONLY|O_NONBLOCK`, so that a FIFO does not block the open). `fstat` on the open file must report a regular file with a link count of 1, so that a hard link to a file elsewhere is refused too; otherwise the file is closed unread. A name is one path component (the rule of Task 3). The rule is the same with and without `run_as` (plan 03).
- The listing uses `unix.Fstatat(..., AT_SYMLINK_NOFOLLOW)` and returns regular files with a link count of 1 only. A known run whose `out/` is gone lists no files.
- A read returns at most `RunScriptMaxReadBytes`; `length` 0 means that much; an `offset` at or past the end returns no data and the size.
- The prototype opens the file with `os.Open`, which follows links (`agent/runner/jobs/run_operation.go:261-307` on `PMM-15696-proto`) [V]; that is the change [spec §6.7](../spec.md#67-the-api) asks for. `os.Root` is not used: it confines to a directory but follows links inside it [I, stdlib].

- [ ] **Step 1: Write failing tests:** `TestReadRunFileConfined` (table, each from a script's own `out/`): a symbolic link to `/etc/hostname`, a link to `../`, a hard link to a file the test made outside the run directory, a FIFO, a sub-directory, a name `..`, a name `a/b` → error; a symbolic link in place of `out/` itself → error; a regular file → its content. `TestReadRunFileList`: a regular file, a symbolic link, a hard link and a directory → only the regular file is listed, with its size. `TestReadRunFileRange`: a 5 MiB file read with `length` 0 → 2 MiB and size 5 MiB; offset 4 MiB → 1 MiB; offset 6 MiB → no data. `TestReadRunFileUnknownRun` → `unknown run`. `TestReadRunFileAfterKeep`: after `keep_files_for` → `unknown run`.
- [ ] **Step 2: Run:** `go test -race -count=1 -run TestReadRunFile ./agent/runner/scripts/` → FAIL (undefined: `ReadRunFile`).
- [ ] **Step 3: Implement** `files_linux.go`; `files_other.go` answers with the error `script runs need Linux`.
- [ ] **Step 4: Run** the same command → PASS.
- [ ] **Step 5: Commit** `PMM-15977 Read run files without following links`.

---

### Task 8: The client: routing and acknowledged delivery

**Files:**
- Create: `agent/client/scripts.go`
- Modify: `agent/client/client.go` (`Client` struct :80-103, `New` :108-131, `runProcessors` :326-334, `processChannelRequests` :568-655, `handleStartJobRequest` :791-909)
- Modify: `agent/commands/run.go` (`client.New` at :75, its only non-test caller; a `Manager` made once before the loop at :65, so that this commit builds)
- Test: `agent/client/scripts_test.go`, `agent/client/client_test.go` (callers of `New`)

**Interfaces:**
- `New(cfg configGetter, supervisor supervisor, r *runner.Runner, s *scripts.Manager, connectionChecker connectionChecker, sv softwareVersioner, sib serviceInfoBroker, cus *connectionuptime.Service, logStore *tailog.Store) *Client`. A nil `*scripts.Manager` is allowed, for the existing tests that build a client without one (`client_test.go:201,320,409`): `processScriptMessages` then returns at once, and the routing refuses `run_script` with `script runs are not available`.
- `func (c *Client) processScriptMessages(ctx context.Context)`, started with the others in `runProcessors` (`start("processScriptMessages", c.processScriptMessages)`). Its loop:
  1. `batch, err := c.scripts.NextBatch(ctx)`; on `ctx` done, return.
  2. `resp, err := channel.SendAndWaitResponse(ctx, batch)` on the connection's channel, captured once as `runProcessors` does for `SendActualStatuses` (:302-304). No timeout of its own: the message is kept until the answer arrives or the connection ends ([spec §6.3](../spec.md#63-delivery-of-output-and-results)).
  3. An `Unimplemented` answer (a pmm-managed replica of an older version, `agent/client/channel/channel.go:434-440`): wait with a growing pause, from `backoffMinDelay` up to `backoffMaxDelay` (`client.go:60-61`), and send again on the same connection.
  4. Any other error, or a nil response: log, wait for `ctx`, return. The batch is still in the outbox and is the first thing the next connection sends. It does not end the connection itself, which would take metrics and Actions down with it.
  5. Otherwise `c.scripts.Acknowledge(batch, resp)`. When some item had no answer, wait before the next batch with the same growing pause, reset by a batch that is answered in full.
- pmm-managed answers `discarded` for an item of a run that has no open record, and sends a stop for that run; also for an item whose store fails for a reason no retry can fix (plan 02). pmm-agent drops a discarded item as it drops a stored one, so a finished run whose record is gone, after a restore of PMM Server, leaves `delivering`, and the stop reaches a run that is still going.
- In `handleStartJobRequest`: `case *agentv1.StartJobRequest_RunScript_: return c.scripts.Start(p.JobId, p.Timeout, j.RunScript)`, before the `default` that answers `unknown job type` (:904-905). The `StartJobResponse` is sent when the run is queued, as for every job today (:601-607) [V].
- `StopJobRequest`: `if !c.scripts.Stop(p.JobId) { c.runner.Stop(p.JobId) }`.
- `ListRunsRequest`: `responsePayload = c.scripts.ListRuns()`. pmm-managed asks on every connect, again until answered, and after any start that got no answer (plan 02); pmm-agent answers each time from memory.
- `ReadRunFileRequest`: answered from a goroutine that sends `c.scripts.ReadRunFile(p)` with the request's id on the captured channel; the loop skips its own `Send` for this case.
- `run.go` (this task): `scr := scripts.New(...)` before the loop, `go scr.Run(rootCtx)`, and `scr` passed to `client.New` in each pass. Task 9 adds the shutdown and `cleanupTmp`.

- [ ] **Step 1: Write failing tests** in `agent/client/scripts_test.go`, with the fake server that `client_test.go` uses (`TestClient` :111):
  - `TestStartJobRoutesRunScript`: a `StartJobRequest{run_script}` is answered with an empty `error`, and the server then receives a `JobMessagesRequest` with `started` and the result.
  - `TestScriptMessagesAcknowledged`: the server answers `ANSWER_STORED` for every item → the result's run leaves `ListRuns`.
  - `TestScriptMessagesDiscarded`: the server answers `ANSWER_DISCARDED` for a result → its run leaves `ListRuns`, and nothing is sent again for it.
  - `TestScriptMessagesRetriedWithoutAnswer`: the server answers with an empty `answers` once → the same messages arrive again at least 1 s later.
  - `TestScriptMessagesUnimplementedBacksOff`: the server answers `Unimplemented` twice → the second send comes at least 1 s after the first, the third at least 2 s after the second.
  - `TestScriptMessagesResentAfterReconnect`: the server receives a batch and closes the stream without answering; on the next connection the first `JobMessagesRequest` holds the same messages.
  - `TestScriptMessagesSurviveNewClient`: a run started through one `Client`; that client's `Run` ends (as on a reload); a second `Client` built with the same `Manager` delivers the run's output and result.
  - `TestStopJobRoutesToScripts`: a stop for a running script ends it `stopped`; a stop for an unknown id reaches the runner.
  - `TestReadRunFileDoesNotBlockRequestLoop`: while a `ReadRunFileRequest` is being answered, a `Ping` and a `ListRunsRequest` are answered.
  - `TestListRunsRequest`: one waiting run → one entry, `PHASE_WAITING`.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestStartJobRoutes|TestScriptMessages|TestStopJobRoutes|TestReadRunFileDoesNot|TestListRunsRequest' ./agent/client/` → FAIL (too many arguments to `New`, undefined: `processScriptMessages`).
- [ ] **Step 3: Implement** `scripts.go`, the routing in `client.go`, and the `run.go` change.
- [ ] **Step 4: Run** the same command → PASS; `go test -race -count=1 ./agent/client/... ./agent/commands/...` → PASS (existing tests unchanged in behavior); `go build ./...`.
- [ ] **Step 5: Commit** `PMM-15977 Deliver run_script messages`.

---

### Task 9: Shutdown, reload and temporary files

**Files:**
- Modify: `agent/commands/run.go` (signal handler :53-60, the loop :65-108, `cleanupTmp` :156-184)
- Modify: `agent/runner/scripts/manager.go` (`Shutdown`)
- Test: `agent/runner/scripts/manager_linux_test.go`, `agent/commands/run_test.go` (new file; the package has only `clients_test.go` and `setup_test.go`)

**Interfaces:**

```go
// Shutdown refuses new runs, ends every waiting run and kills every running run at once (no grace
// period), all with OUTCOME_LOST and the reason "pmm-agent was stopped", and returns when the
// outbox is empty or ctx is done, whichever comes first.
func (m *Manager) Shutdown(ctx context.Context)
```

- **Shutdown.** Today SIGTERM cancels `rootCtx` at once (:59), which ends the stream before any result could be acknowledged. Instead the signal goroutine calls `scr.Shutdown` with a context of `RunScriptShutdownTimeout` (5 s), taken from the moment the signal arrives, and then `rootCancel()`. The connection stays up while `Shutdown` waits.
  - The outcome is `lost`, with the reason: pmm-agent ended the run, nobody asked for it. `stopped` is kept for a stop that somebody asked for ([spec §6.3](../spec.md#63-delivery-of-output-and-results)).
  - Inside the 5 s: the kills, the output readers' last moments (`min(DrainGrace, time left)`, Task 4), and the wait for answers. The whole shutdown fits supervisord's `stopwaitsecs = 10` for PMM Server's own pmm-agent (`managed/services/supervisord/pmm_config.go:188`) [V], and systemd's default stop timeout of 90 s (the unit sets none) [I].
  - What was not answered when `Shutdown` returns is lost all the same; pmm-managed's check on the next connect records those runs as lost ([spec §6.4](../spec.md#64-reconnect-and-lost-runs)).
- **A reload does not end runs.** A reload restarts the loop in the same process (`agent/agentlocal/agent_local.go:183-193`, `run.go:65-108`) [V]; `pmm-admin config` causes one on a running host. The `Manager` lives outside the loop (Task 8), so its runs go on, and the next pass's client sends their output and results. Capacity, queue and `TempDir` are read when pmm-agent starts; a change applies after a restart. Any other end of a pass (the supervisor, the runner or the local server returning, `run.go:83-97`) is the same for the `Manager`.
- **`cleanupTmp`** removes every directory under `TempDir` at the end of each pass (:101, :156-184) [V]. It skips `run-script/`, which the `Manager` owns: `New` empties it at start, `Run` removes it on exit, and in between a reload must leave running runs and kept `out/` directories alone.

- [ ] **Step 1: Write failing tests:**
  - `TestShutdownWithinDeadline`: three running `trap '' TERM; sleep 60` runs and two waiting; `Shutdown` with 5 s while a test goroutine answers every batch → every process is gone at once (no grace period), `Shutdown` returns as soon as the outbox is empty, every run ends `OUTCOME_LOST` with `pmm-agent was stopped`.
  - `TestShutdownWithoutConnection`: the same with nobody answering and `ShutdownTimeout` 300 ms → returns at the deadline, every process gone.
  - `TestShutdownRefusesNewRuns`: `Start` after `Shutdown` → refused.
  - `TestCleanupTmpKeepsRunScript`: `cleanupTmp` removes other directories under `TempDir` and leaves `run-script/` as it was.
  - In `agent/commands/run_test.go`: a helper process (re-exec of the test binary) running `Run()` against an unreachable server, sent SIGTERM with a script run started through its `Manager` → it exits within 6 s, and the run's process is gone. If `Run()` cannot be driven in a test without a server, record that in the PR and rely on Step 5.
- [ ] **Step 2: Run:** `go test -race -count=1 -run 'TestShutdown|TestCleanupTmp' ./agent/runner/scripts/ ./agent/commands/` → FAIL (undefined: `Shutdown`).
- [ ] **Step 3: Implement** `Shutdown` and the `run.go` changes.
- [ ] **Step 4: Run** the same command → PASS; `cd agent && make test` → PASS; `make check` → no new findings.
- [ ] **Step 5: Manual check** on a Linux host with the built `pmm-agent` connected to a PMM Server built from the integration branch with plan 02 merged (if plan 02 is not merged yet, do this check once it is, and record the result in this plan's PR):
  - start 16 runs of `sleep 600` and 40 more, then `systemctl stop pmm-agent` → the unit stops within 6 s (`journalctl -u pmm-agent` shows no `stop-sigterm timed out`), the records read `lost` with `pmm-agent was stopped`, and no `sleep 600` started by the runs is left (`pgrep -f 'sleep 600'`). This is the pmm-agent half of T3; the release run is plan 06's;
  - start 4 runs of `sleep 60`, then reload pmm-agent through its local API (`curl -X POST http://127.0.0.1:7777/local/Reload`, `api/agentlocal/v1/agentlocal.proto:72-74`; 7777 is the default `listen-port`, `agent/config/config.go:239-240`) → the four runs go on and end `succeeded` about a minute later.
- [ ] **Step 6: Commit** `PMM-15977 Stop script runs on shutdown`.

---

### Task 10: The guide for agents

**Files:**
- Modify: `agent/AGENTS.md` (the message lists :24-25, the package table :47-61)

**Interfaces:** none.

- [ ] **Step 1:** Add `ListRuns` and `ReadRunFile` to the server-to-agent list and `JobMessages` to the agent-to-server list; add `runner/scripts` to the package table: script runs with their own slots and queue, acknowledged delivery, not under the runner. Root `AGENTS.md`, "Maintaining This Document", asks for this after a change of the protocol or of the package structure.
- [ ] **Step 2: Commit** `PMM-15977 Describe script runs in agent/AGENTS.md`. Then the plan's second PR: merge `PMM-15976-script-runs` into `PMM-15977-run-script`, run `make prepare-pr`, and open `PMM-15977 Add the run_script job to pmm-agent` into the integration branch.
