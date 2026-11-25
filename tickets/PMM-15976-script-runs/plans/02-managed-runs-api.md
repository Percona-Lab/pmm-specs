# Plan 02: Run records and the API in pmm-managed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, as [00](00-roadmap.md#how-to-execute-these-plans) describes. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pmm-managed keeps one record per run, with its true and final outcome, and serves `scripts.v1beta1.ScriptsService` under `/v1/scripts` to PMM Extensions only. It starts a run once per caller-chosen id, stores what pmm-agent sends before it answers it, asks pmm-agent which runs it knows on every connect and after any start that got no answer, holds stops for hosts that are away, tells a caller of every run's end through one waiting call, lists the hosts that can run scripts, and deletes finished runs after 7 days within a total bound.

**Architecture:** Two packages share the work.
- `managed/services/agents/script_runs.go` (new file) talks to pmm-agent: it sends the start, the stop, `ListRunsRequest` and `ReadRunFileRequest`, and it handles `JobMessagesRequest`. It lives in `agents` because it needs the registry's connections (`Registry.get`, `registry.go:577-585`) [V].
- `managed/services/scripts/` (new package) is the public gRPC server, the check of the second token, pmm-managed's own limits and the cleaner. It calls the `agents` side through a small interface in its `deps.go`, as `managed/services/management/backup/` does with its services [V]. The types the two share live in `managed/models`.
- Three new tables hold everything about a run. No run state lives in a replica's memory; what is kept in memory (a wake-up for a waiting call, the facts a pmm-agent reported on its connection) is a convenience that PostgreSQL or the next connect replaces ([ADR-13](../adr/ADR-13-high-availability.md)).

**Tech Stack:** Go (the version in `go.mod`), protobuf with `google.api.http` and protoc-gen-validate, grpc-gateway v2.33.0 (`go.mod:43`) [V], reform and `lib/pq` on PostgreSQL, testify, go-sqlmock and `testdb`, mockery, the generated swagger clients in api-tests.

