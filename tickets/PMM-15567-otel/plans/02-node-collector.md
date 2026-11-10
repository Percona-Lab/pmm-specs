# OTel 02: Node Collector, Log Sources and Parser Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every node runs at most one pmm-agent-managed OpenTelemetry Collector, as the non-root `pmm-agent` user. It ships the node's log sources to PMM Server through a disk-backed queue, tags each record with PMM identity, and survives restarts and server outages without losing lines. PMM Server's own logs flow through the same path.

**Architecture:**
- pmm-managed stores log sources and parser presets in PostgreSQL. It builds a typed `OtelCollectorParams` for each collector and sends it in `SetStateRequest`.
- pmm-agent turns those params into collector YAML (typed structs, no templates). It enforces its local allow-list, drops privileges, runs the binary, and reports a status for each source.
- Built-in presets ship as embedded YAML and are upserted at startup.

**Tech Stack:** Go (pmm-managed, pmm-agent, pmm-admin), protobuf, reform/PostgreSQL, OpenTelemetry Collector (filelog, journald, otlphttp, file_storage), the stanza library (preset tests only, in a separate Go module).

**Spec:**
- [analysis](../spec.md): §3, §5 F1–F7, F9, F12, F14, §6.1, §6.2, §6.6, §6.7, decisions D3, D10, D11, D13;
- PMM-15572, PMM-15574 (backend), PMM-15575, PMM-15577 (client), PMM-15593 (scrape);
- the [roadmap](00-roadmap.md) for the shared names.

**Depends on:** plan 01, Tasks 1–4 (binary, users, schema, settings) and Task 9 (the `api/otel/v1` domain exists).

## Global Constraints

The roadmap's **Shared contract** and **Global constraints** apply. In addition:

**From PMM-15572:**
- The collector process runs as `pmm-agent`, never as root.
- No OTLP port is open in this plan; the node traces receiver comes in plan 05.
- Every record carries `pmm.node_id` and `pmm.agent_id`. Service-bound sources add `pmm.service_id` and `pmm.service_name`. App sources add `service.name`.
- A source bound to a service on another node is rejected.
- Checkpoints live in a persistent state dir, never in `paths.tempdir`.
- The disk-backed sending queue is 1024 MiB by default.
- Config is deterministic, and is pushed only to agents whose params changed.
- Files that contain credentials are 0600.
- An older pmm-agent gets `FailedPrecondition` on add, and is never sent the type.

**From PMM-15574:**
- Built-ins are read-only, and can be cloned.
- Custom presets allow only known operator types. `EXPR(` and environment expansion (`${`) are rejected.
- Every preset is validated with the bundled `otelcol validate`.
- Deleting a preset that is in use fails.
- A literal `{{` in a preset works.
- No credential can reach `otel.logs` through a preset.

## Review Focus

1. **A symlink under an allowed prefix that points outside it** (`/var/log/x -> /etc/shadow`). Expected: `NOT_ALLOWED`, because the allow-list checks the resolved path. Test in Task 6 (`TestRenderRejectsSymlinkEscape`).
2. **Globs and `..`** (`/var/log/../etc/*`, `/var/log/mysql/*.log`). Expected: a path containing `..` is rejected. A glob is checked on its static directory prefix. A file that a glob or a rotation pattern matches later, such as a symlink created in the log directory after the check, is checked when it is read: if it resolves outside the source's directory and the allow-list, its records keep only a fixed "blocked" body (ADR-08). Test in Task 6 (`TestAllowListGlobsAndDotDot`, `TestRenderGuardRoots`, `TestFilelogGuardBlocksSymlinkEscape`).
3. **Log lines of 64 KiB or more, or binary content.** Expected: each line is truncated at `max_log_size` (64 KiB), and every OTLP request stays under nginx's 10 MB limit, whatever the compression ratio. Test in Task 6 (`TestNodeCollectorRequestsStayUnder10MB`, with the real collector).
4. **Two collectors created concurrently for one pmm-agent** (two `pmm-admin add logs` at once). Expected: exactly one collector. The second request reuses it. Test in Task 3b (`TestAddLogSourceConcurrentCreatesOneCollector`, using the partial unique index).
5. **A log file rotated while the collector is down.** Expected, and documented as best-effort: with rename-and-create rotation, the rest of the renamed file is read from its checkpoint; lines written to the new file while the collector was down are skipped, because a file with no checkpoint starts at its end. With copy-and-truncate, lines written between the copy and the truncate can be lost. Test in Task 6 (`TestFilelogRotationWhileStopped`, with the real collector).

---

### Task 1: The `OTEL_COLLECTOR` agent type in inventory

**Files:**
- Modify:
  - `api/inventory/v1/agents.proto`:
    - enum `AGENT_TYPE_OTEL_COLLECTOR = 20` (:16-37);
    - message `OtelCollector`, following `NomadAgent` at :79-100;
    - `otel_collector` in `ListAgentsResponse` (:792-812), in the `GetAgentResponse` oneof (:821-842), and in `ChangeAgentRequest/Response` (:907-955), with `ChangeOtelCollectorParams { optional bool enable = 1; optional common.StringMap custom_labels = 2; }`;
    - no Add RPC: plan 02, Task 3b creates collectors.
  - `api/inventory/v1/agents.go` (sealed interface, :29,44-45)
  - `api/inventory/v1/types/agent_types.go` (:19-63)
  - `managed/models/agent_model.go` (:79-99, `OtelCollectorType`)
  - `managed/models/agentversion.go`: `PMMAgentMinVersionForOtelCollector`
  - `version/features.go`: `OtelCollectorSupportVersion`
  - `managed/models/database.go`: a migration with the next free number at merge time (126 on `main` at the pinned commit), `CREATE UNIQUE INDEX agents_one_otel_collector_per_pmm_agent ON agents (pmm_agent_id) WHERE agent_type = 'otel-collector'`
  - `managed/services/converters.go` (:580-588)
  - `managed/services/inventory/grpc/agents_server.go` (:44-60 enum map, `ListAgents` :71-128, Change :240-282)
  - `managed/services/inventory/agents.go` (`ChangeOtelCollector`, following `ChangeNomadAgent` :1774-1800)
  - `admin/commands/list.go` (:300-312, :556-620)
  - `admin/commands/inventory/list_agents.go` (:46,55,134-144,200,304)
  - `admin/commands/inventory/change_agent_otel_collector.go` (new, following `change_agent_nomad_agent.go`)
  - `managed/services/management/agent.go` (`agentToAPI` :141-240)
  - `api-tests/management/helpers.go` (`removeAllAgentsInList`, :125-170)
- Test:
  - `managed/services/converters_test.go`
  - `managed/models/agent_helpers_test.go` (`testdb`, because the unique index is migration behaviour)
  - `admin/commands/list_test.go`

**Interfaces:**
- Produces the version constants, both for `3.12.0-0`:
  - `models.PMMAgentMinVersionForOtelCollector = version.Must(version.NewVersion("3.12.0-0"))`, a hashicorp `*version.Version` next to the other `PMMAgentMinVersionFor…` values, because `models.PMMAgentSupported` (`managed/models/agentversion.go:48`) takes that type (Task 3b);
  - `version.OtelCollectorSupportVersion`, the shared-contract `FeatureVersion`, for `state.go` (Task 4).
- Produces the shared-contract enum, message and model constant, and `func (s *AgentsService) ChangeOtelCollector(ctx context.Context, agentID string, p *inventoryv1.ChangeOtelCollectorParams) (*inventoryv1.ChangeAgentResponse, error)`.

- [ ] **Step 1: Write the failing tests.**
  - `TestToAPIAgentOtelCollector`: a `models.Agent{AgentType: models.OtelCollectorType, ...}` converts to `*inventoryv1.OtelCollector` with every field.
  - `TestOneOtelCollectorPerPMMAgent` (`testdb.Open`): creating a second `otel-collector` agent for the same `pmm_agent_id` returns a unique-violation error. A collector for another pmm-agent succeeds.
  - `TestListShowsOtelCollector` in pmm-admin: the rendered list contains `otel_collector` and its status.
- [ ] **Step 2: Run them.** `make gen` (the protos fail first), then `go test ./managed/services/ ./managed/models/ ./admin/commands/ -run 'OtelCollector'`. Expected: FAIL.
- [ ] **Step 3: Implement** every file listed above. `AgentTypeName` panics on an unknown type (`types/agent_types.go:66-73`), so register the name.
- [ ] **Step 4: Run them again.** Same command, then `make prepare-pr`. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add api managed admin version api-tests/management/helpers.go
  git commit -s -m "PMM-15572 Add the OTEL collector agent type"
  ```

### Task 2: Built-in presets, the validator, and a preset test harness

**Files:**
- Create:
  - `managed/services/otel/presets/builtin/*.yml` for the generic presets `syslog`, `json`, `raw` and the hidden `journald` (`selectable: false`). Task 2b adds the database and server presets.
  - `managed/services/otel/presets/presets.go`
  - `managed/services/otel/presets/validate.go`
  - `managed/services/otel/presets/validate_test.go`
  - `managed/services/otel/presets/testdata/<name>/input.log`
  - `managed/services/otel/presets/testdata/<name>/expected.json`
  - `build/otelcol/presettest/go.mod`: a **separate module** that requires `github.com/open-telemetry/opentelemetry-collector-contrib/pkg/stanza` at `otelcol_version`
  - `build/otelcol/presettest/main_test.go`
- Modify: `.github/workflows/otelcol.yml` (run `go test ./...` in `build/otelcol/presettest`, and check that its stanza version equals `otelcol_version` in `build/scripts/vars`)

**Interfaces:**
- Produces:
  - File format:
    ```yaml
    name: mysql_error
    description: …
    min_agent_version: 3.12.0
    selectable: true
    operators: [ … ]
    ```
  - `type Preset struct { Name, Description, OperatorsYAML, MinAgentVersion string; Selectable bool }`
  - `func BuiltIn() ([]Preset, error)`, which reads the embed FS.
  - `type Validator interface { Validate(ctx context.Context, operatorsYAML string) error }`
  - `func NewValidator(otelcolPath string) Validator`. It runs `otelcol validate --config=<tmp>`, where the temp config has one filelog receiver carrying the operators and an `otlphttp` exporter to `http://127.0.0.1:1`.
  - `func CheckCustom(operatorsYAML string) error`, which checks structure and safety:
    - the YAML parses as a non-empty list of maps, each with a `type`;
    - `type` is one of `regex_parser`, `json_parser`, `csv_parser`, `key_value_parser`, `syslog_parser`, `time_parser`, `severity_parser`, `trace_parser`, `scope_name_parser`, `move`, `copy`, `remove`, `retain`, `flatten`, `add`, `recombine`, `noop`;
    - it rejects any string containing `EXPR(`, `${` or `env(`;
    - errors name the operator index and the offending value.
- Built-in fixes from PMM-15574 (applied in Task 2b):
  - `mysql_error` parses `log_timestamps=SYSTEM` offsets (`2026-10-10T12:00:00.123456+02:00`) as well as `Z`.
  - `postgres` parses a non-UTC `log_timezone` abbreviation.
  - Both use `recombine` so that a multi-line entry (an InnoDB deadlock dump, a stack trace) becomes one record.
  - `nginx_error` drops lines in the access-log format: a built-in may use a `filter` expression, a custom preset may not.
  - Built-ins pass `CheckCustom` except for the `filter`/`router` exemption, which `BuiltIn()` marks internally.

- [ ] **Step 1: Write the failing tests.**
  ```go
  func TestCheckCustomRejects(t *testing.T) {
      for name, y := range map[string]string{
          "unknown op":   "- type: router\n",
          "expr add":     "- type: add\n  field: body.x\n  value: EXPR(env(\"HOME\"))\n",
          "env expansion": "- type: add\n  field: body.x\n  value: ${env:PMM_AGENT_SERVER_PASSWORD}\n",
          "empty":        "",
      } {
          t.Run(name, func(t *testing.T) { require.Error(t, CheckCustom(y)) })
      }
  }

  func TestCheckCustomAcceptsLiteralBraces(t *testing.T) {
      require.NoError(t, CheckCustom("- type: add\n  field: body.x\n  value: '{{ .server_auth_b64 }}'\n"))
  }

  func TestBuiltInsLoad(t *testing.T) {
      ps, err := BuiltIn()
      require.NoError(t, err)
      var names []string
      for _, p := range ps { names = append(names, p.Name) }
      assert.ElementsMatch(t, []string{"syslog", "json", "raw", "journald"}, names)
  }
  ```
  In `build/otelcol/presettest/main_test.go`, `TestPresetsParseSamples`: for each `testdata/<name>/`, build a stanza pipeline from the preset's operators, feed `input.log` line by line, and compare `[]{timestamp(UTC RFC3339Nano), severity_text, body}` with `expected.json`. Write the samples from real logs. This task writes the syslog and JSON samples; Task 2b writes the rest:
  - MySQL 8.0 and 8.4 error logs, with both `log_timestamps` modes;
  - PostgreSQL 13–17 stderr logs with `log_timezone=Europe/Berlin`;
  - nginx access and error logs;
  - the Grafana console format;
  - logrus text for pmm-managed, pmm-agent, qan-api2 and vmproxy;
  - ClickHouse server logs;
  - supervisord logs;
  - VictoriaMetrics and vmalert logs, a Nomad hclog sample, and `pmm-init.log` Ansible output with a failed task;
  - RFC 3164 and 5424 syslog;
  - JSON with `ts`/`level`/`msg` and `timestamp`/`severity`/`message`.

  Each multi-line sample asserts one record.
- [ ] **Step 2: Run them.** `cd managed && go test ./services/otel/presets/` and `cd build/otelcol/presettest && go test ./...`. Expected: FAIL.
- [ ] **Step 3: Implement** the files, `presets.go` (`//go:embed builtin/*.yml`), `validate.go`, and the harness. Start from the prototype's operator chains (`git show origin/tibi-holmes:managed/models/database.go`, migrations 127–129 and 134), and correct them until the samples pass.
- [ ] **Step 4: Run them again.** Same commands. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add managed/services/otel/presets build/otelcol/presettest .github/workflows/otelcol.yml
  git commit -s -m "PMM-15574 Add the preset format, validator and harness"
  ```

### Task 2b: The database and server presets

**Files:**
- Create:
  - `managed/services/otel/presets/builtin/*.yml` for `mysql_error`, `syslog_mysql_systemd`, `nginx_access`, `nginx_error`, `grafana`, `pmm_managed`, `pmm_agent`, `postgres`, `clickhouse_server`, `otel_collector`, `supervisord`, `victoriametrics`, `hclog` and `ansible`
  - `managed/services/otel/presets/testdata/<name>/input.log` and `expected.json` for each of them
- Modify: `managed/services/otel/presets/validate_test.go` (`TestBuiltInsLoad`)

**Interfaces:**
- Consumes the file format, `BuiltIn`, `CheckCustom` and the harness (Task 2).
- Applies the built-in fixes from PMM-15574 listed in Task 2's Interfaces.
- `qan-api2.log` and `vmproxy.log` use `pmm_agent` (Task 8). If their samples don't parse under it, widen `pmm_agent` until they do; don't add a preset.

- [ ] **Step 1: Write the failing tests.** Extend `TestBuiltInsLoad` to the full list: `mysql_error`, `syslog_mysql_systemd`, `nginx_access`, `nginx_error`, `grafana`, `pmm_managed`, `pmm_agent`, `postgres`, `clickhouse_server`, `otel_collector`, `supervisord`, `syslog`, `json`, `raw`, `victoriametrics`, `hclog`, `ansible`, `journald`. Add the samples from Task 2's list that Task 2 didn't cover; each multi-line sample asserts one record.
- [ ] **Step 2: Run them.** `cd managed && go test ./services/otel/presets/` and `cd build/otelcol/presettest && go test ./...`. Expected: FAIL.
- [ ] **Step 3: Implement** the presets. Start from the prototype's operator chains (`git show origin/tibi-holmes:managed/models/database.go`, migrations 127–129 and 134), and correct them until the samples pass.
- [ ] **Step 4: Run them again.** Same commands. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add managed/services/otel/presets
  git commit -s -m "PMM-15574 Add database and server log presets"
  ```

### Task 3: Table `log_parser_presets` and the preset RPCs

**Files:**
- Create:
  - `managed/models/log_parser_preset_model.go`
  - `managed/models/log_parser_preset_helpers.go`
  - its `_reform.go` file (generated by `make gen`)
  - `managed/services/otel/presets_grpc.go`
  - their tests
  - `api-tests/otel/presets_test.go`
- Modify:
  - `managed/models/database.go`: a migration with the next free number at merge time (127 on `main` at the pinned commit, after Task 1's), creating `log_parser_presets (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', operators_yaml TEXT NOT NULL, built_in BOOLEAN NOT NULL DEFAULT FALSE, selectable BOOLEAN NOT NULL DEFAULT TRUE, min_agent_version VARCHAR NOT NULL DEFAULT '', cloned_from VARCHAR NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)`.
  - `api/otel/v1/otel.proto` (the preset RPCs from the roadmap table)
  - `managed/cmd/pmm-managed/main.go`: call `presets.BuiltIn()` at startup, convert each `presets.Preset` to `models.BuiltInPreset`, and upsert them through `models.SyncBuiltInPresets`.

**Interfaces:**
- Consumes `presets.BuiltIn`, `presets.CheckCustom` and the `presets.Validator` (Task 2).
- Produces:
  - `type BuiltInPreset struct { Name, Description, OperatorsYAML, MinAgentVersion string; Selectable bool }` in `models`, so `models` imports no service package.
  - `func SyncBuiltInPresets(q *reform.Querier, builtIns []BuiltInPreset) error`. It upserts each built-in by name. A custom preset with a clashing name is renamed to `<name>_custom`, and a warning is logged.
  - `func FindLogParserPresets(q *reform.Querier) ([]*LogParserPreset, error)`. Task 3b adds `UsageCount`.
  - `CreateLogParserPreset`, `ChangeLogParserPreset` and `RemoveLogParserPreset`:
    - change and remove of a built-in return `codes.FailedPrecondition` "built-in presets are read-only; clone it".

- [ ] **Step 1: Write the failing tests.**
  - `log_parser_preset_helpers_test.go` (`testdb.Open`):
    - `TestSyncBuiltInPresetsRenamesClash`: a custom `syslog` exists before sync; afterwards the custom one is `syslog_custom`, keeps its id, and the built-in `syslog` exists.
    - `TestChangeBuiltInFails`.
- [ ] **Step 2: Run them.** `cd managed && go test ./models/ ./services/otel/ -run 'Preset'`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, the migration, the helpers, the proto (then `make gen`), the handlers and the startup sync.
- [ ] **Step 4: Run them again.** Same command, then `make prepare-pr`. Expected: PASS. Then write the api-test against a Feature Build: the list contains every selectable built-in in `presets.BuiltIn()`; add, change and clone a custom preset; changing a built-in gets 400; invalid YAML gets 400 with a clear message; a Viewer gets 403.
- [ ] **Step 5: Commit.**
  ```bash
  git add api/otel managed api-tests/otel
  git commit -s -m "PMM-15574 Add the parser presets API"
  ```

### Task 3b: Table `log_sources` and the log source RPCs

**Files:**
- Create:
  - `managed/models/log_source_model.go`
  - `managed/models/log_source_helpers.go`
  - its `_reform.go` file (generated by `make gen`)
  - `managed/services/otel/log_sources_grpc.go`
  - their tests
  - `api-tests/otel/log_sources_test.go`
- Modify:
  - `managed/models/database.go`: a migration with the next free number after Task 3's (128 on `main` at the pinned commit), creating `log_sources` as described in analysis §6.2. `units` and `custom_labels` are stored like `agents.custom_labels`. `state` holds the proto enum name (`LOG_SOURCE_STATE_COLLECTING`, …), and `state_reason` the agent's text.
  - `api/otel/v1/otel.proto` (the log source RPCs from the roadmap table)

**Interfaces:**
- Consumes `models.OtelCollectorType` and `models.PMMAgentMinVersionForOtelCollector` (Task 1), and the preset table (Task 3).
- Produces:
  - `func UpsertLogSource(q *reform.Querier, p UpsertLogSourceParams) (*LogSource, bool, error)` (the bool means "created"), with `UpsertLogSourceParams{ PMMAgentID string; Kind string; Path string; Units []string; PresetName string; ServiceID string; AppName string; Discovery string; CustomLabels map[string]string }`.
    - It creates the collector agent when the pmm-agent has none.
    - It rejects a `ServiceID` whose `node_id` differs from the pmm-agent's `runs_on_node_id` with `InvalidArgument` "service %s runs on node %s, not on this node".
    - It rejects an unknown preset with `NotFound` naming it.
    - It rejects `ServiceID` and `AppName` together with `InvalidArgument`.
    - Adding the same `(collector, kind, path, units)` again updates the row, so the last preset wins.
  - `func RemoveLogSources(q *reform.Querier, f LogSourceFilters) (int, error)` and `func FindLogSources(q *reform.Querier, f LogSourceFilters) ([]*LogSource, error)`, with `LogSourceFilters{ID, NodeID, PMMAgentID, ServiceID, Path string}`.
  - Removing a service deletes its sources through the foreign key.
  - `FindLogParserPresets` gains `UsageCount`, a `COUNT` over `log_sources`; removing a preset in use returns `FailedPrecondition` with the count.
  - **Preset changes** call `RequestStateUpdate` for each pmm-agent whose collector uses the preset (`SELECT DISTINCT pmm_agent_id …`), and for no other agent.
  - **gRPC:**
    - `AddLogSourceRequest` takes exactly one of `pmm_agent_id` (pmm-admin) or `node_id` (UI). A `node_id` resolves to the pmm-agent whose `runs_on_node_id` is that node; if there is none, the request fails with `FailedPrecondition` "node %s has no pmm-agent".
    - The handlers call `models.PMMAgentSupported(q, pmmAgentID, "OpenTelemetry log collection", models.PMMAgentMinVersionForOtelCollector)` before any write, and map the result to `FailedPrecondition`.
    - After the transaction they call `state.RequestStateUpdate(ctx, pmmAgentID)` for that pmm-agent only.

- [ ] **Step 1: Write the failing tests.**
  - `log_source_helpers_test.go` (`testdb.Open`, because the tests cover foreign keys, unique and check constraints):
    - `TestUpsertLogSourceOwners`: a file source, a journald source, an app source and a service-bound source on one node give one collector agent, with 4 rows and the right owner columns.
    - `TestUpsertLogSourceLastPresetWins`.
    - `TestUpsertLogSourceRejectsForeignService`, asserting that the error contains both node ids.
    - `TestUpsertLogSourceRejectsServiceAndApp`.
    - `TestRemoveServiceRemovesItsSources`.
    - `TestAddLogSourceConcurrentCreatesOneCollector`: two goroutines with `sync.WaitGroup.Go`, each in its own transaction, give one collector.
    - `TestRemovePresetInUseFails` (in `log_parser_preset_helpers_test.go`).
  - `presets_grpc_test.go`, with mocks for `Validator` and the state updater: `TestChangePresetPushesOnlyUsers` asserts that `RequestStateUpdate` is called for agent A, which uses the preset, and not for agent B.
- [ ] **Step 2: Run them.** `cd managed && go test ./models/ ./services/otel/ -run 'LogSource|Preset'`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, the migration, the helpers, the proto (then `make gen`) and the handlers.
- [ ] **Step 4: Run them again.** Same command, then `make prepare-pr`. Expected: PASS. Then the api-test against a Feature Build (connect a pmm-agent from `api-tests` setup, or use the server's own node): add, list and remove a source; an unknown preset gets 404 naming it; removing a preset in use gets 400; a Viewer gets 403.
- [ ] **Step 5: Commit.**
  ```bash
  git add api/otel managed api-tests/otel
  git commit -s -m "PMM-15572 Add the log sources API"
  ```

### Task 4: Build `OtelCollectorParams` in pmm-managed

**Files:**
- Create:
  - `api/agent/v1/otel.proto` (the messages from the roadmap)
  - `managed/services/agents/otelcollector.go`
  - `managed/services/agents/otelcollector_test.go`
- Modify:
  - `api/agent/v1/agent.proto`: `AgentProcess.otel_collector = 9`, `StateChangedRequest.log_source_statuses = 6`
  - `managed/services/agents/state.go`:
    - a `case models.OtelCollectorType` in `sendSetStateRequest` (~:281-290), skipped with a warning for agents below the version (pattern at :304-309);
    - in `AgentFilters`, `IgnoreOtelCollector: !settings.IsOtelCollectorEnabled()` (pattern `IgnoreNomad` ~:225; filter field at `agent_helpers.go:244-262,345`).

**Interfaces:**
- Consumes `models.FindLogSources` (Task 3b), `FindLogParserPresets` (Task 3), `version.OtelCollectorSupportVersion` (Task 1), and `models.MergeLabels`.
- Produces `func otelCollectorConfig(agent *models.Agent, node *models.Node, sources []*models.LogSource, presetsByID map[string]*models.LogParserPreset, services map[string]*models.Service, isServerNode bool, pmmAgentVersion *version.Parsed) *agentv1.SetStateRequest_AgentProcess`. It returns:
  - `Type: AGENT_TYPE_OTEL_COLLECTOR`;
  - `OtelCollector.ResourceAttributes = {"pmm.node_id", "pmm.agent_id"}`;
  - for each source:
    - `Id = log_sources.id`, `Kind`, `Path`, `Units`;
    - `OperatorsYaml` = the preset's operators. A journald source uses the hidden `journald` preset.
    - `ResourceAttributes`: for a service source, `pmm.service_id` and `pmm.service_name`, plus `service.name` set to the program (`mysqld`, `postgres`, `mongod`, by service type; D4). For an app source, `service.name = app_name`. Then the source's custom labels.
    - `Discovered = discovery != ""`.
  - A source whose preset has `MinAgentVersion` above the pmm-agent version is left out, and its `state` is set to `LOG_SOURCE_STATE_AGENT_TOO_OLD`.
  - `SendToLocalReceiver = isServerNode`, `SendingQueueMib = 1024`.
  - Sources are sorted by id, and map keys are sorted on marshal, so equal input always gives an equal message.
  - `Args` and `TextFiles` are empty: pmm-agent renders the config itself (D11).

- [ ] **Step 1: Write the failing tests.**
  ```go
  func TestOtelCollectorConfigIdentity(t *testing.T) {
      p := otelCollectorConfig(collector, node, []*models.LogSource{svcSource, appSource, osSource}, presets, services, false, v3_12)
      require.Len(t, p.OtelCollector.LogSources, 3)
      assert.Equal(t, map[string]string{"pmm.node_id": node.NodeID, "pmm.agent_id": collector.AgentID}, p.OtelCollector.ResourceAttributes)
      assert.Equal(t, map[string]string{"pmm.service_id": "svc1", "pmm.service_name": "mysql-1", "service.name": "mysqld"}, byID(p, "src-svc").ResourceAttributes)
      assert.Equal(t, map[string]string{"service.name": "billing"}, byID(p, "src-app").ResourceAttributes)
      assert.Empty(t, byID(p, "src-os").ResourceAttributes)
      assert.Empty(t, p.Args)
      assert.Empty(t, p.TextFiles)
  }

  func TestOtelCollectorConfigDeterministic(t *testing.T) {
      a := otelCollectorConfig(collector, node, shuffled(sources), presets, services, false, v3_12)
      b := otelCollectorConfig(collector, node, sources, presets, services, false, v3_12)
      assert.True(t, proto.Equal(a, b))
  }
  ```
  Add `TestSendSetStateWithholdsOtelFromOldAgent`: with a pmm-agent at 3.10.0, the request has no `otel-collector` process. Add `TestSendSetStateIgnoresOtelWhenDisabled`.
- [ ] **Step 2: Run them.** `make gen && cd managed && go test ./services/agents/ -run Otel`. Expected: FAIL.
- [ ] **Step 3: Implement** `otelCollectorConfig` and the `state.go` changes.
- [ ] **Step 4: Run them again.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add api/agent version managed/services/agents managed/models
  git commit -s -m "PMM-15572 Send typed collector params to pmm-agent"
  ```

### Task 5: pmm-agent config: binary path, data dir, allow-list

**Files:**
- Modify:
  - `agent/config/config.go`:
    - `Paths.OtelCollector` and `Paths.OtelCollectorDataDir` (:112-136);
    - defaults in `applyDefaults` (`tools/otelcol` via the tools branch at :315-326; `<paths_base>/data/otelcol` like `NomadDataDir` at :304-307);
    - `clearDerivedPaths` (:434-466);
    - Kingpin flags with `PMM_AGENT_*` env vars (:517-548);
    - new `type LogSources struct { AllowedPaths []string \`yaml:"allowed-paths"\`; AllowedJournaldUnits []string \`yaml:"allowed-journald-units"\` }`, added to `Config` as `LogSources LogSources \`yaml:"log-sources"\``. The default is `AllowedPaths = ["/var/log"]` when the key is absent; an explicit empty list stays empty.
  - `agent/config/config_test.go`
  - `managed/services/supervisord/pmm_config.go` (:180-192): add `--paths-otelcol-data-dir=/srv/otelcol/data --log-sources-allowed-paths=/srv/logs` to the server's `[program:pmm-agent]` command, and update the golden `managed/testdata/supervisord.d/pmm.ini`.

**Interfaces:**
- Produces `cfg.Paths.OtelCollector`, `cfg.Paths.OtelCollectorDataDir` and `cfg.LogSources`. Task 6 reads them.

- [ ] **Step 1: Write the failing tests.**
  - `TestLoadDefaultsOtel`: an empty config file gives `Paths.OtelCollector == "/usr/local/percona/pmm/tools/otelcol"`, `OtelCollectorDataDir == "/usr/local/percona/pmm/data/otelcol"`, and `LogSources.AllowedPaths == []string{"/var/log"}`.
  - `TestLoadKeepsAllowListAcrossSave`: load a file with `allowed-paths: [/var/log, /opt/app/logs]`, call `SaveToFile`, reload, and get the same list. This is the upgrade-survival AC from PMM-15577.
  - `TestEnvAllowList`: `PMM_AGENT_LOG_SOURCES_ALLOWED_PATHS=/srv/logs` gives `[]string{"/srv/logs"}`.
- [ ] **Step 2: Run them.** `cd agent && go test ./config/ -run 'Otel|AllowList'`. Expected: FAIL.
- [ ] **Step 3: Implement** the fields, defaults and flags, then the server program flags. pmm-agent creates `/srv/otelcol/data` itself (Task 7).
- [ ] **Step 4: Run them again.** Same command, plus `cd managed && go test ./services/supervisord/`. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add agent/config managed/services/supervisord managed/testdata
  git commit -s -m "PMM-15572 Add collector paths and log allow-list"
  ```

### Task 6: Render the collector config on pmm-agent

**Files:**
- Create:
  - `agent/agents/otelcollector/render.go`
  - `agent/agents/otelcollector/allowlist.go`
  - `agent/agents/otelcollector/render_test.go`
  - `agent/agents/otelcollector/allowlist_test.go`
  - `agent/agents/otelcollector/testdata/*.golden.yaml`

**Interfaces:**
- Consumes `agentv1.OtelCollectorParams` (Task 4) and `config.LogSources` (Task 5).
- Produces:
  - `type RenderInput struct { ServerURL *url.URL; Username, Password string; InsecureTLS bool; DataDir string; TelemetryPort uint16; AllowedPaths, AllowedUnits []string; Readable func(path string) error; JournalctlAvailable bool; DiscoveredPaths, DiscoveredUnits map[string]bool }`. Plan 04 fills `DiscoveredPaths` and `DiscoveredUnits`; they are nil here.
  - `func Render(p *agentv1.OtelCollectorParams, in RenderInput) (yaml []byte, statuses []*agentv1.LogSourceStatus, err error)`
  - `func CheckAllowed(path string, allowed []string) error`. It cleans the path, rejects a path that is not absolute or contains `..`, resolves symlinks with `filepath.EvalSymlinks` when the path exists, checks the static prefix of a glob, and requires a resolved prefix to be under one of the `allowed` entries.
- Rendering rules (D11):
  - **One pipeline per accepted source,** `logs/<id>`: receivers `[filelog/<id>]` or `[journald/<id>]`, processors `[memory_limiter, resource/pmm, resource/<id>, batch]`, with `transform/guard-<id>` after `memory_limiter` for a file source, exporters `[otlphttp]`.
  - **`filelog/<id>`:** `include: [path, path + ".*", path + "-*"]`, which match rotated names such as `error.log.1`, `mysqld.log-20261109` and `mongod.log.2026-11-09T00-00-00`; `exclude: [path + "*.gz", path + "*.xz", path + "*.bz2", path + "*.zst"]` (a renamed file keeps being read from its checkpoint; compressed rotations are skipped), `include_file_path: true`, `include_file_path_resolved: true`, `start_at: end`, `storage: file_storage`, `max_log_size: 65536`, `operators` = the parsed `OperatorsYaml`.
  - **`journald/<id>`:** `units`, `start_at: end`, `storage: file_storage`, `operators`.
  - **`transform/guard-<id>`** (file sources only), `log_statements` with context `log`, both under the condition `not IsMatch(attributes["log.file.path_resolved"], "<roots>")`: `keep_keys(attributes, ["log.file.path", "log.file.path_resolved"])`, then `set(body, "[blocked by pmm-agent: the file resolves outside the allowed directories]")`.
    - `<roots>` is `^(` + each allowed root through `regexp.QuoteMeta`, joined with `|`, + `)/`. A discovered source has one root: the resolved directory of its path. Any other source has the resolved allow-list entries.
    - It covers files that the collector opens after `CheckAllowed` ran: a glob or a rotation pattern can match a symlink created later (ADR-08 resolves symlinks before the check).
    - Check that the pinned filelog receiver supports `include_file_path_resolved`, and record the result.
  - **`resource/pmm` and `resource/<id>`:** `actions` with `upsert` for each attribute.
  - **`memory_limiter`:** `check_interval: 1s`, `limit_mib: 128`.
  - **Request size:** batches are bounded by bytes, not only by count. If the pinned collector's exporter supports a byte limit on its batches (the exporterhelper `sizer: bytes`), set it to 8 MiB; check this against the pinned release and record the choice. Otherwise use the `batch` processor with `timeout: 5s`, `send_batch_size: 128`, `send_batch_max_size: 128`: 128 × 64 KiB is 8 MiB of bodies, under nginx's 10 MB limit before compression.
  - **`otlphttp`:**
    - `endpoint`: `http://127.0.0.1:4318` when `SendToLocalReceiver`, otherwise `<ServerURL>/otlp`;
    - `headers.Authorization`: `Basic base64(user:pass)`, and only when not local;
    - `tls.insecure_skip_verify: InsecureTLS`, `compression: gzip`;
    - `retry_on_failure: {enabled: true, initial_interval: 5s, max_interval: 30s, max_elapsed_time: 0}`;
    - `sending_queue: {enabled: true, storage: file_storage, sizer: bytes, queue_size: SendingQueueMib·2²⁰}`. Check that the pinned collector supports the `bytes` sizer; if it doesn't, use `sizer: requests` with `queue_size: 5000`, and record the choice.
  - **`extensions.file_storage`:** `directory: <DataDir>/storage`, `create_directory: true`, `compaction.on_start: true`.
  - **`service.telemetry.metrics`:** a pull reader on `127.0.0.1:<TelemetryPort>`.
  - **No `receivers.otlp`.**
  - **Escaping:** every string that comes from params or credentials has `$` replaced with `$$` before marshalling.
  - **Statuses:** a file source outside the allow-list gives `NOT_ALLOWED`, unless `DiscoveredPaths[path]`. `Readable(path)` failing gives `NOT_READABLE` or `NOT_FOUND`. A journald source gives `JOURNALD_UNAVAILABLE` when `journalctl` is unavailable, and `NOT_ALLOWED` when a unit is in neither `AllowedUnits` nor `DiscoveredUnits`. An accepted source gives `COLLECTING`.
  - **No accepted sources:** the config still renders with no pipelines, and the caller (Task 7) doesn't start the process.

- [ ] **Step 1: Write the failing tests.**
  ```go
  func TestRenderGolden(t *testing.T) { /* params with one file, one journald, one app source; compare with testdata/mixed.golden.yaml */ }

  func TestRenderRejectsSymlinkEscape(t *testing.T) {
      dir := t.TempDir()
      require.NoError(t, os.Symlink("/etc/hostname", filepath.Join(dir, "x.log")))
      _, st, err := Render(paramsWithFile(filepath.Join(dir, "x.log")), RenderInput{AllowedPaths: []string{dir}, Readable: okReadable})
      require.NoError(t, err)
      assert.Equal(t, agentv1.LogSourceState_LOG_SOURCE_STATE_NOT_ALLOWED, st[0].State)
  }

  func TestAllowListGlobsAndDotDot(t *testing.T) {
      require.NoError(t, CheckAllowed("/var/log/mysql/*.log", []string{"/var/log"}))
      require.Error(t, CheckAllowed("/var/log/../etc/shadow", []string{"/var/log"}))
      require.Error(t, CheckAllowed("relative/path.log", []string{"/var/log"}))
      require.Error(t, CheckAllowed("/var/logs-other/x.log", []string{"/var/log"}))
  }

  func TestRenderEscapesDollarAndKeepsBraces(t *testing.T) {
      y, _, err := Render(paramsWithOperators("- type: add\n  field: body.x\n  value: '{{ .server_auth_b64 }} $HOME'\n"), RenderInput{Password: "pa$$word", /* … */})
      require.NoError(t, err)
      assert.Contains(t, string(y), "{{ .server_auth_b64 }} $$HOME")
      assert.NotContains(t, string(y), "server_password")
  }

  // Real collector: skipped unless PMM_OTEL_CONTRACT_BINARY is set, as in plan 01, Task 8.
  func TestNodeCollectorRequestsStayUnder10MB(t *testing.T) { /* render a config for one file source, point otlphttp at an httptest server that records each request's body size and answers 413 above 10,000,000 bytes; write 2,000 lines of 64 KiB random (incompressible) bytes; assert every request < 10,000,000 bytes, no 413, and all 2,000 lines received */ }
  func TestRenderedFilelogUsesStorageAndStartAtEnd(t *testing.T) { /* assert storage, start_at, include_file_path, include_file_path_resolved, the .* and -* rotation patterns and the compressed excludes */ }
  func TestRenderGuardRoots(t *testing.T) { /* a discovered source's guard has only its resolved directory as root; a manual source's has the resolved allow-list; a journald source has no guard */ }
  // Real collector, skipped unless PMM_OTEL_CONTRACT_BINARY is set.
  func TestFilelogGuardBlocksSymlinkEscape(t *testing.T) { /* dir A holds x.log, dir B holds secret.log; start the collector on A/x.log; create A/x.log.1 -> B/secret.log and append lines to secret.log; assert no secret line reaches the httptest server, and those records carry the blocked body */ }
  // Real collector, skipped unless PMM_OTEL_CONTRACT_BINARY is set.
  func TestFilelogRotationWhileStopped(t *testing.T) { /* subtests rename-create and copy-truncate: write lines A, stop the collector, write lines B, rotate, write lines C, start it; assert A and B arrive once each for rename-create, C is skipped, nothing arrives twice; for copy-truncate assert no duplicates and record what is lost */ }
  func TestRenderLocalReceiverHasNoAuth(t *testing.T) { /* SendToLocalReceiver: endpoint 127.0.0.1:4318, no Authorization header */ }
  func TestRenderHasNoOTLPReceiver(t *testing.T) { /* receivers has no key "otlp" */ }
  ```
- [ ] **Step 2: Run them.** `cd agent && go test ./agents/otelcollector/`. Expected: FAIL.
- [ ] **Step 3: Implement `Render` and `CheckAllowed`.** Model each config section as a struct; parse operators into `[]yaml.Node`, so they are embedded without re-serialising through `map[string]any`.
- [ ] **Step 4: Run them again.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add agent/agents/otelcollector
  git commit -s -m "PMM-15572 Render collector config on pmm-agent"
  ```