**Spec:** [§6.2](../spec.md#62-what-a-run-is), [§6.3](../spec.md#63-delivery-of-output-and-results), [§6.4](../spec.md#64-reconnect-and-lost-runs), [§6.5](../spec.md#65-containment) (the held stop), [§6.6](../spec.md#66-records-and-retention), [§6.7](../spec.md#67-the-api), [§6.8](../spec.md#68-the-host-list), [§9.1](../spec.md#91-who-can-start-a-run), [§9.2](../spec.md#92-high-availability), [§9.3](../spec.md#93-versions); [ADR-03](../adr/ADR-03-at-most-once.md), [ADR-04](../adr/ADR-04-acknowledged-delivery.md), [ADR-05](../adr/ADR-05-run-records-and-retention.md), [ADR-09](../adr/ADR-09-who-may-start-a-run.md), [ADR-10](../adr/ADR-10-api-shape.md), [ADR-12](../adr/ADR-12-host-list.md), [ADR-13](../adr/ADR-13-high-availability.md); contract in [00-roadmap.md](00-roadmap.md#shared-contract). Ticket PMM-15978.

## Global Constraints

**Code base and branches**
- percona/pmm `main` at `122590fc6`; line numbers refer to it. Re-check them before each edit.
- Both branches are cut from the integration branch `PMM-15976-script-runs`, and their PRs target it (00):
  - `PMM-15978-scripts-api`: Task 1 only. Plan 04 starts from this PR's generated clients, so it is opened first and on its own.
  - `PMM-15978-script-runs`: Tasks 2 to 11. It needs plan 01 Task 1 merged into the integration branch. That PR owns everything the new messages need for the tree to build and lint: the protocol, `api/agent/v1/agent.go`, both channels' cases, `api/agent/v1/scripts.go` with the shared limits, and a stub case in `managed/services/agents/handler.go`. This plan fills in the behavior behind them.
- Commit titles `PMM-15978 <summary>`, at most 50 characters in all, signed off (`git commit -s`). Review fixes are new commits (`AGENTS.md`, Git and pull request checklist) [V].
- **Task 4 waits for the security design review** (00). Its Step 1 (the server type, not yet wired) does not, so Tasks 5 to 10 can be written while the review runs. Nothing under `/v1/scripts` is reachable before Task 4 lands, because Task 4 is the only task that registers the service in `main.go`.
- Nothing from the prototype branch is copied unless [spec §7](../spec.md#7-what-the-prototype-is-and-what-changes) lists it as kept. From the pmm-managed side that is the stored stop.

**Commands** (verified in the Makefiles at `122590fc6`)
- Unit tests that use go-sqlmock run on the host: `cd managed && go test -race -p 1 -run <Test> ./<package>/`. `make test` in `managed/` runs `go test -timeout=180s -p 1 -race ./...` (`managed/Makefile:28-30,54-55`) [V].
- Tests that use `testdb.Open` need the devcontainer's PostgreSQL at `127.0.0.1:5432` (`managed/utils/testdb/db.go:51-55`) [V]. Start it with `make env-up` from the repository root, then run inside it: `docker exec --workdir=/root/go/src/github.com/percona/pmm/managed pmm-server go test -race -p 1 -run <Test> ./<package>/`. The container and path are those of `make env` (`Makefile:43-45`); without `-it`, as `make env-pg-config` does (`Makefile:30-31`), so it runs without a terminal [V].
- After a proto, reform model or mocked interface change: `make gen` from the root. Before a PR: `make prepare-pr` (`gen check-all format`, then `go mod tidy`; `Makefile.include:75-76`) [V]. `make check` runs `buf lint`, golangci-lint from `bin/` (installed by `make init`) and `go-sumtype` (`Makefile.include:49-52`) [V].
- api-tests: `cd api-tests && PMM_SERVER_URL=https://<user>:<password>@<host> PMM_SERVER_INSECURE_TLS=1 go test -count=1 -p 1 ./scripts/... -v` (`api-tests/AGENTS.md`, Running Tests) [V]. `make test` there exits 0 when tests fail, so read the output [V].

**Rules this plan relies on**
- Migrations are forward-only, one entry at the end of `databaseSchema`, and carry no column `DEFAULT` (`managed/AGENTS.md`, Database; `database.go:1412`, "Avoid default values in schema definition") [V].
- API errors are `status.Error` with gRPC codes (`AGENTS.md`, PMM-specific choices) [V].
- **Limits** (00, Limits). A value that pmm-agent and pmm-managed both check is defined once, in `api/agent/v1/scripts.go` (plan 01 Task 1), and imported here as `agentv1.RunScript…`. This plan uses `RunScriptMaxFilesBytes`, `RunScriptMaxStdinBytes`, `RunScriptMaxCommandEnvBytes`, `RunScriptDefaultTimeout`, `RunScriptMaxTimeout`, `RunScriptDefaultStartWithin`, `RunScriptMaxStartWithin`, `RunScriptDefaultMaxOutputBytes`, `RunScriptMaxOutputBytes`, `RunScriptDefaultKeepFilesFor`, `RunScriptMaxKeepFilesFor`, `RunScriptMaxReadBytes` and `RunScriptDefaultFileMode`, under the names plan 01 Task 1 gives them; a value this plan needs that plan 01 lacks is added there, not here. pmm-managed's own values are named constants in `managed/services/scripts/limits.go` (the API and the cleaner) and in `managed/services/agents/script_runs.go` (the calls to pmm-agent).
- Every request pmm-managed sends to pmm-agent for script runs (`StartJobRequest`, `StopJobRequest`, `ListRunsRequest`, `ReadRunFileRequest`) has a 10 s deadline, `agentCallTimeout`. No call uses `context.TODO()`.
- The content of `files`, the values of `env`, and `stdin` are never written to PostgreSQL or to a log, and the SHA-256 of a file marked sensitive is not stored either ([spec §6.6](../spec.md#66-records-and-retention)). They exist in pmm-managed only during the `StartRun` call.
- **Code form** (`.golangci.yml`, root `AGENTS.md`, Code Style) [V]: no named results (`nonamedreturns` is off for tests only, `.golangci.yml:119`); a function that returns an interface other than `error` or `any` carries `//nolint:ireturn`, as `channel.go:180` does (`ireturn` allows `anon`, `error`, `empty`, `.golangci.yml:71-75`); comments go above a declaration, not beside it. The sketches below follow that form.
- Every new file under `managed/`, `api/scripts/` and `api-tests/` carries the license header; `make prepare-pr` runs `check-license` (`Makefile.include:54-57`) [V].
- **Why most tests here use `testdb`.** The guarded `UPDATE`, `ON CONFLICT`, the advisory lock, the savepoints and the cascades are PostgreSQL behavior that go-sqlmock cannot show. Root `AGENTS.md` allows `testdb.Open` "when SQL/migration behavior must be verified" [V]. Tests of pure logic and of the gRPC layer use mocks.

**The version gate and branch builds.** A build's version is `<VERSION>-<branch>-<commit>`, where `VERSION` is the file in Percona-Lab/pmm-submodules that the build checks out; only `main` and `pmm-3.*` builds use the bare `VERSION` (`build/scripts/vars:19-26`) [V]. `version.Parsed` orders the part after `X.Y.Z` as a plain string (`version/parsed.go:90-107`) [V], so a gate `X.Y.Z-0` admits every branch build of `X.Y.Z`. So the gate is set in two steps (Task 3):
- while the integration branch builds as another version, `ScriptRunsSupportVersion` is `<that VERSION>-0`, read from the `VERSION` file of the pmm-submodules branch its Feature Builds use;
- before the integration branch merges into `main`, it is `3.12.0-0`, the release that ships plan 01.

On the integration branch the first value also admits a released pmm-agent of that version, which has no `run_script`; it refuses the job, and the run is `not_started` (Task 5). That is acceptable on a branch that does not ship.

## Review Focus

1. **A record in a final state changes, or a state change outside spec §6.2's arrows.** Expected: never. Every change is one guarded `UPDATE … WHERE state = ANY(<allowed sources>)` built from the arrows, and a message that arrives before its start's answer walks the arrows in order. Tests: `TestScriptRunTransitions` (Task 2), `TestJobMessagesBeforeStartAnswer`, `TestJobMessagesLateResult` (Task 6).
2. **A second `StartRun` with the same id.** Expected: the first record comes back and nothing is sent, also when the two calls race. Tests: `TestCreateScriptRunIdempotent` (Task 2), `TestStartRunSameID` (Task 5).
3. **A chunk stored twice, answered `stored` and not stored, or one bad chunk holding up a host.** Expected: `(run_id, chunk_id)` is the key; a transient failure answers nothing; a store that no retry can fix is `discarded` and counted, and the rest of the batch is stored. Tests: `TestJobMessagesDuplicateChunk`, `TestJobMessagesStoreFailsNoAnswer`, `TestJobMessagesPermanentFailure` (Task 6).
4. **An item pmm-managed will not store.** Expected: every item gets `stored` or `discarded`; an item for a run with no open record is `discarded` and that run is stopped; an item for another pmm-agent's run is `discarded`, with no stop and a warning. Tests: `TestJobMessagesNoOpenRecord`, `TestJobMessagesWrongAgent`, `TestJobMessagesOutputCap` (Task 6).
5. **A run marked lost while it waits in pmm-agent's queue, while its result is on the way, or while its start is in flight.** Expected: no. The check judges only records that were `queued` or `running` before the question, and `pending` records past their start deadline, which every `pending` record has from its creation. Tests: `TestCheckQueuedNotLost`, `TestCheckResultInFlight`, `TestCheckStartInFlight` (Task 7).
6. **A list question that gets no answer.** Expected: asked again on the same stream with a growing pause until answered or the stream ends, and asked again after any start that got no answer. Tests: `TestCheckRetriesUntilAnswered`, `TestCheckAfterUnansweredStart` (Task 7).
7. **`ListRuns` with `final_after` skips a run.** Expected: never; every answer carries a cursor, and `from_now` returns the cursor alone. Final transitions take their cursor value under one transaction-level lock, so values become visible in the order they are taken. Tests: `TestScriptRunsFinalSeqOrder` (Task 2), `TestListRunsFinalAfterConcurrent` (Task 8).
8. **The second token.** Expected: 403 without it, with a wrong one, and with one of another length; the comparison is constant-time; the gateway forwards the header. Tests: `TestScriptsToken` (Task 4), `TestScriptsTokenRequired` (Task 11, T12).
9. **No internal token.** Expected: on all three paths where `ResolveExtensions` returns none, an authenticated caller gets exactly what an unknown path gives it, and pmm-managed logs an error. Tests: `TestTokenSource`, `TestScriptsAbsentWithoutToken`, `TestScriptsTokenFromResolveExtensions` (Task 4).
10. **`connected` and `responsive` in HA and under load.** Expected: `connected` is the replica's own registry, the lookup a start uses; `responsive` turns false only after 30 s with nothing received, and not while pmm-managed's own loop holds the receiver. Tests: `TestScriptHostConnected`, `TestResponsive` (Task 9).
11. **A call that waits, on a replica that did not store the result.** Expected: it returns within about a second of the record turning final, because it re-reads PostgreSQL every second. Tests: `TestGetRunWaitRereads`, `TestListRunsWaitRereads` (Task 8).
12. **Stored output.** Expected: one run stores at most its `max_output_bytes`; all runs together at most 1 GiB, enforced by the cleaner from the oldest finished run. Tests: `TestJobMessagesOutputCap` (Task 6), `TestCleanerOutputBound` (Task 10).
13. **Retention runs on the leader only.** Expected: the cleaner is a leader service. Test: `TestScriptRunsCleanerIsLeaderService` (Task 10).
14. **A pmm-agent removed from the inventory.** Expected: its runs are stopped where this replica can still reach it, then marked `lost`; runs of a pmm-agent removed elsewhere are closed by the cleaner. Tests: `TestRemovedAgentStopsThenLoses`, `TestCleanerClosesRunsOfRemovedAgents` (Task 10).

---

### Task 1: The API definition `scripts.v1beta1.ScriptsService`

**Files:**
- Create: `api/scripts/v1beta1/scripts.proto`, `api/scripts/v1beta1/json/header.json` (new files); generated by `make gen`: `scripts.pb.go`, `scripts_grpc.pb.go`, `scripts.pb.gw.go`, `scripts.pb.validate.go`, `json/v1beta1.json`, `json/client/…`
- Modify: `api/Makefile` (the `SPECS` list of `gen` `:9-24`, the `swagger-dev.json` mixin `:66-80`, the `SPECS` list of `clean` `:114-130`), `api/swagger/swagger-dev.json` (regenerated)
- Test: `api/scripts/v1beta1/scripts_test.go` (new file)

**Interfaces:**
- Model: `api/ha/v1/ha.proto` for the layout, `api/accesscontrol/v1beta1/accesscontrol.proto` for a beta package with validation, `api/backup/v1/backup.proto:156-165` and `api/backup/v1/common.proto:47-51` for the log shape, `api/advisors/v1/advisors.proto:273-306` for paging, `api/server/v1/server.proto:6,109` for `(extensions.v1.sensitive)`, `api/inventory/v1/agents.proto:1978` for `string.uuid` [V].
- `header.json`, as `api/accesscontrol/v1beta1/json/header.json` [V], with the title `PMM Scripts API` and version `v1beta1`. The client package is then `api/scripts/v1beta1/json/client/scripts_service` [I: by the pattern of `ha_service` and `access_control_service`].
- **Validation** is in the definition wherever its rules can express a limit: `run_id`, names, file modes, `timeout`, `start_within`, `keep_files_for`, `max_output_bytes`, both `wait`s, the read length. The literals equal the shared constants of `api/agent/v1/scripts.go`; `TestDefinitionMatchesLimits` keeps them equal. Sizes summed over a request and `memory_max`'s floor are checked in code (Task 5).
- The proto. Field comments become the reference in the development OpenAPI document (`api/AGENTS.md`, Do) [V], so every field gets one; most are left out here.

```proto
syntax = "proto3";

package scripts.v1beta1;

import "extensions/v1/redact.proto";
import "google/api/annotations.proto";
import "google/protobuf/duration.proto";
import "google/protobuf/timestamp.proto";
import "protoc-gen-openapiv2/options/annotations.proto";
import "validate/validate.proto";

enum RunState {
  RUN_STATE_UNSPECIFIED = 0;
  RUN_STATE_PENDING = 1;
  RUN_STATE_QUEUED = 2;
  RUN_STATE_RUNNING = 3;
  RUN_STATE_SUCCEEDED = 4;
  RUN_STATE_FAILED = 5;
  RUN_STATE_STOPPED = 6;
  RUN_STATE_TIMED_OUT = 7;
  RUN_STATE_EXPIRED = 8;
  RUN_STATE_PREPARE_FAILED = 9;
  RUN_STATE_NOT_STARTED = 10;
  RUN_STATE_LOST = 11;
}

enum LogStream {
  LOG_STREAM_UNSPECIFIED = 0;
  LOG_STREAM_STDOUT = 1;
  LOG_STREAM_STDERR = 2;
}

message RunFile {
  string name = 1 [(validate.rules).string = {min_len: 1, max_len: 255, not_contains: "/"}];
  // Text. Never stored on PMM Server.
  string content = 2 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
  // Owner bits only: 0400, 0500, 0600 or 0700 (decimal 256, 320, 384, 448). 0 means 0600.
  uint32 mode = 3 [(validate.rules).uint32 = {in: [0, 256, 320, 384, 448]}];
  // When true, the record keeps neither the content nor its SHA-256.
  bool sensitive = 4;
}

message EnvVar {
  string name = 1 [(validate.rules).string = {pattern: "^[A-Za-z_][A-Za-z0-9_]*$"}];
  string value = 2 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
}

// What a record keeps of a file.
message RunFileSummary {
  string name = 1;
  int64 size = 2;
  // Empty for a sensitive file.
  string sha256 = 3;
  uint32 mode = 4;
  bool sensitive = 5;
}

message Run {
  string run_id = 1;
  string pmm_agent_id = 2;
  string node_id = 3;
  string node_name = 4;
  RunState state = 5;
  string reason = 6;
  optional int32 exit_code = 7;
  repeated RunFileSummary files = 8;
  repeated string command = 9;
  repeated string env_names = 10;
  string run_as = 11;
  google.protobuf.Duration timeout = 12;
  google.protobuf.Duration start_within = 13;
  int64 max_output_bytes = 14;
  google.protobuf.Duration keep_files_for = 15;
  int64 memory_max = 16;
  int64 stored_bytes = 17;
  int64 dropped_bytes = 18;
  google.protobuf.Timestamp created_at = 19;
  google.protobuf.Timestamp queued_at = 20;
  google.protobuf.Timestamp started_at = 21;
  google.protobuf.Timestamp finished_at = 22;
  // Whether this replica holds the pmm-agent's stream now. Nothing records since when it does not.
  bool agent_connected = 23;
  // The cleaner removed the stored output to keep the total bound.
  bool output_deleted = 24;
}

message StartRunRequest {
  // Chosen by the caller. A second call with an id that exists returns that record and starts nothing.
  string run_id = 1 [(validate.rules).string.uuid = true];
  string pmm_agent_id = 2 [(validate.rules).string.min_len = 1];
  repeated RunFile files = 3;
  repeated string command = 4 [(validate.rules).repeated = {min_items: 1, items: {string: {min_len: 1}}}];
  repeated EnvVar env = 5;
  string stdin = 6 [(extensions.v1.sensitive) = REDACT_TYPE_FULL];
  string run_as = 7;
  google.protobuf.Duration timeout = 8 [(validate.rules).duration = {lte: {seconds: 604800}, gte: {}}];
  google.protobuf.Duration start_within = 9 [(validate.rules).duration = {lte: {seconds: 86400}, gte: {}}];
  int64 max_output_bytes = 10 [(validate.rules).int64 = {gte: 0, lte: 104857600}];
  google.protobuf.Duration keep_files_for = 11 [(validate.rules).duration = {lte: {seconds: 86400}, gte: {}}];
  // Bytes. 0: no limit. Otherwise at least 16 MiB, and only on a contained host.
  int64 memory_max = 12 [(validate.rules).int64.gte = 0];
}
message StartRunResponse { Run run = 1; }

message GetRunRequest {
  string run_id = 1 [(validate.rules).string.uuid = true];
  google.protobuf.Duration wait = 2 [(validate.rules).duration = {lte: {seconds: 30}, gte: {}}];
}
message GetRunResponse { Run run = 1; }

message ListRunsRequest {
  string pmm_agent_id = 1;
  optional bool final = 2;
  optional int32 page_size = 3 [(validate.rules).int32 = {gte: 1, lte: 1000}];
  optional int32 page_index = 4 [(validate.rules).int32.gte = 0];
  // A cursor from ListRunsResponse.cursor. When set, only runs that reached a final state after it,
  // in that order. "" starts before the oldest kept run.
  optional string final_after = 5;
  // With final_after: when no run is there yet, wait at most this long for one.
  google.protobuf.Duration wait = 6 [(validate.rules).duration = {lte: {seconds: 30}, gte: {}}];
  // Return no runs, only the current cursor.
  bool from_now = 7;
}
message ListRunsResponse {
  repeated Run runs = 1;
  int32 total_items = 2;
  int32 total_pages = 3;
  // Always set: after the last run returned with final_after, otherwise the current one.
  string cursor = 4;
}

message LogChunk {
  uint32 chunk_id = 1;
  LogStream stream = 2;
  string data = 3;
}
message GetRunLogsRequest {
  string run_id = 1 [(validate.rules).string.uuid = true];
  uint32 offset = 2;
  uint32 limit = 3 [(validate.rules).uint32.lte = 1000];
}
message GetRunLogsResponse {
  repeated LogChunk logs = 1;
  // True when the run is final and no chunk is left after the last one returned.
  bool end = 2;
}

message StopRunRequest {
  string run_id = 1 [(validate.rules).string.uuid = true];
}
message StopRunResponse {
  // False: the stop is held until pmm-agent reconnects, or the run was already final.
  bool sent = 1;
  // The record; unchanged when the run was already final.
  Run run = 2;
}

message RunFileInfo {
  string name = 1;
  int64 size = 2;
}
message ListRunFilesRequest {
  string run_id = 1 [(validate.rules).string.uuid = true];
}
// A run that wrote nothing to out/ answers an empty list. A run pmm-agent no longer knows
// (its keep_files_for has passed) answers NotFound.
message ListRunFilesResponse { repeated RunFileInfo files = 1; }

message ReadRunFileRequest {
  string run_id = 1 [(validate.rules).string.uuid = true];
  string name = 2 [(validate.rules).string = {min_len: 1, not_contains: "/"}];
  int64 offset = 3 [(validate.rules).int64.gte = 0];
  int64 length = 4 [(validate.rules).int64 = {gte: 1, lte: 2097152}];
}
message ReadRunFileResponse {
  // Base64 in the gateway's JSON.
  bytes data = 1;
  // True when data reaches the end of the file.
  bool eof = 2;
}

message Host {
  string node_name = 1;
  string node_id = 2;
  string pmm_agent_id = 3;
  string address = 4;
  bool connected = 5;
  bool responsive = 6;
  bool can_run = 7;
  string reason = 8;
  string user = 9;
  bool contained = 10;
  uint32 capacity = 11;
  uint32 queue = 12;
}
message ListHostsRequest {}
message ListHostsResponse { repeated Host hosts = 1; }

service ScriptsService {
  rpc StartRun(StartRunRequest) returns (StartRunResponse) {
    option (google.api.http) = {post: "/v1/scripts/runs" body: "*"};
  }
  rpc GetRun(GetRunRequest) returns (GetRunResponse) {
    option (google.api.http) = {get: "/v1/scripts/runs/{run_id}"};
  }
  rpc ListRuns(ListRunsRequest) returns (ListRunsResponse) {
    option (google.api.http) = {get: "/v1/scripts/runs"};
  }
  rpc GetRunLogs(GetRunLogsRequest) returns (GetRunLogsResponse) {
    option (google.api.http) = {get: "/v1/scripts/runs/{run_id}/logs"};
  }
  rpc StopRun(StopRunRequest) returns (StopRunResponse) {
    option (google.api.http) = {post: "/v1/scripts/runs/{run_id}:stop" body: "*"};
  }
  rpc ListRunFiles(ListRunFilesRequest) returns (ListRunFilesResponse) {
    option (google.api.http) = {get: "/v1/scripts/runs/{run_id}/files"};
  }
  rpc ReadRunFile(ReadRunFileRequest) returns (ReadRunFileResponse) {
    option (google.api.http) = {get: "/v1/scripts/runs/{run_id}/files/{name}"};
  }
  rpc ListHosts(ListHostsRequest) returns (ListHostsResponse) {
    option (google.api.http) = {get: "/v1/scripts/hosts"};
  }
}
```

  Each RPC also gets an `openapiv2_operation` with `summary` and `description`, as `ha.proto` does [V]. The description of every RPC that takes a `run_id` says that an unknown run answers `NotFound` with the text "script run <id> not found", so that a caller can tell it from the gateway's "Endpoint not found: …" of a hidden API (Task 4).
- **The host** is named by `pmm_agent_id` only. A caller that holds a node name finds the id in `ListHosts`.
- **Where the definition is published.** Like `dump/v1beta1` and `accesscontrol/v1beta1`, the package goes into `swagger-dev.json` only, not `swagger.json` (`api/Makefile:46-62` against `:66-80`) [V]. `.github/workflows/api-docs.yml:35-37` uploads only `swagger.json` [V], so no public API reference is published for it. The proto comments are its reference.

- [ ] **Step 1: Write the failing tests** in `scripts_test.go`:
  - `TestStartRunRequestValidation`, table-driven on `(*StartRunRequest).ValidateAll()` (protoc-gen-validate) [I: the generated method name]. Each of these is an error: `run_id` empty or `not-a-uuid`; no `pmm_agent_id`; empty `command`; a `command` item `""`; a file name `a/b`; a file `mode` of `0644`, `0200`, `01600` or `0777`; an env name `1X` or `A-B`; `timeout` 7 days plus 1 s; `start_within` 24 h plus 1 s; `keep_files_for` 24 h plus 1 s; `max_output_bytes` −1 or 100 MiB plus one byte. A request with a UUID, one file `run.sh`, `command: ["/bin/sh", "run.sh"]` passes, with `mode` 0 and with each of `0400`, `0500`, `0600`, `0700`.
  - `GetRunRequest{wait: 31s}` and `ListRunsRequest{wait: 31s}` → error; `30s` → nil. `ReadRunFileRequest{length: 2097153}` → error.
  - `TestDefinitionMatchesLimits`: each boundary above equals its `agentv1.RunScript…` constant: a request one unit past the constant fails, and one at it passes.
- [ ] **Step 2: Run them:** `go test ./api/scripts/v1beta1/` → FAIL: the package does not exist.
- [ ] **Step 3: Write `scripts.proto` and `json/header.json`.** Then, in `api/Makefile`:
  - add `scripts/v1beta1` after `accesscontrol/v1beta1` in both `SPECS` lists;
  - add `scripts/v1beta1/json/v1beta1.json` after `accesscontrol/v1beta1/json/v1beta1.json` in the `swagger-dev.json` mixin.

  Run `go tool buf format api -w` and `go tool buf lint -v api`.
- [ ] **Step 4: Run `make gen`** from the root. It runs `buf breaking --against descriptor.bin` first (`api/Makefile:6`) [V], and CI runs `make gen`; the check passes because the package is new. Check that `api/scripts/v1beta1/json/client/scripts_service/` exists, and that `api/swagger/swagger.json` has no `/v1/scripts` path.
- [ ] **Step 5: Run the tests again:** `go test ./api/scripts/v1beta1/` → PASS.
- [ ] **Step 6: Run `make prepare-pr`.** Commit `PMM-15978 Add the scripts v1beta1 API definition`, push, open the PR into `PMM-15976-script-runs`, and tell plan 04 its number.

---

### Task 2: Tables, models and helpers

**Files:**
- Modify: `managed/models/database.go` (one entry at the end of `databaseSchema`, after `129:` at `:1379-1410`)
- Create: `managed/models/script_run_model.go`, `managed/models/script_run_helpers.go` (new files); `managed/models/script_run_model_reform.go` (generated)
- Test: `managed/models/script_run_helpers_test.go` (new file), `managed/models/database_test.go` (`TestDatabaseMigrations` `:390`)

**Interfaces:**
- **The migration number.** The highest entry at `122590fc6` is `129` (`database.go:1379`) [V], so the entry is `130` if nothing lands before. Choose it when the commit is made:
  - open `database.go` on the integration branch after merging `main`, and take the highest key plus one;
  - do the same again after every merge of `main` that adds one. Entries 121 to 129 landed in the six weeks before `122590fc6` (`git log 016153c7a..122590fc6 -- managed/models/database.go`) [V].

  `migrateDB` runs every pending entry in one transaction (`database.go:1723`) [V], and a duplicate key does not compile, so a clash shows at once.
- **Sizing** (ADR-05, ADR-11): one run a second for 7 days is 604,800 rows in `script_runs` [I: the rate is ADR-11's]. At about 1 KiB a row with its request summary, that is about 600 MiB of rows and well under 100 MiB for each of the indexes below [I: estimated, not measured]. Every query of this plan reads by an index: the key, the open runs of one pmm-agent (a partial index), `final_seq`, `finished_at`, and `created_at` for the plain list. Output is bounded apart, at 1 GiB in all (Task 10). Task 10's retention pass deletes about 600 runs every 10 minutes at that rate.
- DDL. `TIMESTAMP` without time zone and `VARCHAR`, as entry 129 [V]. No `DEFAULT`. `node_id` and `node_name` are copied in, and `pmm_agent_id` has no foreign key, so a record outlives its node and its pmm-agent, as `jobs.pmm_agent_id` does (`database.go:521-534`) [V].

```sql
CREATE TABLE script_runs (
  id VARCHAR NOT NULL,
  pmm_agent_id VARCHAR NOT NULL CHECK (pmm_agent_id <> ''),
  node_id VARCHAR NOT NULL,
  node_name VARCHAR NOT NULL,
  state VARCHAR NOT NULL,
  reason VARCHAR NOT NULL,
  exit_code INTEGER,
  request JSONB NOT NULL,
  stored_bytes BIGINT NOT NULL,
  dropped_bytes BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  start_deadline TIMESTAMP NOT NULL,
  queued_at TIMESTAMP,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  final_seq BIGINT,
  output_deleted_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL,
  PRIMARY KEY (id)
);
CREATE INDEX script_runs_open_idx ON script_runs (pmm_agent_id) WHERE state IN ('pending', 'queued', 'running');
CREATE INDEX script_runs_created_at_idx ON script_runs (created_at);
CREATE INDEX script_runs_finished_at_idx ON script_runs (finished_at);
CREATE UNIQUE INDEX script_runs_final_seq_idx ON script_runs (final_seq);
CREATE SEQUENCE script_runs_final_seq;

CREATE TABLE script_run_logs (
  run_id VARCHAR NOT NULL REFERENCES script_runs (id) ON DELETE CASCADE,
  chunk_id INTEGER NOT NULL,
  stream SMALLINT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (run_id, chunk_id)
);

CREATE TABLE script_stop_requests (
  run_id VARCHAR NOT NULL REFERENCES script_runs (id) ON DELETE CASCADE,
  pmm_agent_id VARCHAR NOT NULL,
  requested_at TIMESTAMP NOT NULL,
  PRIMARY KEY (run_id)
);
```

- `script_run_model.go`, with `//go:generate go tool reform` as `advisor_run_model.go` [V]. It also holds the types `scripts` and `agents` share (Task 4, package boundaries):

```go
type ScriptRunState string

const (
	ScriptRunPending       ScriptRunState = "pending"
	ScriptRunQueued        ScriptRunState = "queued"
	ScriptRunRunning       ScriptRunState = "running"
	ScriptRunSucceeded     ScriptRunState = "succeeded"
	ScriptRunFailed        ScriptRunState = "failed"
	ScriptRunStopped       ScriptRunState = "stopped"
	ScriptRunTimedOut      ScriptRunState = "timed_out"
	ScriptRunExpired       ScriptRunState = "expired"
	ScriptRunPrepareFailed ScriptRunState = "prepare_failed"
	ScriptRunNotStarted    ScriptRunState = "not_started"
	ScriptRunLost          ScriptRunState = "lost"
)

// Final reports whether no change may follow s.
func (s ScriptRunState) Final() bool

// ScriptRunFile is what a record keeps of one file. SHA256 is empty for a sensitive file.
type ScriptRunFile struct {
	Name      string      `json:"name"`
	Size      int64       `json:"size"`
	SHA256    string      `json:"sha256"`
	Mode      os.FileMode `json:"mode"`
	Sensitive bool        `json:"sensitive"`
}

// ScriptRunRequest is the request without its secrets.
type ScriptRunRequest struct {
	Files          []ScriptRunFile `json:"files"`
	Command        []string        `json:"command"`
	EnvNames       []string        `json:"env_names"`
	RunAs          string          `json:"run_as"`
	Timeout        time.Duration   `json:"timeout"`
	StartWithin    time.Duration   `json:"start_within"`
	MaxOutputBytes int64           `json:"max_output_bytes"`
	KeepFilesFor   time.Duration   `json:"keep_files_for"`
	MemoryMax      int64           `json:"memory_max"`
}

// ScriptRun has one field per column. Request is a *ScriptRunRequest with Value and Scan, as the JSON columns of job_models.go are.
//
//reform:script_runs
type ScriptRun struct { … }

//reform:script_run_logs
type ScriptRunLog struct { RunID string; ChunkID uint32; Stream int16; Data string }

//reform:script_stop_requests
type ScriptStopRequest struct { RunID, PMMAgentID string; RequestedAt time.Time }
```

- `script_run_helpers.go`. Every function takes `ctx` and a `*reform.Querier`, as `advisor_run_helpers.go` does [V]:

```go
// CreateScriptRun inserts run unless its id exists, and returns the stored row and whether it was new.
func CreateScriptRun(ctx context.Context, q *reform.Querier, run *ScriptRun) (*ScriptRun, bool, error)
// FindScriptRunByID returns codes.NotFound "script run <id> not found" when there is no row.
func FindScriptRunByID(ctx context.Context, q *reform.Querier, id string) (*ScriptRun, error)
func FindScriptRuns(ctx context.Context, q *reform.Querier, f ScriptRunFilters, pageIndex, pageSize int) ([]*ScriptRun, int, error)
// FindScriptRunsFinalAfter returns runs whose final_seq is above finalAfter, by final_seq, at most limit.
func FindScriptRunsFinalAfter(ctx context.Context, q *reform.Querier, pmmAgentID string, finalAfter int64, limit int) ([]*ScriptRun, error)
// CurrentScriptRunsCursor returns the highest visible final_seq, or 0.
func CurrentScriptRunsCursor(ctx context.Context, q *reform.Querier) (int64, error)
// FindScriptRunsToCheck returns the records the check may judge (Task 7).
func FindScriptRunsToCheck(ctx context.Context, q *reform.Querier, pmmAgentID string, asked time.Time) ([]*ScriptRun, error)
func FindOpenScriptRuns(ctx context.Context, q *reform.Querier, pmmAgentID string) ([]*ScriptRun, error)

// TransitionScriptRun moves a run to `to` along one arrow of spec §6.2, and reports whether it did.
// It must run in a transaction: a final transition takes scriptRunsFinalLockID first.
func TransitionScriptRun(ctx context.Context, q *reform.Querier, id string, to ScriptRunState, ch ScriptRunChange) (bool, error)

// AddScriptRunLogs stores the chunks of one run within its max_output_bytes, and returns the bytes stored and refused.
func AddScriptRunLogs(ctx context.Context, q *reform.Querier, run *ScriptRun, logs []*ScriptRunLog) (int64, int64, error)
func FindScriptRunLogs(ctx context.Context, q *reform.Querier, runID string, offset, limit uint32) ([]*ScriptRunLog, error)

// HoldScriptStop stores a stop; holding one twice is not an error.
func HoldScriptStop(ctx context.Context, q *reform.Querier, runID, pmmAgentID string) error
func FindScriptStop(ctx context.Context, q *reform.Querier, runID string) (*ScriptStopRequest, error)
func DeleteOldScriptRuns(ctx context.Context, q *reform.Querier, finishedBefore time.Time) (int, error)
// DeleteOldestScriptRunOutput deletes the logs of the oldest finished runs until the stored total is at most limit.
func DeleteOldestScriptRunOutput(ctx context.Context, q *reform.Querier, limit int64) (int, error)
// FindScriptRunsOfRemovedAgents returns open runs whose pmm-agent row no longer exists.
func FindScriptRunsOfRemovedAgents(ctx context.Context, q *reform.Querier) ([]*ScriptRun, error)
```

  - **`CreateScriptRun`** inserts with `INSERT … ON CONFLICT (id) DO NOTHING`, then reads the row, so two concurrent starts with one id get the same record and only one gets `true`.
  - **`ScriptRunChange`** carries the optional columns a change sets: `Reason`, `ExitCode`, `DroppedBytes` (added to the stored count), `QueuedAt`, `StartedAt`, `FinishedAt`. `updated_at` is always set; `finished_at` is set to `Now()` when `to` is final and none is given.
  - **The arrows**, exactly those of [spec §6.2](../spec.md#62-what-a-run-is):
    - from `pending`: `queued`, `not_started`, `lost`;
    - from `queued`: `running`, `expired`, `stopped`, `prepare_failed`, `lost`;
    - from `running`: `succeeded`, `failed`, `stopped`, `timed_out`, `lost`.

    No other pair is allowed, and no final state is a source. A caller that must reach a state further down (a progress or a result handled before the start's answer, Task 6) calls it once per arrow.
  - **The cursor of `ListRuns`.** A final transition takes `pg_advisory_xact_lock(scriptRunsFinalLockID)` and then sets `final_seq = nextval('script_runs_final_seq')` in its `UPDATE`. The lock is held to the commit, so the values become visible in the order they are taken, on every replica, and a reader that has seen value N never later finds a smaller one appear. The precedent is `encryptionKeyLockID` (`managed/models/encryption_helpers.go:37-39,153`) [V]; `scriptRunsFinalLockID` is a new constant with another value. Final transitions are rare next to log writes, so the lock is not a bottleneck [I].
  - **`CurrentScriptRunsCursor`** is `SELECT max(final_seq)`: by the lock above, every value below it is already visible.
  - **`FindScriptRunsToCheck`** ([spec §6.4](../spec.md#64-reconnect-and-lost-runs) step 3): the pmm-agent's records in `queued` or `running` whose `queued_at` is before `asked`, and those in `pending` whose `start_deadline` is before `asked`. A start still in flight is never returned. A move from `pending` straight to `running` cannot happen (the arrows), so every `running` record has a `queued_at`.
  - **A final transition deletes the run's `script_stop_requests` row** in the same transaction.
  - **`AddScriptRunLogs`** inserts with `INSERT … ON CONFLICT (run_id, chunk_id) DO NOTHING`, counts the bytes of `data` it inserted (the text as received, after pmm-agent's replacement of invalid bytes), refuses a chunk that would take `stored_bytes` above `request.max_output_bytes`, and updates both counters.
  - **`DeleteOldestScriptRunOutput`**: while `sum(stored_bytes)` is above `limit`, delete the logs of the final run with the oldest `finished_at` that still has output, set its `stored_bytes` to 0 and its `output_deleted_at`.

- [ ] **Step 1: Write the failing migration test** in `TestDatabaseMigrations`: open `testdb` at the previous version (`testdb.Open(t, models.SkipFixtures, new(<N-1>))`, then `testdb.SetupDB(t, sqlDB, models.SkipFixtures, new(<N>))`, as the existing cases do, `database_test.go:390-430`) [V]; the three tables and the sequence exist; a `script_run_logs` row without its run fails with a foreign-key error; deleting the run deletes its logs and its stop row.
- [ ] **Step 2: Write the failing helper tests** in `script_run_helpers_test.go` on `testdb.Open(t, models.SkipFixtures, nil)`:
  - `TestCreateScriptRunIdempotent`: a second insert with the same id returns the first row and `false`; ten goroutines with one id → one `true`.
  - `TestScriptRunTransitions`: table over every pair of states. Exactly the arrows above succeed; every other pair returns `false` and leaves the row as it was; from every final state every target returns `false`. A transition to a final state sets `finished_at` and `final_seq` and deletes the stop row.
  - `TestFindScriptRunsFinalAfter`: three runs turned final in order → returned in that order from cursor 0; from the second's `final_seq`, only the third; open runs never.
  - `TestScriptRunsFinalSeqOrder`: two transactions turn two runs final; the first holds its transaction open → the second's `final_seq` is not visible until the first commits, and the first's value is the smaller. `CurrentScriptRunsCursor` meanwhile reads the value before both.
  - `TestAddScriptRunLogs`: chunks 0, 1, 2 stored; chunk 1 again → counted as neither stored nor refused, data unchanged; with `max_output_bytes` 10 and chunks of 6 bytes → the second refused, `dropped_bytes` 6.
  - `TestFindScriptRunLogs`: `offset` and `limit` by `chunk_id`, ordered by it.
  - `TestFindScriptRunsToCheck`: only that pmm-agent's rows; `queued` and `running` with `queued_at` before `asked`; `pending` only with `start_deadline` before `asked`.
  - `TestDeleteOldScriptRuns`: deletes final runs finished before the cut, with their logs; keeps open runs whatever their age.
  - `TestDeleteOldestScriptRunOutput`: three final runs of 600, 600 and 600 bytes and a limit of 1,000 → the two oldest lose their logs and read `stored_bytes` 0 with `output_deleted_at`; an open run is never touched.
  - `TestFindScriptRunsOfRemovedAgents`: an open run whose pmm-agent row was deleted is returned; one whose row exists is not.
- [ ] **Step 3: Run them** in the devcontainer: `… go test -race -p 1 -run 'TestDatabaseMigrations|TestCreateScriptRun|TestScriptRun|TestFindScriptRun|TestAddScriptRunLogs|TestDeleteOld' ./models/` → FAIL: undefined names, then missing tables.
- [ ] **Step 4: Implement** the migration entry, the model and the helpers. Run `make gen` for `script_run_model_reform.go`.
- [ ] **Step 5: Run the tests again** → PASS. Run the whole `./models/` package in the devcontainer: no other migration test changes.
- [ ] **Step 6: Commit** `PMM-15978 Add the script run tables and helpers`.

---

### Task 3: The version gate

**Files:**
- Modify: `version/features.go` (the `var` block `:21-32`)
- Test: `version/features_test.go` (new file)

**Interfaces:**
- `ScriptRunsSupportVersion FeatureVersion = MustParse("<V>-0")`, beside `NomadAgentSupportVersion` (`features.go:26`) [V], with a comment above it naming the feature and saying where `<V>` comes from. `IsFeatureSupported` (`features.go:35-37`) [V] is unchanged.
- `<V>` (Global Constraints, the version gate):
  - **on the integration branch**: the version its builds have, which is the `VERSION` file of the Percona-Lab/pmm-submodules branch that its Feature Builds use (`build/scripts/vars:19-20`) [V]. Read the file there when this task starts, and again whenever that branch's `VERSION` changes;
  - **before the merge into `main`**: `3.12.0`, the release that ships plan 01 (00).
- `version.Parsed.Less` compares the part after `X.Y.Z` as a string (`version/parsed.go:90-107`) [V]: `-0` sorts below `-PMM-…`, `-rc1` and the empty string, so `<V>-0` admits every build of `<V>`.

- [ ] **Step 1: Write the failing test** `TestScriptRunsSupportVersion`, written against the constant's own `Major`, `Minor` and `Patch` so it holds for both values of `<V>`: the version one minor below, and its `.99` patch → false; `<V>-0`, `<V>-PMM-15976-script-runs-abc1234` (a branch build), `<V>-rc1`, `<V>`, and one minor above → true.
- [ ] **Step 2: Run** `go test ./version/ -run TestScriptRunsSupportVersion` → FAIL: undefined.
- [ ] **Step 3: Add the constant** with the integration branch's `<V>`. Run again → PASS.
- [ ] **Step 4: Commit** `PMM-15978 Add the script runs version gate`.
- [ ] **Step 5: Before the integration branch merges into `main`** (after plan 06's gate), set `<V>` to `3.12.0`, run the test, and commit `PMM-15978 Gate script runs on 3.12.0`.

---

### Task 4: Who may call

> This task waits for the security design review (00). Step 1 does not.

**Files:**
- Create: `managed/services/scripts/scripts.go`, `managed/services/scripts/token.go`, `managed/services/scripts/deps.go`, `managed/services/scripts/limits.go` (new files)
- Modify:
  - `managed/services/grafana/auth_server.go` (`rules`, `:54-149`: two entries);
  - `managed/cmd/pmm-managed/main.go` (`gRPCServerDeps` `:218-252`; the unary and stream chains `:285-294`; the server registrations near `:355`; `runHTTP1Server`'s `NewServeMux` `:415-419`, registrar list `:441-473` and `mux.Handle("/", proxyMux)` `:478`; the existing `ResolveExtensions` call `:1162`);
  - `.mockery.yaml` (a `github.com/percona/pmm/managed/services/scripts` entry).
- Test: `managed/services/scripts/token_test.go`, `managed/services/scripts/gateway_test.go` (new files), `managed/services/grafana/auth_server_test.go` (`TestResolveRule` `:192`), `managed/cmd/pmm-managed/main_test.go` (`TestImports` `:81`; `TestScriptsTokenFromResolveExtensions`, new)

**Interfaces:**
- **Auth rules** (00): `"/v1/scripts": admin` beside `"/v1/backups": admin` (`auth_server.go:95`) [V], and `"/scripts.v1beta1.": admin` with the gRPC entries. nginx passes gRPC only for `/agent.`, `/inventory.`, `/management.`, `/server.` and `/realtimeanalytics.` (`pmm.conf:324-344`) [V], so the gRPC name is not reachable through it; its rule is a safeguard.
- **The second token** (00, ADR-09). In `token.go`:

```go
const (
	ScriptsTokenHeader = "X-PMM-Scripts-Token"
	scriptsTokenLabel  = "pmm-managed-scripts-token"
)

// TokenSource gives the expected token: HMAC-SHA256, hex, keyed with the internal token pmm-managed
// shares with PMM Extensions, over scriptsTokenLabel.
type TokenSource struct { resolve func() (string, string); mu sync.Mutex; token []byte; l *logrus.Entry }

// NewTokenSource returns nil when resolve gives no URL or no internal token at start-up.
func NewTokenSource(resolve func() (string, string), l *logrus.Entry) *TokenSource

// Token returns the expected token.
func (s *TokenSource) Token() ([]byte, error)

// check answers codes.PermissionDenied unless the header carries the expected token.
func (s *TokenSource) check(ctx context.Context) error

// ScriptsToken returns hex(HMAC-SHA256(key: internalToken, message: scriptsTokenLabel)).
func ScriptsToken(internalToken string) string

func UnaryTokenInterceptor(s *TokenSource) grpc.UnaryServerInterceptor
func StreamTokenInterceptor(s *TokenSource) grpc.StreamServerInterceptor
func IncomingHeaderMatcher(key string) (string, bool)
```

  - **The key** is the internal token pmm-managed and PMM Extensions already share: exactly what `om.ResolveExtensions` returns (`managed/services/om/extensions_connection.go:42-67`) [V], from the flags `--extensions-url` [`PMM_EXTENSIONS_URL`] and `--extensions-token` [`PMM_EXTENSIONS_TOKEN`] (`main.go:743-746`) [V]. One rule covers the side-car and a PMM Extensions that runs elsewhere:
    - the side-car (`env.ExtensionsEnabled()`, no URL): the token derived from its `SECRET_KEY`, unless `PMM_EXTENSIONS_TOKEN` is set (`:56-58`) [V];
    - elsewhere (URL set): `PMM_EXTENSIONS_TOKEN` as given (`:43-49`) [V].

    The message is the label `pmm-managed-scripts-token` in every case. `ResolveExtensions` does not change. `scripts` may not import `om` (package boundaries, below), so `main.go` passes `resolve` as a closure over `om.ResolveExtensions(*extensionsURLF, *extensionsTokenF, …)`.
  - **No internal token: the API is off.** `ResolveExtensions` gives no usable token on three paths: PMM Extensions not enabled, where it returns no URL (`:51-52`); its `SECRET_KEY` unreadable (`:61-64`); and a URL with no `PMM_EXTENSIONS_TOKEN` (`:43-49`) [V]. On all three, `NewTokenSource` returns nil, pmm-managed logs an error at start-up naming the path, and the service is not registered on gRPC or on the gateway. An empty token never becomes a key.
  - **HA and an external PostgreSQL.** There the side-car's secret file is not published (`build/ansible/roles/extensions/files/extensions-secrets:146-149`) [V], and the internal token comes from `PMM_EXTENSIONS_TOKEN`, set to the same value on every replica (ADR-09, ADR-13).
  - **Rotation.** The token is derived at start-up on both sides. A change of the secret needs a restart of pmm-managed and of PMM Extensions; until both have restarted, calls get 403. Task 11 Step 5 puts this in `managed/AGENTS.md`.
  - `check` reads the header from incoming metadata and compares its value, as the hex text it is sent in, with `crypto/subtle.ConstantTimeCompare`. A missing, empty or different value is `codes.PermissionDenied` (HTTP 403 through `runtime.HTTPStatusFromCode`, `utils/errors/errors.go:100`) [V]. The message names neither the expected value nor its length.
  - **The gateway drops the header today.** `runHTTP1Server` builds its mux without `WithIncomingHeaderMatcher` (`main.go:415-419`) [V], and grpc-gateway's default forwards only its list of permanent headers and `Grpc-Metadata-*` (`runtime/mux.go:156-164`, `runtime/context.go:334-360` in v2.30.0) [V for v2.30.0, I for the pinned v2.33.0]. `IncomingHeaderMatcher` maps `X-Pmm-Scripts-Token` to metadata `x-pmm-scripts-token` and defers to `runtime.DefaultHeaderMatcher` for every other key, so no other header changes. It is passed to `NewServeMux` in every case.
  - The interceptors act on methods under `/scripts.v1beta1.` only. They go into both chains in `runGRPCServer` after `interceptors.UnaryAdd`/`Stream` and before `UnaryServiceEnabledInterceptor`, so a call without the token gets 403 before any validation detail.
- **"As if it did not exist"** ([spec §9.1](../spec.md#91-who-can-start-a-run) rule 3). The rule is about what an authenticated caller gets: nginx's `auth_request` answers first, and a path with no rule needs the Grafana server admin (`auth_server.go:615-620`) [V]. For a caller that passes `auth_request` on both paths, an unknown path gets HTTP 404, `codes.NotFound`, "Endpoint not found: <path>, http method: <method>" from `PMMRoutingErrorHandler` (`utils/errors/errors.go:147-161`) [V]; with no internal token, `/v1/scripts/…` reaches no handler and gets the same answer.
- **The server type** (`scripts.go`), modeled on `HAServer` (`managed/services/ha/ha.go:25-37`) [V]:

```go
type Server struct {
	scriptsv1beta1.UnimplementedScriptsServiceServer

	db   *reform.DB
	runs scriptRuns
	l    *logrus.Entry
}

func NewServer(db *reform.DB, runs scriptRuns) *Server
```

  `runs` is the interface in `deps.go`, implemented by `*agents.ScriptRunsService`. Until Tasks 5 to 9 fill them, every RPC answers `codes.Unimplemented` from the embedded type.
- **Package boundaries.** `TestImports` (`main_test.go:81-140`) keeps service packages from importing each other [V]. `managed/services/scripts` joins its list with `blacklistPrefixes: ["github.com/percona/pmm/managed/services/"]`, as `management` has. So `scripts` never imports `agents` or `om`: the types the two share (`StartScriptRunParams`, `ScriptFile`, `ScriptHost`, `ScriptRunFileInfo`) are in `managed/models/script_run_model.go`, and `scripts/deps.go` names only `models`, `api` and standard types.
- **pmm-managed's own limits** (`limits.go`); the shared ones come from `agentv1` (Global Constraints):

```go
const (
	minMemoryMax         = 16 << 20
	maxWait              = 30 * time.Second
	defaultListPageSize  = 100
	runRetention         = 7 * 24 * time.Hour
	retentionInterval    = 10 * time.Minute
	maxStoredOutputBytes = 1 << 30
)
```

- [ ] **Step 1: Create the package** with `Server`, `NewServer`, an empty `scriptRuns` interface in `deps.go`, and `limits.go`. Add the package to `TestImports`. `go build ./managed/...` and `cd managed && go test -run TestImports ./cmd/pmm-managed/` pass. This step does not wait for the review.
- [ ] **Step 2: Write the failing tests:**
  - `TestResolveRule` gains `GET /v1/scripts/hosts`, `POST /v1/scripts/runs`, `POST /v1/scripts/runs/r1:stop`, `GET /v1/scripts/runs/r1/files/out.txt` and `POST /scripts.v1beta1.ScriptsService/StartRun` → `admin`.
  - `TestScriptsToken` (`token_test.go`), with a `resolve` stub returning `("http://x", "it1")`: the header `ScriptsToken("it1")` → the handler runs. No header, an empty one, one byte changed, a prefix of the right value, `it1` itself, and a token derived from `it1` under another label → `PermissionDenied`, and the handler does not run. A method outside `/scripts.v1beta1.` without a token → the handler runs.
  - `TestScriptsTokenValue`: `ScriptsToken` of a fixed internal token equals a fixed hex value computed in the test with `crypto/hmac`, so plan 04 can copy the vector.
  - `TestTokenSource`: `resolve` returning `("", "")`, `("", "t1")`, `("http://x", "")` and `("http://pmm-extensions:9000", "")` → nil, and one error logged each; `("http://x", "it1")` → the token is `ScriptsToken("it1")`.
  - `TestIncomingHeaderMatcher`: `X-PMM-Scripts-Token` in any case → `x-pmm-scripts-token, true`; `Authorization` → as `runtime.DefaultHeaderMatcher`; `X-Other` → `"", false`.
  - `TestScriptsAbsentWithoutToken` (`gateway_test.go`): a gateway mux built as `runHTTP1Server` builds it, without the scripts handler registered; `GET /v1/scripts/hosts` and `POST /v1/scripts/runs` give the same status and body as `GET /v1/nosuchapi` and `POST /v1/nosuchapi`; `GET /v1/ha/status` is unaffected.
  - `TestScriptsTokenThroughGateway` (`gateway_test.go`): an in-process gRPC server with the interceptor and the gateway with the matcher; `GET /v1/scripts/hosts` with the header reaches the server (`Unimplemented` until Task 9), without it → 403.
  - `TestScriptsTokenFromResolveExtensions` (`main_test.go`, `t.Setenv`, so not parallel): `PMM_ENABLE_EXTENSIONS=1`, `PMM_DEV_EXTENSIONS_SECRETS_DIR` at a `t.TempDir()` holding a `SECRET_KEY`, and `resolve` bound as `main.go` binds it → `Token()` equals the value the test computes itself: the scripts token of the internal token that `ResolveExtensions` returns for that `SECRET_KEY`. `PMM_ENABLE_EXTENSIONS` unset → `NewTokenSource` is nil.
- [ ] **Step 3: Run** `cd managed && go test -race -p 1 -run 'TestResolveRule|TestNextPrefix' ./services/grafana/` and `go test -race -p 1 ./services/scripts/ ./cmd/pmm-managed/` → FAIL. Other tests of `services/grafana` need a live Grafana; run only these two there.
- [ ] **Step 4: Implement** the rules, `TokenSource`, `ScriptsToken`, the interceptors and the matcher. Then wire `main.go`:
  - next to the `ResolveExtensions` call (`:1162`), `scripts.NewTokenSource(func() (string, string) { return om.ResolveExtensions(*extensionsURLF, *extensionsTokenF, …) }, …)`;
  - when the source is not nil: a `scriptsServer *scripts.Server` in `gRPCServerDeps`, `scriptsv1beta1.RegisterScriptsServiceServer` beside `hav1.RegisterHAServiceServer` (`:355`), and `scriptsv1beta1.RegisterScriptsServiceHandler` in the registrar list (`:441-473`);
  - in every case: the interceptors in both chains (they let every other method through), and `IncomingHeaderMatcher` passed to `NewServeMux`;
  - the mockery entry for `scriptRuns`.
- [ ] **Step 5: Run the tests again** → PASS. `make gen` produces no diff outside the new mock.
- [ ] **Step 6: Commit** `PMM-15978 Let only PMM Extensions call scripts`.

---

### Task 5: `StartRun` and `GetRun`

**Files:**
- Create: `managed/services/agents/script_runs.go`, `managed/services/agents/script_runs_test.go` (new files)
- Modify: `managed/models/script_run_model.go` (the shared types), `managed/services/scripts/scripts.go`, `managed/services/scripts/deps.go`, `managed/services/agents/deps.go` (`agentSender`), `managed/services/agents/registry.go` (implements `agentSender`; `isConnectedHere`), `.mockery.yaml` (an entry for `github.com/percona/pmm/managed/services/agents` with `agentSender`), `managed/cmd/pmm-managed/main.go` (build the service after `NewJobsService`, `:1102`)
- Test: `managed/services/scripts/scripts_test.go` (new file), `managed/services/agents/script_runs_test.go`

**Interfaces:**
- In `agents/deps.go`, so that tests need no live stream:

```go
type agentSender interface {
	// sendToAgent sends one request on the pmm-agent's stream held by this replica.
	// It returns errAgentNotConnected when this replica holds no stream for it.
	sendToAgent(ctx context.Context, pmmAgentID string, req agentv1.ServerRequestPayload) (agentv1.AgentResponsePayload, error)
}
```

  `Registry` implements it with `r.get(pmmAgentID)` (`registry.go:577-585`) and `channel.SendAndWaitResponse(ctx, …)` (`channel.go:180`) [V]; a miss in `r.get` becomes `errAgentNotConnected`, a new package-level error in `script_runs.go`. The implementation returns an interface, so it carries `//nolint:ireturn`, as `SendAndWaitResponse` does.
- `func (r *Registry) isConnectedHere(pmmAgentID string) bool`: whether `r.get` finds the pmm-agent, the same lookup a send uses. It is not `Registry.IsConnected`, which in HA reads every replica's `is_connected` column through a cache (`registry.go:185-207`, `:216-247`) [V] and would call a host connected that this replica cannot reach.
- In `models/script_run_model.go`:

```go
type ScriptFile struct {
	Name      string
	Content   string
	Mode      os.FileMode
	Sensitive bool
}

type StartScriptRunParams struct {
	RunID          string
	PMMAgentID     string
	Files          []ScriptFile
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
```

  Nothing in `models` writes `Files[].Content`, `Env` values or `Stdin`; `Mode` is 0600 when the request gave 0.
- In `agents/script_runs.go`:

```go
const (
	agentCallTimeout    = 10 * time.Second
	startDeadlineMargin = 5 * time.Second
)

type ScriptRunsService struct { db *reform.DB; sender agentSender; r *Registry; l *logrus.Entry; waiters *runWaiters }

func NewScriptRunsService(db *reform.DB, r *Registry) *ScriptRunsService
func (s *ScriptRunsService) StartRun(ctx context.Context, p *models.StartScriptRunParams) (*models.ScriptRun, error)
func (s *ScriptRunsService) IsConnected(pmmAgentID string) bool
```

- In `scripts/deps.go`, `scriptRuns` gains `StartRun` and `IsConnected`. `Server.StartRun` and `Server.GetRun` convert between `scriptsv1beta1` and these types; a helper `runToProto(*models.ScriptRun, bool) *scriptsv1beta1.Run` is shared by every RPC that returns a run.

**Steps of `StartRun`** ([spec §6.2](../spec.md#62-what-a-run-is), §9.3):
1. **Validate** in `Server.StartRun`, after the generated rules (`grpc_validator`, `main.go:288`) [V]. Each failure is `codes.InvalidArgument` naming the rule, and no record is made:
   - the total bytes of `files[].content` above `RunScriptMaxFilesBytes`; `stdin` above `RunScriptMaxStdinBytes`; the bytes of every `command` item plus every env name and value above `RunScriptMaxCommandEnvBytes`;
   - two files with one name; a file name `.`, `..` or `out`;
   - an env name starting with `PMM_RUN_` or `LD_`, or equal to `PATH` (00); an env name given twice;
   - `memory_max` above 0 and below `minMemoryMax`.

   Then the defaults, each when 0 or absent: a file `mode` `RunScriptDefaultFileMode` (0600), `timeout` `RunScriptDefaultTimeout`, `start_within` `RunScriptDefaultStartWithin`, `max_output_bytes` `RunScriptDefaultMaxOutputBytes`, `keep_files_for` `RunScriptDefaultKeepFilesFor`. The record and pmm-agent always see the values used.
2. **An id that exists**: `models.FindScriptRunByID` finds it → return that record, send nothing. The race of two first calls is settled by `CreateScriptRun` in step 4.
3. **Find the pmm-agent**: `models.FindAgentByID` (`agent_helpers.go:427`) [V]; not found, or not `models.PMMAgentType` (`agent_model.go:80`) [V] → `codes.NotFound`. An unknown pmm-agent is an error, not a record: a record needs a host. Its node by `models.FindNodeByID` (`node_helpers.go:153`) [V] for `node_id` and `node_name`.
4. **Create the record** with `CreateScriptRun`: state `pending`, `start_deadline` = now + `agentCallTimeout` + `startDeadlineMargin`, so every `pending` record has one from its creation and a start still in flight is never judged (Task 7). The request is stored without its secrets: `size`, `mode` and `sensitive` per file, the `sha256` only for a file that is not sensitive, `env_names` sorted. If `CreateScriptRun` reports the id was not new, return the stored record and send nothing.
5. **Not started without sending**, in the roadmap's order and with its texts (→ `not_started` with the reason, `finished_at`):
   1. this replica holds no stream for the pmm-agent (`isConnectedHere`): "pmm-agent is not connected";
   2. its stored version is below `ScriptRunsSupportVersion` or does not parse: "pmm-agent is too old to run scripts". The version is the one `authenticate` stores on connect (`registry.go:392-393`) [V]; a pmm-agent that never connected has none, and step 5.1 has already answered for it;
   3. the host facts of this connection (Task 7) say script runs are switched off: "script runs are switched off on this host";
   4. the facts say pmm-agent is not root and `run_as` is set: "run_as needs a pmm-agent that runs as root";
   5. the facts say the host is not contained and `memory_max` is set: "memory_max needs a host where runs are contained".

   Checks 3 to 5 need the facts, which arrive with Task 7; until a connection has reported them, the start is sent, and pmm-agent applies the same rules itself (plans 01 and 03). Task 7 adds those three checks and their tests.
6. **Send** `StartJobRequest{job_id: run_id, timeout, job: run_script{…}}`, each file with its name, content and mode, with `sendToAgent` under `context.WithTimeout(ctx, agentCallTimeout)`. The field names inside `RunScript` are plan 01 Task 1's.
7. **The answer:**
   - `errAgentNotConnected` (the stream went between step 5 and the send): `not_started`, "pmm-agent is not connected";
   - pmm-agent answered with a refusal: a non-empty `StartJobResponse.error`, as `jobs.go:445-447` reads it [V], or an error that carries a gRPC status, which the channel returns for a non-OK answer (`channel.go:448-454`) [V] → `not_started` with that text, the last reason of the roadmap's list. This covers pmm-agent's own limits and a pmm-agent that does not know the job type;
   - **any other error**: the deadline passed, or the stream closed while waiting. The record stays `pending`, with the reason "pmm-agent did not answer the start within 10 s; the next check with it settles the run", and the run's pmm-agent is asked which runs it knows (Task 7, `requestCheck`). The script may have started, so the run is not `not_started`;
   - accepted → `TransitionScriptRun(…, queued, QueuedAt: now)`; the guard leaves a run that a message has already moved;
   - a stop held while the run was `pending` (Task 8) is sent now.
8. **Return** the record, whatever its state. A run that cannot start is a record, not an error ([spec §6.7](../spec.md#67-the-api)).

`GetRun` without `wait`: `models.FindScriptRunByID`; `codes.NotFound` "script run <id> not found" when absent; `agent_connected` from `IsConnected`, which is `isConnectedHere`. It says whether this replica holds the host's stream now, not since when it does not: nothing records that.

- [ ] **Step 1: Write the failing tests** in `agents/script_runs_test.go`, with go-sqlmock and the generated `mockAgentSender`:
  - `TestStartRunNotConnected`: no stream here → `sendToAgent` is not called; the record ends `not_started`, "pmm-agent is not connected". A pmm-agent row with no version gives the same.
  - `TestStartRunTooOld` (T10): connected at a version below the gate → `not_started`, "pmm-agent is too old to run scripts"; no send.
  - `TestStartRunRefused`: the response's `error` "<text>" → `not_started` with that text.
  - `TestStartRunStatusError`: `sendToAgent` returns a `codes.Unimplemented` status → `not_started` with its text.
  - `TestStartRunAccepted`: the request carries `job_id` = the run id, the timeout, the files with their modes, the env, the stdin; the record ends `queued` with `queued_at`; its request summary holds each file's mode, and no `sha256` for a sensitive file.
  - `TestStartRunNoAnswer`: a sender that blocks → the call returns within `agentCallTimeout` plus a margin; the record stays `pending` with the reason and a `start_deadline`; a check of that pmm-agent is requested.
  - `TestStartRunChannelGone`: the sender returns an error that carries no gRPC status → `pending`, as above.
  - `TestStartRunDisconnectedAtSend`: the sender returns `errAgentNotConnected` → `not_started`, "pmm-agent is not connected".
  - `TestStartRunSameID`: a run id that exists → the stored record, no insert, no send.
  - `TestStartRunNoSecretsStored` (T13 in part): the SQL arguments sqlmock receives contain neither a file's content, nor an env value, nor the stdin, nor the SHA-256 of a sensitive file.
- [ ] **Step 2: Write the failing tests** in `scripts/scripts_test.go`, with the mocked `scriptRuns`:
  - each validation rule of step 1 → `InvalidArgument` and no call, including `command` and `env` of 64 KiB plus one byte together, a file named `out`, and `memory_max` of 16 MiB minus one byte; `memory_max` 0 and 16 MiB pass;
  - the defaults reach `StartRun`, including a file `mode` of 0 as 0600 and 0700 unchanged;
  - an unknown pmm-agent → `NotFound`; `GetRun` of an unknown id → `NotFound` with "script run <id> not found";
  - `TestStartRunRequestRedacted`: a `StartRunRequest` with a file content, an env value and a stdin, each a distinct marker, formatted as the debug log of `interceptors.UnaryAdd` formats a request, `prototext.Format(logger.RedactMessage(req))` (`managed/utils/interceptors/interceptors.go:134-147`) [V] → none of the three markers appears; the file name and the env name do.
- [ ] **Step 3: Run** `cd managed && go test -race -p 1 -run 'TestStartRun|TestGetRun' ./services/agents/ ./services/scripts/` → FAIL: undefined.
- [ ] **Step 4: Implement**, then `make gen` for the new mocks.
- [ ] **Step 5: Run again** → PASS.
- [ ] **Step 6: Commit** `PMM-15978 Start script runs on pmm-agent`.

---

### Task 6: Receiving `JobMessagesRequest`

**Files:**
- Modify: `managed/services/agents/handler.go` (plan 01 Task 1's stub case in the dispatch `:120-177`; `Handler` and `NewHandler` `:47-71`), `managed/services/agents/deps.go` (`scriptRunsService`), `managed/services/agents/script_runs.go`, `managed/cmd/pmm-managed/main.go` (`NewHandler` call `:1104`)
- Test: `managed/services/agents/script_runs_messages_test.go` (new file, `testdb`)

**Interfaces:**
- The channel cases for the new messages, and a stub case in `handler.go`, come from plan 01 Task 1. This task replaces the stub.
- In `deps.go` (Task 7 adds its own method):

```go
type scriptRunsService interface {
	handleJobMessages(ctx context.Context, pmmAgentID string, req *agentv1.JobMessagesRequest) *agentv1.JobMessagesResponse
}
```

- In `handler.go`, the case for `*agentv1.JobMessagesRequest`: `resp := h.scriptRuns.handleJobMessages(ctx, agent.id, p)`, then `agent.channel.Send(&channel.ServerResponse{ID: req.ID, Payload: resp})`. It runs in the loop, as every other request does.

**Rules** ([spec §6.3](../spec.md#63-delivery-of-output-and-results), [ADR-04](../adr/ADR-04-acknowledged-delivery.md)):
1. **Every item gets an answer, `ANSWER_STORED` or `ANSWER_DISCARDED`**, in the order of the request (plan 01 Task 1's `JobMessagesResponse`). pmm-agent drops an item on either answer, and sends again only the items that got none.
2. **Store first, answer second.** All items of one request are handled in one transaction, each inside its own savepoint (`SAVEPOINT`, then `RELEASE` or `ROLLBACK TO`).
   - A failure that a retry can fix (a lost connection, a serialization failure or deadlock, a canceled statement) ends the whole transaction, and the response answers none of the items: pmm-agent sends them all again.
   - **A failure that no retry can fix**: a `*pq.Error` (`errors.As`, as `advisor_run_helpers.go:41-42` does) [V] of class `22` (data exception, such as a NUL byte in text) or `23` (integrity) [I: lib/pq's `ErrorCode.Class`]. The item's savepoint is rolled back, the item is `discarded`, its bytes are added to the run's `dropped_bytes`, and a warning names the run, the chunk and the code. The rest of the batch goes on, so one bad chunk cannot hold up a host's delivery.

   The prototype answered even after a failed write (prototype `handler.go:173-185`) [V]; that is not kept.
3. **`discarded`, and a stop:** an item for a run with no open record: no row at all (after a restore of PMM Server), or a final record (a late result, or output after the run was closed). The run's id gets one `StopJobRequest` to the pmm-agent that sent the item, with `agentCallTimeout`, from a goroutine started after the commit, so the loop is not held. A failed send is logged; the next check sends it again (Task 7, step 5).
4. **`discarded` without a stop:** an item whose run has an open record of another pmm-agent. Nothing is stored, no stop is sent to either pmm-agent, and pmm-managed logs a warning with both pmm-agent ids.
5. **Logs:** `AddScriptRunLogs` per run, so `(run_id, chunk_id)` dedups: a chunk already stored is answered `stored`. A chunk refused because it would pass `max_output_bytes` is `discarded`, and its bytes are counted in `dropped_bytes`. Bytes are counted on the text as received, after pmm-agent's replacement of invalid bytes; plan 01 counts the same text.
6. **A message before its start's answer.** A `pending` record that receives an item from its own pmm-agent has been accepted: it first moves `pending` → `queued` (`QueuedAt`: now), then on along the arrows. A `started` progress, or a result that implies the process ran, moves it on to `running` first.
7. **`started`:** `TransitionScriptRun(running, StartedAt)`; `stored`.
8. **The result:** one case for every outcome pmm-agent can send, plan 01 Task 1's enum:

   | Outcome | State | From |
   |---|---|---|
   | `OUTCOME_SUCCEEDED` | `succeeded` | `running` |
   | `OUTCOME_FAILED` | `failed` | `running` |
   | `OUTCOME_TIMED_OUT` | `timed_out` | `running` |
   | `OUTCOME_STOPPED` | `stopped` | `queued` or `running` |
   | `OUTCOME_EXPIRED` | `expired` | `queued` |
   | `OUTCOME_PREPARE_FAILED` | `prepare_failed` | `queued` |
   | `OUTCOME_LOST` | `lost`, with pmm-agent's reason (for example "pmm-agent was stopped") | `queued` or `running` |
   | `OUTCOME_UNSPECIFIED`, or a value this pmm-managed does not know | `failed`, with the reason "pmm-agent sent outcome <n>, which this PMM Server does not know", and a warning | `running` |

   Each stores `exit_code`, `reason`, `started_at`, `finished_at` and adds the pmm-agent's `dropped_output_bytes` to `dropped_bytes`; `stored`. A result for a record that is already final falls under rule 3.
9. **After the commit**, a run that turned final wakes its waiters (Task 8).

- [ ] **Step 1: Write the failing tests** on `testdb.Open(t, models.SkipFixtures, nil)`, with a run row per case and `mockAgentSender` for stops:
  - `TestJobMessagesStoresThenAnswers`: three chunks and `started` for a `queued` run → three rows, state `running`, every item `stored`.
  - `TestJobMessagesDuplicateChunk`: chunk 1 twice in two requests → one row; both answers are `stored`.
  - `TestJobMessagesStoreFailsNoAnswer`: the run's row locked by another transaction, with a statement timeout set for the test → no item is answered; nothing is stored; no stop is sent.
  - `TestJobMessagesPermanentFailure`: a chunk whose `data` holds a NUL byte, between two good chunks → the bad one `discarded` with its bytes in `dropped_bytes`, the two others `stored`.
  - `TestJobMessagesNoOpenRecord`: a chunk for an id with no row, and a chunk for a `succeeded` run → both `discarded`, nothing stored, one `StopJobRequest` per run id to the sender.
  - `TestJobMessagesWrongAgent`: an item for a run sent to `pmm-agent-a`, arriving from `pmm-agent-b` → `discarded`, nothing stored, no stop, a warning with both ids.
  - `TestJobMessagesOutputCap`: `max_output_bytes` 10, chunks of 6 bytes → the first `stored`, the second `discarded`, `dropped_bytes` 6.
  - `TestJobMessagesBeforeStartAnswer`: a `pending` run receives `started`, then `OUTCOME_SUCCEEDED` → `queued_at` set, then `running`, then `succeeded`; no arrow outside spec §6.2 is used.
  - `TestJobMessagesResult`: one table case per row of the table above, unknown value included → the state, `exit_code`, `reason`, `finished_at`, `final_seq`; the stop row is gone; `stored`.
  - `TestJobMessagesLateResult`: a run already `lost` receives `OUTCOME_SUCCEEDED` → it stays `lost`; the item is `discarded` and a stop is sent.
- [ ] **Step 2: Run** in the devcontainer: `… go test -race -p 1 -run 'TestJobMessages' ./services/agents/` → FAIL.
- [ ] **Step 3: Implement.** Update `NewHandler`'s callers, including `main.go:1104`.
- [ ] **Step 4: Run again** → PASS. `cd managed && go test -race -p 1 ./services/agents/...` has no other failure.
- [ ] **Step 5: Commit** `PMM-15978 Store script run output, then answer`.

---

### Task 7: The check with pmm-agent

**Files:**
- Modify: `managed/services/agents/handler.go` (`Run`, after `h.state.RequestStateUpdate(ctx, agent.id)` at `:97`), `managed/services/agents/registry.go` (`pmmAgentInfo` `:82-87`), `managed/services/agents/deps.go`, `managed/services/agents/script_runs.go`
- Test: `managed/services/agents/script_runs_check_test.go` (new file, `testdb`), `managed/services/agents/script_runs_test.go`

**Interfaces:**

```go
// hostFacts are what pmm-agent reported in its last ListRunsResponse on this connection.
type hostFacts struct {
	User      string
	Contained bool
	Disabled  bool
	Capacity  uint32
	Queue     uint32
}

// In pmmAgentInfo: nil until the first answer on this connection.
facts   atomic.Pointer[hostFacts]
// In pmmAgentInfo: a buffered channel of one; a send asks for another check.
recheck chan struct{}

const (
	checkRetryMin = time.Second
	checkRetryMax = 30 * time.Second
)

// runChecks asks pmm-agent which runs it knows, settles the records, and repeats on request, until ctx ends.
func (s *ScriptRunsService) runChecks(ctx context.Context, agent *pmmAgentInfo)
// requestCheck asks for a check of that pmm-agent's runs, if this replica holds its stream.
func (s *ScriptRunsService) requestCheck(pmmAgentID string)
```

- `scriptRunsService` in `deps.go` gains `runChecks`; `handler.go:97` gains `go h.scriptRuns.runChecks(ctx, agent)`. It runs beside the loop, so it never delays it; a `ListRunsResponse` is delivered by the channel's receiver, not by the loop (`channel.go:305-327`) [V].

**One check** ([spec §6.4](../spec.md#64-reconnect-and-lost-runs)):
1. A pmm-agent below the gate is never asked: `runChecks` returns.
2. `asked := models.Now()`; send `ListRunsRequest` with `agentCallTimeout`. **No answer**: ask again on the same stream after a pause that starts at `checkRetryMin` and doubles up to `checkRetryMax`, until an answer arrives or the stream ends. pmm-agent serves some requests one at a time (`agent/client/client.go:595-599`) [V], so an answer can be late on a healthy connection. Nothing is judged while there is no answer.
3. Store the host facts on `agent.facts`.
4. For each record of `FindScriptRunsToCheck(agent.id, asked)` (Task 2):
   - **in the answer**: the record follows the run's phase along the arrows. `PHASE_WAITING`: a `pending` record moves to `queued`. `PHASE_RUNNING`: `pending` or `queued` moves on to `running`. `PHASE_DELIVERING`: nothing; the result is on its way. Then, if `FindScriptStop` finds a held stop, send `StopJobRequest{job_id}`;
   - **not in the answer**, `queued` or `running`: `lost`, "pmm-agent no longer has the run: it restarted, or its result was lost";
   - **not in the answer**, `pending`: `lost`, "pmm-agent did not answer the start and does not have the run; the script may have started".

   Wake the waiters of every record that turned final.
5. For each id in the answer with no open record (final, or no row at all): send `StopJobRequest`. Nothing is stored for it. An id whose record is open but was not judged in step 4 (a start in flight) is left alone.

**When a check runs:** once when the stream registers, and again each time `recheck` receives: `requestCheck` is called after any start that got no answer (Task 5, step 7). A check that is waiting for an answer absorbs a further request.

**The facts in `StartRun`.** From this task on, `StartRun` reads `agent.facts` for checks 3 to 5 of its step 5, in that order and with the roadmap's texts. pmm-agent is root when `facts.User` is `root` [I: plan 03 fills `user` with the name of the user pmm-agent runs as].

- [ ] **Step 1: Write the failing tests** with `mockAgentSender` and `testdb`:
  - `TestCheckLost` (T3 in part): two `running` records with `queued_at` before the question, the answer lists one → the other is `lost` with the reason.
  - `TestCheckQueuedNotLost`: a `queued` record listed as `PHASE_WAITING` → unchanged.
  - `TestCheckFollowsPhase`: a `queued` record listed as `PHASE_RUNNING` → `running`.
  - `TestCheckResultInFlight`: a `running` record listed as `PHASE_DELIVERING` → unchanged; then the result arrives (Task 6) → final.
  - `TestCheckSendsHeldStop` (T6 in part): a listed run with a stop row → one `StopJobRequest`; the row stays until the result.
  - `TestCheckStopsUnknown` (T7 in part): an id with no row, and one whose row is `succeeded` → a `StopJobRequest` each; no row is created.
  - `TestCheckStartInFlight`: a `pending` record whose `start_deadline` is after `asked`, absent from the answer → unchanged; its id present in the answer → no stop.
  - `TestCheckQueuedAfterQuestion`: a `queued` record whose `queued_at` is after `asked`, absent from the answer → unchanged.
  - `TestCheckUnansweredStartProceeds`: a `pending` record past its `start_deadline`, listed as `PHASE_WAITING` → `queued`.
  - `TestCheckUnansweredStartLost`: the same, not in the answer → `lost` with the "may have started" reason.
  - `TestCheckRetriesUntilAnswered`: the sender times out twice, then answers → three requests, pauses of about 1 s and 2 s (a fake clock), then the records are judged; with the context canceled during a pause → no further request, nothing changed.
  - `TestCheckAfterUnansweredStart`: `requestCheck` while no check runs → one more `ListRunsRequest`.
  - `TestCheckTooOld`: a version below the gate → no request is sent.
  - In `script_runs_test.go`, `TestStartRunFromFacts`: facts with `Disabled` → `not_started`, "script runs are switched off on this host"; `User: "pmm-agent"` and `run_as` set → "run_as needs a pmm-agent that runs as root"; `Contained: false` and `memory_max` 64 MiB → "memory_max needs a host where runs are contained"; all three at once → the first; no facts yet → sent. No `StartJobRequest` in the refused cases.
- [ ] **Step 2: Run** in the devcontainer: `… go test -race -p 1 -run 'TestCheck|TestStartRunFromFacts' ./services/agents/` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run again** → PASS.
- [ ] **Step 5: Commit** `PMM-15978 Check pmm-agent runs until answered`.

---

### Task 8: `StopRun`, the two waits, `ListRuns`, `GetRunLogs`, `ListRunFiles`, `ReadRunFile`

**Files:**
- Modify: `managed/services/agents/script_runs.go`, `managed/services/scripts/scripts.go`, `managed/services/scripts/deps.go`, `managed/utils/interceptors/interceptors.go` (`logRequest` `:42-82`, `dropEndpointsRE` `:111`, `UnaryAdd` `:114-147`)
- Test: `managed/services/agents/script_runs_test.go`, `managed/services/scripts/scripts_test.go`, `managed/utils/interceptors/interceptors_test.go`

**Interfaces:**

```go
// StopRunResult is what StopRun did.
type StopRunResult struct { Run *models.ScriptRun; Sent bool }

func (s *ScriptRunsService) StopRun(ctx context.Context, runID string) (*StopRunResult, error)
func (s *ScriptRunsService) WaitFinal(ctx context.Context, runID string, wait time.Duration) (*models.ScriptRun, error)
// WaitFinalAfter returns the runs final after the cursor at once, or waits for the first one, at most wait.
func (s *ScriptRunsService) WaitFinalAfter(ctx context.Context, pmmAgentID string, finalAfter int64, limit int, wait time.Duration) ([]*models.ScriptRun, error)
func (s *ScriptRunsService) ListRunFiles(ctx context.Context, runID string) ([]models.ScriptRunFileInfo, error)
// ReadRunFile returns the bytes read and whether they reach the end of the file.
func (s *ScriptRunsService) ReadRunFile(ctx context.Context, runID, name string, offset, length int64) ([]byte, bool, error)

// runWaiters wakes waiting calls on this replica: per run id, and once for any run that turns final.
type runWaiters struct { mu sync.Mutex; byRun map[string][]chan struct{}; anyFinal []chan struct{} }

const waitReread = time.Second
```

`StopRunResult` stands in for two results, so `StopRun` needs no named results (Global Constraints).

- **`StopRun`** ([spec §6.5](../spec.md#65-containment)): `codes.NotFound` for an unknown run. A run already final: the record unchanged, `sent: false`; nothing is held or sent. An open run:
  - `HoldScriptStop` first, in PostgreSQL;
  - then, if this replica holds the pmm-agent's stream and the run is not `pending`, `StopJobRequest` with `agentCallTimeout`; `sent` is true when pmm-agent answered. A failed send leaves the stop held and returns `sent: false`, not an error;
  - it returns at once with the record and never waits for the run to end. A `pending` run's stop is sent by `StartRun` once pmm-agent accepts it (Task 5, step 7), or by the check (Task 7). The stop row goes when the run turns final (Task 2).
- **`GetRun` with `wait`**, for a caller that follows one run: when the run is open, `WaitFinal` waits for a wake-up from Task 6 or 7 or the end of the wait, and re-reads the record every `waitReread` meanwhile, so it returns whichever replica stored the result ([ADR-13](../adr/ADR-13-high-availability.md)). It returns the record as it then is.
- **`ListRuns`**, every answer carries `cursor` ([spec §6.7](../spec.md#67-the-api)):
  - **plain** (no `final_after`, no `from_now`): `FindScriptRuns` by `pmm_agent_id` and `final`, ordered by `created_at` descending (`script_runs_created_at_idx`), `page_size` default `defaultListPageSize`, with `total_items` and `total_pages` as `ListInsightsResponse` (`advisors.proto:302-306`) [V]; `cursor` is `CurrentScriptRunsCursor`. `wait` without `final_after` is `codes.InvalidArgument`.
  - **`from_now`**: no runs, `cursor` is `CurrentScriptRunsCursor`. With `final_after`, `final`, `page_index` or `wait` it is `codes.InvalidArgument`.
  - **`final_after`**, for a caller that keeps one call open to hear of every run's end ([ADR-10](../adr/ADR-10-api-shape.md); plan 04): the cursor is the decimal text of a `final_seq`, and `""` means 0; anything else is `codes.InvalidArgument`, as are `final` and `page_index` with it. `page_size` caps the runs returned; `pmm_agent_id` filters. Runs whose `final_seq` is above the cursor come back at once, by `final_seq`. With none, `WaitFinalAfter` waits for the broadcast wake-up or the end of `wait`, re-reading every `waitReread`, and returns what it then finds, which may be nothing. `cursor` is the `final_seq` of the last run returned, otherwise the larger of the given cursor and `CurrentScriptRunsCursor`. `total_items` and `total_pages` are 0.
  - A run deleted by retention before the caller read it is not returned. The caller's own periodic check of its open runs covers a cursor that is older than 7 days.
- **`GetRunLogs`**: `FindScriptRunLogs(offset, limit)`, `limit` default 100. `end` is true when the run is final and the page holds the run's last stored chunk. Unlike `BackupService.GetLogs` (`backup_service.go:426-475`) [V], there is no `last_chunk` row: the final state marks the end. A run whose output the cleaner deleted (Task 10) returns no chunks and `end: true`, and its record says `output_deleted`.
- **`ListRunFiles` and `ReadRunFile`**: relayed to pmm-agent with `ReadRunFileRequest` and `agentCallTimeout`; nothing is stored. No stream on this replica → `codes.FailedPrecondition` "pmm-agent is not connected"; pmm-agent's own error (no such file, not a regular file, a run it no longer knows) → `codes.NotFound` with its text. A known run whose `out/` is empty or gone lists no files, which is not an error. Confinement to `out/` is pmm-agent's ([spec §6.7](../spec.md#67-the-api), plan 01). The gateway writes `data` as base64 in JSON [I: grpc-gateway's `JSONPb` for `bytes`].
- **Logging of the two waiting calls.** `logRequest` logs every call at info and any call of 1 s or more at warning (`interceptors.go:42-82`) [V]. A caller keeps one `ListRuns` open at all times, so pmm-managed would log a warning every 30 s. A new `waitingEndpointsRE` (`^/scripts.v1beta1.ScriptsService/(GetRun|ListRuns)$`) makes `UnaryAdd` log those two methods at debug, start and end, whatever their length; an error is still logged as today. `dropEndpointsRE` gains `ReadRunFile` and `GetRunLogs`, so a debug log does not print up to 2 MiB of a file or a page of output. The agent channel's own debug log prints every message whole (`channel/channel.go:261-267`) [V], including a 2 MiB file read; that is debug level only, and this plan leaves it as it is.

- [ ] **Step 1: Write the failing tests:**
  - `TestStopRunConnected`: a `running` run → a stop row and one `StopJobRequest`; `sent: true`.
  - `TestStopRunHeld` (T6 in part): no stream here → a stop row, no send, `sent: false`. A new `ScriptRunsService` on the same database (a restart of pmm-managed) and a check with the run in the answer → the stop is sent.
  - `TestStopRunPending`: a `pending` run → held; `StartRun` accepted → the stop is sent right after.
  - `TestStopRunFinal`: a `succeeded` run → the record unchanged, `sent: false`, no stop row, no send.
  - `TestGetRunWait`: a run turned final by `handleJobMessages` 100 ms into a 5 s wait → returns within 300 ms.
  - `TestGetRunWaitRereads`: the row turned final by another `ScriptRunsService` on the same database, as another replica would → returns within about 1.2 s.
  - `TestGetRunWaitTimesOut`: nothing happens → returns the open record after the wait.
  - `TestListRuns`: filters, order and paging; `cursor` set; `wait` without `final_after` → `InvalidArgument`.
  - `TestListRunsFromNow`: two runs already final → no runs, and `cursor` equal to the second's `final_seq`; `from_now` with `final_after` → `InvalidArgument`.
  - `TestListRunsFinalAfter`: two runs already final → both at once, in order, with `cursor` the second's; called again with it and a 5 s wait, a third run turned final 100 ms in → returned within 300 ms; a wait with nothing happening → no runs, `cursor` unchanged; `final_after: "x"` → `InvalidArgument`.
  - `TestListRunsWaitRereads`: a run turned final by another `ScriptRunsService` on the same database → returned within about 1.2 s.
  - `TestListRunsFinalAfterConcurrent`: 20 goroutines turn 200 runs final while a reader loops on `ListRuns` with `final_after`, `wait` and each answer's `cursor` → the reader sees all 200, each once.
  - `TestGetRunLogs`: offsets; `end` false while open, true once final and read to the last chunk; `end: true` with no chunks for a run whose output was deleted.
  - `TestReadRunFile`: the request carries offset and length; pmm-agent's error → `NotFound`; no stream here → `FailedPrecondition`.
  - `TestWaitingCallsLogAtDebug` (interceptors): a `ListRuns` call of 1.5 s through `UnaryAdd` logs nothing at info or warning; another method of 1.5 s still logs its warning.
- [ ] **Step 2: Run** in the devcontainer: `… go test -race -p 1 -run 'TestStopRun|TestGetRunWait|TestListRuns|TestGetRunLogs|TestReadRunFile' ./services/agents/ ./services/scripts/` and on the host `cd managed && go test -race -p 1 -run TestWaitingCallsLogAtDebug ./utils/interceptors/` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run again** → PASS.
- [ ] **Step 5: Commit** `PMM-15978 Stop, wait for and read script runs`.

---

### Task 9: `ListHosts`

**Files:**
- Modify: `managed/services/agents/channel/channel.go` (`runReceiver` `:245-343`: the time of the last message, and whether the receiver waits on a full request queue), `managed/services/agents/registry.go` (a reader of the host state), `managed/services/agents/script_runs.go`, `managed/services/scripts/scripts.go`
- Test: `managed/services/agents/channel/channel_test.go`, `managed/services/agents/registry_test.go`, `managed/services/agents/script_runs_test.go`, `managed/services/scripts/scripts_test.go`

**Interfaces:**

```go
// In channel.Channel. lastRecv holds the Unix time in nanoseconds of the last message received.
lastRecv atomic.Int64
// In channel.Channel. queueStall is true while the receiver waits for room in the request queue.
queueStall atomic.Bool

// LastReceived returns when the last message from pmm-agent arrived.
func (c *Channel) LastReceived() time.Time
// Stalled reports whether the receiver waits for pmm-managed's own loop to take a request.
func (c *Channel) Stalled() bool

const responsiveWindow = 30 * time.Second

// ScriptHostState is what this replica knows of one pmm-agent.
type ScriptHostState struct { Connected, Responsive bool; Facts *hostFacts }

func (r *Registry) scriptHostState(pmmAgentID string) ScriptHostState
func (s *ScriptRunsService) ListHosts(ctx context.Context) ([]*models.ScriptHost, error)
```

- **Rows** ([spec §6.8](../spec.md#68-the-host-list)): one per `pmm-agent` row, from `models.FindAgents(q, models.AgentFilters{AgentType: new(models.PMMAgentType)})`, the form `registry.go:223` uses [V], with its node's name, id and address.
- **`connected`**: `isConnectedHere`, the in-memory lookup a send uses (Task 5), not `Registry.IsConnected`. The list and a start agree on every replica.
- **`responsive`** ([ADR-12](../adr/ADR-12-host-list.md)): any message received from pmm-agent is proof of life. `runReceiver` stores the time after each successful `Recv` (`channel.go:251-257`) [V]. The host is responsive while `LastReceived` is within `responsiveWindow`, or while `Stalled` is true: when the receiver waits because pmm-managed's own loop has not taken the 32 queued requests (`channel.go:36`, `:270-303`) [V], silence is pmm-managed's, not the host's. The ping every 10 s (`handler.go:40`) [V] keeps a healthy, idle host above the window; nothing about the ping changes, and it still does not drop a connection.
- **`can_run` and `reason`**, in this order: not connected → "pmm-agent is not connected"; not responsive → "pmm-agent has not answered for 30 s"; below the gate → "pmm-agent is too old to run scripts"; no facts yet on this connection (Task 7 has not had an answer) → "being checked"; facts with `Disabled` → "script runs are switched off on this host". Otherwise `can_run: true`.
- **`user`, `contained`, `capacity`, `queue`**: from the facts; empty and 0 while there are none.

- [ ] **Step 1: Write the failing tests:**
  - `TestLastReceived` (`channel_test.go`, with its `setup` at `:52`) [V]: a message from the client moves `LastReceived`; with the request queue full and nobody reading it, `Stalled` is true.
  - `TestScriptHostConnected` (`registry_test.go`, `newTestRegistry` at `:69-81`) [V]: a pmm-agent in this registry's map → connected; one that only the HA connection cache lists → not connected.
  - `TestResponsive`: last message 10 s ago → responsive; 31 s ago → not; 31 s ago with `Stalled` → responsive.
  - `TestListHosts`: seven pmm-agent rows: not connected; connected, silent for 31 s; connected below the gate; connected with no facts yet; connected with `Disabled` facts; and one that can run with `user: root`, `contained: true`, `capacity: 16`, `queue: 256` → the reasons above, in that order of checks, and the facts in the last row.
  - `TestListHostsServer`: the conversion to `scriptsv1beta1.Host`.
- [ ] **Step 2: Run** `cd managed && go test -race -p 1 -run 'TestLastReceived|TestScriptHostConnected|TestResponsive|TestListHosts' ./services/agents/... ./services/scripts/` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run again** → PASS.
- [ ] **Step 5: Commit** `PMM-15978 List the hosts that can run scripts`.

---

### Task 10: The cleaner, and the runs of a removed pmm-agent

**Files:**
- Create: `managed/services/scripts/cleaner.go`, `managed/services/scripts/cleaner_test.go` (new files)
- Modify: `managed/services/agents/registry.go` (`Kick` `:547-549`), `managed/services/agents/script_runs.go`, `managed/cmd/pmm-managed/main.go` (beside the `cleaner` leader service, `:1366-1369`)
- Test: `managed/services/agents/script_runs_test.go`, `managed/cmd/pmm-managed/main_test.go`

**Interfaces:**

```go
// Cleaner deletes old runs, keeps the stored output within its bound, and closes runs of removed pmm-agents.
type Cleaner struct { db *reform.DB; l *logrus.Entry }

func NewCleaner(db *reform.DB) *Cleaner
// Run makes a pass at start, then every retentionInterval, until ctx ends.
func (c *Cleaner) Run(ctx context.Context)

// In agents: called by Registry.Kick before it disconnects a pmm-agent.
func (s *ScriptRunsService) beforeKick(ctx context.Context, pmmAgentID string)

// In main.go, so that the wiring can be tested.
func addScriptRunsCleaner(leader leaderServices, c *scripts.Cleaner)
```

`leaderServices` is a one-method interface in `main.go` with `AddLeaderService(ha.LeaderService)`, which `*ha.Service` has (`managed/services/ha/haservice.go:569`) [V].

- **One pass of the cleaner**, in this order, each step in its own transaction:
  1. `DeleteOldScriptRuns`: final runs whose `finished_at` is older than `runRetention` (7 days), with their logs and stop rows by cascade.
  2. `DeleteOldestScriptRunOutput(maxStoredOutputBytes)`: the stored output of all runs together stays within 1 GiB, the oldest finished runs' output going first ([spec §6.6](../spec.md#66-records-and-retention)). Open runs are never touched; a run whose output goes reads `output_deleted`.
  3. `FindScriptRunsOfRemovedAgents`: each open run whose pmm-agent row is gone becomes `lost`, "pmm-agent was removed from the inventory". This covers a removal that `beforeKick` did not see.

  Each step logs its count at info level when it is not 0. The loop is `clean.Results.Run`'s (`managed/utils/clean/clean.go:38-52`) [V].
- **Leader only.** `addScriptRunsCleaner` calls `leader.AddLeaderService(ha.NewContextService("script-runs-cleaner", …))`, as `cleaner` does (`main.go:1366-1369`; `NewContextService`, `managed/services/ha/leaderservice.go:80`) [V], and `main.go` calls it when the scripts service is registered (Task 4). With HA off, every node is the leader (`managed/services/ha/haservice.go:596-601`) [V].
- **A pmm-agent removed from the inventory** (spec §6.4): every removal of a pmm-agent ends in `Registry.Kick` (`inventory/agents.go:1916-1919`, `inventory/nodes.go:423-425`, `management/node.go:193-195`) [V], after its transaction. `Kick` calls a hook set by `NewScriptRunsService` before it unregisters the stream. `beforeKick`:
  1. returns at once unless the pmm-agent's row is gone (`models.FindAgentByID` answers `NotFound`), so a kick for another reason changes nothing;
  2. for each open run of that pmm-agent, sends `StopJobRequest` on the stream this replica still holds, each with `agentCallTimeout`, and logs a failure;
  3. then moves each of those runs to `lost`, "pmm-agent was removed from the inventory", and wakes its waiters.

  Without a stream on this replica, step 2 sends nothing and step 3 still runs. The cleaner's step 3 closes what is left.

- [ ] **Step 1: Write the failing tests:**
  - `TestCleanerRetention` (`testdb`): runs finished 8 days and 6 days ago, and an open run created 30 days ago → after one pass only the first is gone, with its logs (T23 in part).
  - `TestCleanerOutputBound` (`testdb`): `maxStoredOutputBytes` lowered for the test through an unexported field; three final runs above it together → the oldest loses its output first.
  - `TestCleanerClosesRunsOfRemovedAgents` (`testdb`): an open run whose pmm-agent row was deleted → `lost` with the reason.
  - `TestCleanerStops`: `Run` returns when `ctx` is canceled.
  - `TestRemovedAgentStopsThenLoses` (`script_runs_test.go`, `testdb` and `mockAgentSender`): a pmm-agent with a `running` and a `queued` run, its row deleted, its stream held → two `StopJobRequest`s, then both `lost` with the reason; the order of the calls is checked.
  - `TestKickWithoutRemovalKeepsRuns`: the same with the row still there → no stop, no change.
  - `TestScriptRunsCleanerIsLeaderService` (`main_test.go`): a fake `leaderServices` that records its calls → `addScriptRunsCleaner` adds exactly one service, with the id `script-runs-cleaner`.
- [ ] **Step 2: Run** in the devcontainer: `… go test -race -p 1 -run 'TestCleaner' ./services/scripts/` and `… -run 'TestRemovedAgent|TestKickWithoutRemoval' ./services/agents/`, and on the host `cd managed && go test -race -p 1 -run TestScriptRunsCleanerIsLeaderService ./cmd/pmm-managed/` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run again** → PASS.
- [ ] **Step 5: Commit** `PMM-15978 Clean script runs on the leader`.

---

### Task 11: API tests, the component guides, and the PR

**Files:**
- Create: `api-tests/scripts/scripts_test.go`, `api-tests/scripts/helpers_test.go`, and the helper that derives the token on the test server (new files; its form, a Go test helper or a script beside the tests, is decided in the code PR)
- Modify: `api-tests/init.go` (a flag beside `-pmm.run-advisor-tests` `:103`, its variable `:71-72`, the env map `:108-115`), `api/AGENTS.md` (Key API Services table, `:47-66`), `managed/AGENTS.md` (Key Packages table, `:104-121`)

**Environment:** a PMM Server from a Feature Build of the integration branch with plans 01 and 02 merged, started with `PMM_ENABLE_EXTENSIONS=1` (`.env.example:57-67`) [V]. Its own pmm-agent, `models.PMMServerAgentID` (`agent_model.go:114`) [V], runs the scripts; running scripts on PMM Server through its own pmm-agent is in scope ([spec §14](../spec.md#14-not-in-scope)). See Global Constraints for the version of the build.

**Interfaces:**
- Flag `-pmm.scripts-token` [`PMM_SCRIPTS_TOKEN`]: the hex token. The tests skip when it is empty. A helper beside the tests derives it on the test server; `TestScriptsTokenValue` (Task 4) checks the computation with a fixed vector. Plan 06 uses the same helper for T5, T8, T12, T13, T18 and T21.
- `func scriptsClient(t *testing.T, token string) *client.PMMScriptsAPI`: the generated client on `pmmapitests.Transport` (`init.go:76`) [V] with a `ClientAuthInfoWriter` that adds `X-PMM-Scripts-Token` beside the Basic credentials of `-pmm.server-url` [I: `client.Compose` in go-openapi/runtime].
- `func waitFinal(t *testing.T, c *client.PMMScriptsAPI, runID string) *models.Run`: `GetRun` with `wait=30s` until final, at most 2 minutes.
- Every run id is a new `uuid.NewString()`.

- [ ] **Step 1: Write the tests.** Each cleans up after itself (`api-tests/AGENTS.md`, Do) [V]; runs need no cleanup, as retention removes them.
  - `TestScriptsTokenRequired` (T12): `ListHosts` and `StartRun` as Admin with no token, with a wrong token, and with the internal token itself → 403; with the token → 200.
  - `TestRunSucceeds`: `files: [run.sh]` printing 1,000 numbered lines to stdout and one to stderr, then writing `result.json` to `$PMM_RUN_OUTPUT_DIR`; `command: ["/bin/sh", "run.sh"]` → `succeeded`, `exit_code` 0; `GetRunLogs` read to `end` holds every line once, in order, on its stream; `ListRunFiles` lists `result.json`; `ReadRunFile` returns its content.
  - `TestStartRunSameID`: two `StartRun` calls with one `run_id` → the same record; the script, which appends a line to a file in `/tmp` named after the id, ran once.
  - `TestRunFileModes`: two files, `mode` 0 and `0700`, and a script that prints `stat -c %a` of each → `600` and `700`; a file with `mode` `0644` → 400.
  - `TestRunFails`: `exit 3` → `failed`, `exit_code` 3.
  - `TestRunValidation`: env `LD_PRELOAD`, `PMM_RUN_ID` and `PATH`; a file name `../x`; files of 1 MiB plus one byte; `command` and `env` of 64 KiB plus one byte together; `timeout` of 8 days; `start_within` of 25 h; `max_output_bytes` of 101 MiB; `memory_max` of 1 MiB; a `run_id` that is not a UUID → 400 each, and `ListRuns` shows no new record.
  - `TestStopRun`: `sleep 600` → `StopRun` `sent: true` → `stopped` within 10 s; `StopRun` again → the same record, `sent: false`.
  - `TestListRunsFinalAfter`: `ListRuns` with `from_now` → a cursor and no runs; start two short runs; `ListRuns` with that cursor and `wait=30s`, repeated with each answer's `cursor`, returns both, each once, within 30 s of their end.
  - `TestRunNotConnected`: `pmmapitests.AddGenericNode` (`helpers.go:164`), which removes its node itself after the test (`helpers.go:162-163`) [V], then `AddPMMAgent` (`:263`), never connected, with its removal registered after the node's helper so that it runs first → `not_started`, "pmm-agent is not connected"; `ListHosts` shows it with `can_run: false` and that reason.
  - `TestRunUnknownAgent`: a random `pmm_agent_id` → 404, with a body that is not "Endpoint not found".
  - `TestSecretNotInRecord` (T13 in part): a secret on `stdin` that the script reads and does not print, an env value, and a file marked sensitive → none of them, and not the sensitive file's SHA-256, in `GetRun`'s JSON or in any log chunk. The search of PostgreSQL, the process list and both sides' logs is plan 06's.
  - `TestListHostsServerAgent`: PMM Server's own pmm-agent is listed `connected`, `responsive`, `can_run`, with `capacity` and `queue` set.
- [ ] **Step 2: Run them.** Against the build of Task 1 only, if one exists, they fail with 404 from the gateway; that run is optional, since Task 4 may land after Tasks 5 to 10. Against the build with all tasks → PASS: `cd api-tests && PMM_SERVER_URL=https://<user>:<password>@<host> PMM_SERVER_INSECURE_TLS=1 PMM_SCRIPTS_TOKEN=<token> go test -count=1 -p 1 ./scripts/... -v`.
- [ ] **Step 3: Check absence** on a server started without `PMM_ENABLE_EXTENSIONS`: `curl -sk -u <user>:<password> https://<host>/v1/scripts/hosts` returns the same status and body as `https://<host>/v1/nosuchapi`, for a user that passes `auth_request` on both (the Grafana server admin, Task 4).
- [ ] **Step 4: `go vet ./api-tests/...`** passes. Commit `PMM-15978 Add API tests for script runs`.
- [ ] **Step 5: Update the component guides** (root `AGENTS.md`, "Maintaining This Document") [V]:
  - `api/AGENTS.md`, Key API Services: a row `ScriptsService` | `scripts/v1beta1/` | Script runs on pmm-agent, for PMM Extensions only.
  - `managed/AGENTS.md`, Key Packages: a row for `services/scripts` (the scripts API, its second token, the cleaner), and one sentence under "Database Layer" (`:72`) on the three tables. One sentence on rotation: a change of PMM Extensions' secret, or of `PMM_EXTENSIONS_TOKEN`, needs a restart of pmm-managed and of PMM Extensions.

  Commit `PMM-15978 Describe script runs in the guides`.
- [ ] **Step 6: Open the PR.** Run `make prepare-pr`, push, and open the PR from `PMM-15978-script-runs` into `PMM-15976-script-runs`, with the Feature Build link. No page under `documentation/api/` is written: the package is in `swagger-dev.json` only and no public API reference is published for it (Task 1). Say so beside the template's "API Docs updated" box (`.github/pull_request_template.md:6-8`) [V] instead of ticking it.