### Task 7: Run the collector as `pmm-agent`

**Files:**
- Create:
  - `agent/agents/otelcollector/credential.go`
  - `agent/agents/otelcollector/credential_test.go`
  - `agent/agents/otelcollector/readable.go`
- Modify:
  - `agent/agents/process/process.go`:
    - a `Credential *syscall.Credential` field in `Params` (:75-87);
    - in `toStarting` (:150-178), set `p.cmd.SysProcAttr.Credential` **after** `pdeathsig.Set`, so `Pdeathsig` is kept.
  - `agent/agents/supervisor/supervisor.go`:
    - a `case inventoryv1.AgentType_AGENT_TYPE_OTEL_COLLECTOR` in `processParams` (:1118-1219). It creates each missing directory down to `OtelCollectorDataDir` with mode 0755, then `<agentID>` with mode 0700, owned by the credential. Not one `os.MkdirAll` with 0700: it gives every level it creates the same mode, so a root pmm-agent would leave `data/otelcol` as root:root 0700, and the collector, running as `pmm-agent`, couldn't reach its config. The packages don't create `/usr/local/percona/pmm/data`. If an existing parent isn't searchable by the credential, the agent status is `INITIALIZATION_ERROR`, naming that directory. Then it calls `Render`, writes the YAML to `config.yaml` there with mode 0600, chowns that directory tree to the credential, and sets `Path = cfg.Paths.OtelCollector`, `Args = ["--config=<file>"]`, `Env = ["PATH=/usr/bin:/bin"]` and `Credential`;
    - it assigns `RenderInput.TelemetryPort` from the supervisor's port range, the way exporters get theirs, and reports it as the agent's `listen_port` (Task 9 scrapes it);
    - `version()` (:1262-1283) with a regex for `otelcol version`, in `deps.go:26`.
  - `build/packages/rpm/client/pmm-client.spec` and `build/packages/deb/postinst`: after the user is created, `usermod -aG systemd-journal pmm-agent` when `getent group systemd-journal` succeeds, and `-aG adm` on Debian/Ubuntu when `adm` exists.

**Interfaces:**
- Consumes `Render` (Task 6) and `config.Paths` and `LogSources` (Task 5).
- Produces:
  - `func CollectorCredential(euid int, lookup func(string) (*user.User, error), groupIDs func(*user.User) ([]string, error)) (*syscall.Credential, error)`. It returns `nil, nil` when `euid != 0`. As root, it returns the `pmm-agent` uid, gid and supplementary groups. If the user is missing, it returns an error, which becomes the agent status `INITIALIZATION_ERROR` with the message "user pmm-agent not found; the collector does not run as root".
  - `func ReadableAs(cred *syscall.Credential) func(path string) error`. It checks the owner, group and other read bits on the file (or, for a glob, its directory), and the execute bit on each parent directory. When the file or a parent has a `system.posix_acl_access` xattr, the check is skipped.

- [ ] **Step 1: Write the failing tests.**
  ```go
  func TestCollectorCredential(t *testing.T) {
      lookup := func(string) (*user.User, error) { return &user.User{Uid: "998", Gid: "997", Username: "pmm-agent"}, nil }
      groups := func(*user.User) ([]string, error) { return []string{"997", "4", "190"}, nil }
      c, err := CollectorCredential(0, lookup, groups)
      require.NoError(t, err)
      assert.Equal(t, &syscall.Credential{Uid: 998, Gid: 997, Groups: []uint32{997, 4, 190}}, c)

      c, err = CollectorCredential(1002, lookup, groups)
      require.NoError(t, err)
      assert.Nil(t, c)

      _, err = CollectorCredential(0, func(string) (*user.User, error) { return nil, user.UnknownUserError("pmm-agent") }, groups)
      require.ErrorContains(t, err, "does not run as root")
  }
  ```
  Also write:
  - `TestReadableAs`, on temp files with modes 0600, 0640 and 0644 and a fake credential.
  - `TestProcessParamsOtelCollectorUnsearchableParent`: an existing `OtelCollectorDataDir` with mode 0700, owned by another user, gives `INITIALIZATION_ERROR` naming it.
  - In the supervisor tests, `TestProcessParamsOtelCollector`: the data directory is created, every directory above the config file has mode 0755 (searchable by the collector's uid) and the `<agentID>` directory 0700, the config file exists with mode 0600, `Args[0]` starts with `--config=`, `Env` is `["PATH=/usr/bin:/bin"]`, and the rendered config's telemetry endpoint uses the assigned port.
- [ ] **Step 2: Run them.** `cd agent && go test ./agents/otelcollector/ ./agents/supervisor/ ./agents/process/`. Expected: FAIL.
- [ ] **Step 3: Implement** everything listed above, including the package scripts.
- [ ] **Step 4: Run them again.** Same command, then `make prepare-pr`. Expected: PASS. Then on a CHAOS VM with a Feature Build (`pmm-qa:chaos-docker-provisioning`):
  - `ps -o user= -C otelcol` prints `pmm-agent`.
  - `ss -ltnp | grep otelcol` shows only `127.0.0.1:<listen_port>`.
- [ ] **Step 5: Commit.**
  ```bash
  git add agent build/packages
  git commit -s -m "PMM-15572 Run the collector as pmm-agent"
  ```

### Task 7b: Report a state for each log source

**Files:**
- Modify:
  - `agent/agents/supervisor/supervisor.go`: keep the statuses `Render` returns on the agent's process info, and send `StateChangedRequest.LogSourceStatuses` together with the process status (:833), and again whenever the statuses change.
  - `managed/services/agents/handler.go` (`stateChanged` ~:129,223): convert each `agentv1.LogSourceStatus` to `models.LogSourceStateUpdate` and store them with `models.UpdateLogSourceStates`.
  - `managed/models/log_source_helpers.go`

**Interfaces:**
- Consumes `Render`'s statuses (Task 6) and the `log_sources` table (Task 3b).
- Produces:
  - `type LogSourceStateUpdate struct { ID, State, Reason string }` in `models`, so `models` doesn't import `api/agent`.
  - `func UpdateLogSourceStates(q *reform.Querier, updates []LogSourceStateUpdate) error`. `State` is the proto enum name.

- [ ] **Step 1: Write the failing tests.**
  - In `agent/agents/supervisor`, `TestSupervisorSendsLogSourceStatusesOnChange`: a changed status list produces a `StateChangedRequest` with the new statuses; an unchanged list produces none.
  - In `managed/services/agents`, `TestStateChangedStoresLogSourceStates` (sqlmock): the expected UPDATE on `log_sources` sets `state` and `state_reason` for the given id.
- [ ] **Step 2: Run them.** `cd agent && go test ./agents/supervisor/ -run LogSourceStatuses` and `cd managed && go test ./services/agents/ -run StateChanged`. Expected: FAIL.
- [ ] **Step 3: Implement** the sending, the conversion and the helper.
- [ ] **Step 4: Run them again.** Same commands, then `make prepare-pr`. Expected: PASS. Then on the Task 7 VM, add a source with a path outside `/var/log`; `GET /v1/otel/log-sources` shows `LOG_SOURCE_STATE_NOT_ALLOWED`.
- [ ] **Step 5: Commit.**
  ```bash
  git add agent managed
  git commit -s -m "PMM-15572 Report a state for each log source"
  ```

### Task 8: PMM Server's own logs

**Files:**
- Create:
  - `managed/services/otel/server_sources.go`
  - `managed/services/otel/server_sources_test.go`
- Modify:
  - `managed/services/agents/registry.go`: in `authenticate` (~:353-405), call `ensureServerOtelCollector` for the server's pmm-agent (`models.PMMServerAgentID`, or the HA UUID) on every connect, whatever the OTEL setting, as `addNomadAgentToPMMAgent` (:526-545) does for Nomad. Task 4's `IgnoreOtelCollector` withholds the collector while OTEL is off, so turning OTEL on at runtime only needs a state push, not a reconnect (ADR-25).

**Interfaces:**
- Consumes `models.UpsertLogSource` (Task 3b) and `SendToLocalReceiver` (Task 4).
- Produces:
  - `type ServerSource struct { File, Preset, App, ServiceID string; When func(ServerEnv) bool }`
  - `type ServerEnv struct { BuiltinPostgres, BuiltinClickHouse, InternalVictoriaMetrics, NomadEnabled bool }`. It is read from `PMM_DISABLE_BUILTIN_POSTGRES` (`managed/cmd/pmm-managed-init/main.go:74`), `PMM_DISABLE_BUILTIN_CLICKHOUSE`, `VMParams.ExternalVM()` and `settings.IsNomadEnabled()`.
  - `func DefaultServerSources(env ServerEnv) []ServerSource`. It covers **every** log file PMM Server writes to `/srv/logs`. There are 14; PMM-15575 lists 10:

    | File | Preset | `service.name` | Collected when |
    |---|---|---|---|
    | `nginx.log` | `nginx_error`, which drops access lines (PMM-15575) | `nginx` | always |
    | `grafana.log` | `grafana` | `grafana` | always |
    | `pmm-managed.log` | `pmm_managed` | `pmm-managed` | always |
    | `pmm-agent.log` | `pmm_agent` | `pmm-agent` | always |
    | `pmm-init.log` | `ansible` (new; it holds `ansible-playbook` output, `pmm_config.go:88`) | `pmm-init` | always |
    | `supervisord.log` | `supervisord` | `supervisord` | always |
    | `qan-api2.log` | `pmm_agent` | `qan-api2` | always |
    | `vmproxy.log` | same as `qan-api2.log` | `vmproxy` | always |
    | `vmalert.log` | `victoriametrics` (new) | `vmalert` | always |
    | `otel-collector.log` | `otel_collector` | `otel-collector` | always |
    | `postgresql.log` | `postgres` | — (bound to the `pmm-server-postgresql` service) | built-in PostgreSQL |
    | `clickhouse-server.log` | `clickhouse_server` | `clickhouse` | built-in ClickHouse |
    | `victoriametrics.log` | `victoriametrics` (new) | `victoriametrics` | internal VictoriaMetrics |
    | `nomad-server.log` | `hclog` (new) | `nomad` | Nomad enabled |

    The real file is `postgresql.log`. PostgreSQL 18 writes to stdout and supervisord stores it there (`pmm_config.go:106-128`), so PMM-15575's `postgresql14.log` is stale.
  - Each source includes `<file>*`, not just `<file>`. supervisord rotates by renaming `x.log` to `x.log.1`, and the glob lets the collector finish lines written just before a rotation. `file_storage` fingerprints stop it from reading a rotated copy twice.
  - New built-in presets in Task 2b:
    - `victoriametrics`: tab-separated, `2026-10-11T10:00:00.000Z<TAB>info<TAB>caller<TAB>message`;
    - `hclog`: `2026-10-11T10:00:00.000Z [INFO]  nomad: message`;
    - `ansible`: `recombine` on `PLAY [`, `TASK [` and `PLAY RECAP`; severity from `fatal:` / `failed:` (error), `changed:` / `ok:` (info).
  - `func (r *Registry) ensureServerOtelCollector(q *reform.Querier, pmmAgentID string, v *version.Parsed) error`. It is idempotent: it upserts the sources whose `When` holds, and removes the default sources whose `When` no longer holds, for example after Nomad is turned off.
  - To collect nginx access lines, an admin changes that source's preset to `nginx_access` through the API or the UI.

- [ ] **Step 1: Write the failing tests.**
  - `TestServerSourcesCoverEveryShippedLog`. It collects every `stdout_logfile = /srv/logs/<name>.log`, and supervisord's own `logfile = /srv/logs/<name>.log`, from:
    - the templates in `managed/services/supervisord/pmm_config.go` and `supervisord.go`;
    - `build/ansible/roles/supervisord/files/*.ini`;

    and asserts each is in `DefaultServerSources` with every `ServerEnv` flag on, and that every listed file is shipped. A new program that logs to `/srv/logs` without a source then fails CI.
  - `TestServerSourcesFollowEnv`: with built-in PostgreSQL and ClickHouse off and external VictoriaMetrics (the HA case), the list has no `postgresql.log`, `clickhouse-server.log` or `victoriametrics.log`. Nomad off means no `nomad-server.log`.
  - `TestEnableOtelPushesServerCollectorWithoutReconnect`: the server's pmm-agent connects with OTEL off, so the collector and its sources exist but `sendSetStateRequest` leaves the collector out; after OTEL is turned on, the next state update for that pmm-agent includes the `otel-collector` process.
  - `TestEnsureServerOtelCollectorIdempotent` (`testdb`): calling it twice gives one collector and 13 sources (Nomad off).
- [ ] **Step 2: Run them.** `cd managed && go test ./services/otel/ ./services/agents/ -run 'ServerSources|EnsureServerOtel'`. Expected: FAIL.
- [ ] **Step 3: Implement** the source list and the ensure hook.
- [ ] **Step 4: Run them again.** Same command. Expected: PASS. Then on a Feature Build, after 2 minutes:
  ```bash
  docker exec pmm-server clickhouse-client -q "SELECT ServiceName, count() FROM otel.logs WHERE Timestamp > now() - INTERVAL 10 MINUTE GROUP BY 1"
  ```
  Expect one row per component, no nginx access lines, and a `SeverityText` set on each row.
- [ ] **Step 5: Commit.**
  ```bash
  git add managed/services/otel managed/services/agents/registry.go
  git commit -s -m "PMM-15575 Collect PMM Server's own logs"
  ```

### Task 9: Collector self-metrics into VictoriaMetrics

**Files:**
- Modify:
  - `managed/services/victoriametrics/prometheus.go`: a scrape config for `models.OtelCollectorType` in the agent switch (~:285-296), job `otel-collector`, target `127.0.0.1:<listen_port>`, path `/metrics`, with `node_id`, `agent_id` and `agent_type` labels from `MergeLabels`
  - in the same file, a server scrape of `127.0.0.1:4319`, job `otel-collector-server`, added in `addInternalServicesToScrape` (`prometheus.go:311`) when OTEL is enabled
  - `managed/services/victoriametrics/prometheus_test.go`

**Interfaces:**
- Consumes `OtelCollector.listen_port`, which pmm-agent assigns from its port range in Task 7 (`TelemetryPort = port`).

- [ ] **Step 1: Write the failing tests.** `TestScrapeConfigOtelCollector` asserts job, target and labels. `TestInternalScrapeOtelServer` asserts `127.0.0.1:4319` when enabled and no job when disabled.
- [ ] **Step 2: Run them.** `cd managed && go test ./services/victoriametrics/ -run Otel`. Expected: FAIL.
- [ ] **Step 3: Implement** both scrape configs.
- [ ] **Step 4: Run them again.** Same command. Expected: PASS. On a Feature Build, `otelcol_receiver_accepted_log_records_total` is queryable in VictoriaMetrics for each node collector and for the server collector.
- [ ] **Step 5: Commit.**
  ```bash
  git add managed/services/victoriametrics
  git commit -s -m "PMM-15593 Scrape OTEL collector self-metrics"
  ```

### Task 10: Inventory type in the Grafana fork, and telemetry

**Files:**
- In percona/grafana, on branch `PMM-15572-otel-collector-type`, modify the files below. If PMM-15002 has moved Inventory into `ui/apps/pmm` by then, make the same change there instead.
  - `public/app/percona/inventory/Inventory.types.ts` (:28-50): `OtelCollector = 'otel-collector'`
  - `public/app/percona/inventory/Tabs/Agents.constants.ts` (:25-47): name `OTEL collector`
  - the matching tests
- In percona/pmm, modify `managed/services/telemetry/config.default.yml`. Add metrics:
  - `otel_collector_enabled` (from settings);
  - `otel_log_sources_count` (`SELECT count(*) FROM log_sources`);
  - `otel_daily_ingested_bytes`, through the ClickHouse telemetry datasource: `SELECT sum(bytes_on_disk) FROM system.parts WHERE database='otel' AND active AND partition = toString(yesterday())`.

- [ ] **Step 1: Write the failing test** in the Grafana fork: the Agents tab renders an `otel-collector` agent as "OTEL collector". Run it with `yarn test Agents`. Expected: FAIL.
- [ ] **Step 2: Implement** the type and name. Run the test again. Expected: PASS. Commit with `git commit -s -m "PMM-15572 Show the OTEL collector in Inventory"`.
- [ ] **Step 3: Write the failing test** for telemetry: extend the telemetry config test in `managed/services/telemetry` so it asserts the three new metric names load. Run it. Expected: FAIL.
- [ ] **Step 4: Implement** the config entries. Run `cd managed && go test ./services/telemetry/`. Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add managed/services/telemetry
  git commit -s -m "PMM-15571 Report OTEL usage in telemetry"
  ```

### Task 10b: journald in the pmm-client Docker image

**Files:**
- Modify:
  - `build/docker/client/Dockerfile.el9`. The `builder` stage (`FROM redhat/ubi9`, :1) installs `systemd`. Copy `/usr/bin/journalctl` and the shared libraries `ldd` lists for it into the `micro` stage (:31), the same way the image already copies the CA trust store (~:80).
  - `documentation/` docs PR (see the roadmap's docs item): the `docker run` flags, which are `-v /var/log/journal:/var/log/journal:ro -v /run/log/journal:/run/log/journal:ro -v /etc/machine-id:/etc/machine-id:ro --group-add <host systemd-journal gid>`, plus a read-only mount of each database log directory. Also list what each Percona operator's pmm-client sidecar must mount (PMM-15577).

**Interfaces:**
- Consumes `JournalctlAvailable` in `RenderInput` (Task 6). The supervisor sets it from `exec.LookPath`, using the collector's `PATH` value.

- [ ] **Step 1: Write the failing check.** Run `docker run --rm --entrypoint /usr/bin/journalctl percona/pmm-client:<fb-tag> --version`. Expected: FAIL, the file is missing.
- [ ] **Step 2: Implement** the Dockerfile change.
- [ ] **Step 3: Run the check again.** Expected: a version is printed. Then on a CHAOS VM, run the container with the documented mounts and add `pmm-admin add logs --journald --units=sshd.service`, with `sshd.service` allowed in `pmm-agent.yaml`. Expect rows in `otel.logs` within 1 minute (PMM-15577 AC).
- [ ] **Step 4: Record** the image size change in the PR description.
- [ ] **Step 5: Commit.**
  ```bash
  git add build/docker/client/Dockerfile.el9
  git commit -s -m "PMM-15577 Add journalctl to the pmm-client image"
  ```
