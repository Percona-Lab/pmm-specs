# PMM-15567 OTel Spec Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This file is temporary.** Task 11 deletes it before the pull request is opened. It lives on the branch only so the plan survives a session restart.

**Goal:** Bring `tickets/PMM-15567-otel/` (spec, ADRs, plans 00–08) in line with the decisions approved on 2026-11-05, fix the defects found in the review, and open it as a draft pull request for architect review.

**Architecture:** Documentation-only changes in Percona-Lab/pmm-specs, on branch `PMM-15567-otel-spec-refresh`. One commit per task. Accepted ADRs are never edited; new decisions go into new ADRs (ADR-23, ADR-24) or into Proposed ADRs.

**Tech Stack:** Markdown; `git`, `grep` and `python3` for checks; read-only access to percona/pmm, percona/grafana and percona/percona-helm-charts checkouts for line references.

**Spec:** the design approved in this session, recorded below under **Decisions**, plus the review findings listed in each task. The folder's own [`spec.md`](spec.md), [`plans/00-roadmap.md`](plans/00-roadmap.md) and [`adr/`](adr/README.md) are what this plan edits.

## Decisions (approved 2026-11-05)

| # | Decision |
|---|---|
| D25 | **Release and default.** The Technical Preview targets **3.12.0** (Jira release date 2027-01-14) with Phase 0 and plans 01, 02, 03 and 08. OTEL is on by default (ADR-12 unchanged), with a go/no-go: if PMM-15592 has not passed by 3.12.0 code freeze, 3.12.0 ships with `OtelCollectorEnabledDefault = false`. |
| D26 | **Read path.** The native explorer is the only log UI. No Grafana OTEL datasource, no Grafana fork middleware, no Grafana Logs dashboard. New **ADR-23** records it and supersedes ADR-07 once accepted. It supersedes D24 and amends D20. |
| D27 | **Patterns in 3.12.0.** `otel.logs` gets `PatternHash UInt64 MATERIALIZED cityHash64(<masked Body>)`. The masking rules live in one Go package, `utils/logpatterns`, used by the qan-api2 migration test and by pmm-managed's display queries. A rules change ships as a new migration with `MODIFY COLUMN` only, never `MATERIALIZE COLUMN`; old rows keep old hashes until retention drops them. |
| D28 | **`findQuery`** (open a log line's query in QAN) is a follow-up, not planned. Record both options: a new qan-api2 RPC (preferred, keeps table ownership) or pmm-managed reading `pmm.metrics` directly (the prototype's way). |
| — | **D12 gets its own ADR, ADR-24** (one `otel.v1` domain under `/v1/otel`). |
| — | **Reviewers:** JiriCtvrtka, 4nte, matejkubinec, requested only after the user has read the draft. **#5118 is left as is**; the pull request mentions it as reference only. **Jira is changed only after approval**; the pull request lists the edits. |

## Global Constraints

- **pmm-specs rules** (`AGENTS.md`): never rewrite an **Accepted** ADR's decision; add one that supersedes it. ADR-01, 02, 03, 06, 07, 08, 09, 10, 11, 12, 13, 14 are Accepted and must show no diff in this pull request. No dates in file names. The repo is public: no customer names, credentials, internal hostnames, or exploit detail (plan 07 keeps saying what to change, not how to abuse it).
- **Stable task numbers.** Never renumber an existing plan task, because other plans cite them. A split adds a `b` task directly after its parent (`Task 6`, then `Task 6b`). A removed task keeps its heading with one line: "Removed by ADR-23."
- **Style:** match the surrounding text: short sentences, bullet lists, `[V]`/`[I]` marks in the spec, backticks for code names. New ADRs use the four sections in `adr/README.md` and a header with status, date `2026-11-05` and tickets.
- **Commits:** `PMM-15567 <summary>` (≤50 chars), signed off with `git commit -s`, ending with the line `Claude-Session: https://claude.ai/code/session_018YUBpTVguL8XEU8NzSvDQQ`. Push after every task with `git push -u origin HEAD`.
- **Working directory:** commands whose paths start with `tickets/` run from the pmm-specs repo root; all others run from `tickets/PMM-15567-otel`.
- **Line references** point at a pinned commit, recorded in the spec header (Task 10). Until Task 10, keep existing numbers unless a task says otherwise.
- **Link check** (run from the repo root; it checks relative file links, not anchors):

  ```bash
  python3 - <<'EOF'
  import glob, os, re, sys
  bad = 0
  for f in glob.glob('tickets/PMM-15567-otel/**/*.md', recursive=True):
      for m in re.finditer(r'\]\(([^)#\s]+)(?:#[^)]*)?\)', open(f).read()):
          t = m.group(1)
          if t.startswith(('http://', 'https://', 'mailto:')):
              continue
          if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(f), t))):
              print(f, '->', t); bad += 1
  sys.exit(1 if bad else 0)
  EOF
  ```

## Review Focus

1. **A stale reference survives in a file no task lists** (`3.11`, `pmm-otel`, `ClickHouse-OTEL`, `Logs dashboard`, `= 22;`, `plans 01–06`). Expected: none outside history notes. Test in Task 11 (the global stale-text grep).
2. **An Accepted ADR gets edited.** Expected: no diff. Test in Task 11 (`git diff --stat origin/main -- <accepted ADRs>` prints nothing).
3. **A cross-reference points at a split or removed task** (for example "plan 02, Task 3" for log sources, which move to Task 3b). Expected: every `plan 0N, Task M` resolves to a heading that exists and does what the sentence says. Test in Task 11 (the cross-reference listing, checked by hand).
4. **A new or renamed file breaks a relative link.** Expected: the link check passes. Test at the end of every task that adds or moves a file (Tasks 2, 3, 11).
5. **The prototype's numbers leak in** (Settings 24, `:getPatterns`, `/v1/server/log-parser-presets`, migrations 127–150). Expected: the contract uses this plan's names only. Test in Task 11 (grep for those strings outside spec §4 and the prototype description in §2).

---

### Task 1: Release target 3.12.0 and the on-by-default go/no-go (D25)

**Files:**
- Modify: `plans/00-roadmap.md` (release gating, ~:25-29; version gate, :72), `plans/02-node-collector.md` (:116 `min_agent_version`, :286-298 `v3_11`), `plans/04-database-logs.md` (:76, :231, :264), `adr/ADR-21-native-log-explorer.md` (:39), `spec.md` (§8 table and the interview notes, §9 risks)

- [ ] **Step 1: Run the failing check** (from the repo root). `grep -rn '3\.11\|v3_11' tickets/PMM-15567-otel --include=*.md | grep -v REFRESH-PLAN`. Expected: 10 hits (roadmap 2, plan 02 4, plan 04 3, ADR-21 1).
- [ ] **Step 2: Edit.**
  - Roadmap release gating: Phase 0 and plans 01, 02, 03 **and 08** make up the 3.12.0 Technical Preview; plan 08 is no longer optional (D26). Add the go/no-go rule from D25 as its own bullet.
  - Version gate: `3.12.0-0`. Plan 02's preset `min_agent_version: 3.12.0`; rename the test variable `v3_11` to `v3_12`. Plan 04: every `3.11` becomes `3.12` (the old-server message, :231, and `collectLogsSupported` true for `3.12.0-0` and later).
  - ADR-21 :39 is edited in Task 2 together with the rest of ADR-21; leave it for now.
  - Spec §8: add row **D25** with the text from this plan's Decisions table. Under the interview notes, add "**Review of 2026-11-05:** D25–D28 decided; D24 superseded by D26; ADR-23 and ADR-24 added." §9: add a risk, "**Schedule.** On 2026-11-05 every epic ticket but PMM-15577 was unassigned; 3.12.0 needs plans 01, 02, 03 and 08 merged by code freeze."
- [ ] **Step 3: Run the check again.** Expected: only `adr/ADR-21-native-log-explorer.md:39` (Task 2 removes it).
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Target 3.12.0 and gate the default on"`

### Task 2: Explorer-only read path (D26, ADR-23)

**Files:**
- Create: `adr/ADR-23-explorer-only-read-path.md`
- Modify:
  - `adr/README.md` (index row 23)
  - `adr/ADR-21-native-log-explorer.md` (Proposed: Decision "Grafana" bullet, Consequences)
  - `adr/ADR-18-otel-lbac.md` (Proposed: drop "The Grafana `pmm-otel` datasource stays Admin-only", :42)
  - `spec.md`: §1 summary (:23), §1 table rows "Our own UI" and "How LBAC works" (:35-36), §3 diagram (:85-86) and table-layout sentence (:99), F8 consequence (:143, append "Superseded by ADR-23: there is no OTEL datasource."), §7.3 item 2 (:298-300), §7.4 item 5 (:325), D20 and D24 rows, new row D26
  - `plans/03-ui-and-grafana.md`: title, Goal, Architecture, Tech Stack (drop the plugin version), Spec, Depends on (drop `otel_reader`), Global Constraints (drop the datasource, Viewer-query and `sqlstring` lines), Review Focus items 4 and 5 (replace, see Step 2), Tasks 5 and 6 (stub headings)
  - `plans/08-log-explorer.md`: :19 and :25 (`ADR-07` → `ADR-23`), Task 6 (:293-297)
  - `plans/05-traces.md` (header note and Task 4), `plans/06-lbac.md` (:7 Goal: "Everyone else keeps today's behaviour: logs are Admin-only (ADR-23)."; :100, `ADR-07` → `ADR-23`)
  - `plans/00-roadmap.md`: plan 03 row (scope and tickets: drop the datasource, guard and Logs dashboard; tickets PMM-15574 (UI), PMM-15593), plan 05 row ("trace view, re-plan: ADR-23"), plan 08 row, the D24 follow-up bullet (:48, delete)

**Interfaces:**
- Produces the file name `ADR-23-explorer-only-read-path.md`, which Tasks 9 and 11 link to.

- [ ] **Step 1: Run the failing check.** `grep -rn 'pmm-otel\b\|ClickHouse-OTEL\|percona_otel_admin\|Logs dashboard\|Logs\.json' tickets/PMM-15567-otel --include=*.md | grep -Ev '/adr/ADR-(0[1236789]|1[0-4])-|REFRESH-PLAN'`. Expected: 33 hits, in spec.md, ADR-18, ADR-21, the roadmap and plans 03, 05, 06 and 08.
- [ ] **Step 2: Write ADR-23.** Status: "Proposed. Supersedes ADR-07 once accepted." Tickets: PMM-15567, PMM-15576, PMM-15722.
  - **Context:** ADR-07 reads logs through a Grafana datasource guarded by a fork middleware; ADR-21 adds a native explorer on `LogsService`. Keeping both means two read paths, one of which needs a fork change every release (ADR-07, Consequences) and can never carry LBAC (ADR-18).
  - **Options:** both (ADR-07 plus ADR-21); explorer only; Grafana only.
  - **Decision:** explorer only. Kept from ADR-07: reads are Admin-only until ADR-18 is implemented (rule `"/v1/logs": admin`); `otel_reader` has `SELECT` on `otel.*` only and is used by `LogsService`; the server collector redacts secrets. Removed: the `pmm-otel` datasource, the fork middleware and the Logs dashboard. Service dashboards and Inventory link to the explorer.
  - **Consequences:** no fork change per release; Admins lose ad-hoc SQL over logs in Grafana Explore; the explorer is on the 3.12.0 critical path; plan 05's Grafana traces dashboard must be re-planned; PMM-15576 is re-scoped after approval.

  Then edit the other files:
  - ADR-21 Decision: replace the Grafana bullet with "**Grafana:** no OTEL datasource or Logs dashboard (ADR-23)." Consequences: delete "Two ways to read logs"; replace the 3.11.0 line with "It ships with 3.12.0 and is the only log UI, so it is on the release's critical path." Add `Patterns` to the API list (D27).
  - Spec §3 diagram: replace the two Grafana lines with `pmm-managed LogsService (user otel_reader) ── PMM UI Logs explorer (Admins only)`. §3 layout sentence: "so the exporter works against it unchanged". §7.3 item 2: the `"/v1/logs": admin` rule, `otel_reader`, and no Grafana datasource (ADR-23). §7.4 item 5: drop the datasource sentence. D20: drop "the Grafana datasource and dashboard stay". D24: append "Superseded by D26." New D26 from this plan's Decisions.
  - Plan 03: title "OTel 03: Settings → OTEL UI and Collector Health Implementation Plan". Keep the file name. Replace Review Focus 4 and 5 with: (4) "**A log source whose path contains spaces or non-ASCII characters.** Expected: shown and editable verbatim. Test in Task 4 (`renders path verbatim`)." and (5) "**Purge while the collector is running.** Expected: a confirmation dialog, then status `disk_bytes` drops. Test in Task 2 (`purge asks for confirmation`)." Add both tests to those tasks' Step 1 lists. Tasks 5 and 6 become stub headings ("Removed by ADR-23.").
  - Plan 08 Task 6: list the dashboard files directly (`MySQL/MySQL_Instance_Summary.json`, `PostgreSQL/PostgreSQL_Instance_Summary.json`, `MongoDB/MongoDB_Instance_Summary.json`, `OS/Node_Summary.json`; check names with `ls dashboards/dashboards/*/`), delete the `Logs.json` bullet, and use `from=${__from:date:iso}&to=${__to:date:iso}` because `useLogsUrlFilters` accepts ISO or relative times only. Inventory row action: "If PMM-15002 has moved Inventory into `ui/apps/pmm` by then, add the action there; otherwise in the Grafana fork's `public/app/percona/inventory/`."
  - Plan 05: under the header add "**Re-plan note:** ADR-23 removes the Grafana OTEL datasource, so Task 4's dashboard needs a native trace view instead (plan 06, Task 5 sketches one)." Task 4 heading gets "(re-plan: ADR-23)".
- [ ] **Step 3: Run the check again, then the link check.** Expected: hits only in ADR-23 (the items it removes), ADR-21's Context (:9, what PMM-15576 asked for), plan 03's two stub headings, and spec F8's "Superseded by ADR-23" note; the link check exits 0.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Read logs through the explorer only"`

### Task 3: ADR-24, one OTel API domain (D12)

**Files:**
- Create: `adr/ADR-24-otel-api-domain.md`
- Modify: `adr/README.md` (row 24), `spec.md` (D12 row: add "(ADR-24)"; §1 line 38: "ADR-19, ADR-20, ADR-24"), `plans/00-roadmap.md` (:7 and :15, "ADR-17..24"; the D12 sentence in :7)

- [ ] **Step 1: Run the failing check.** `ls adr/ADR-24-*.md`. Expected: no such file.
- [ ] **Step 2: Write ADR-24.** Status: "Proposed. Changes the paths in PMM-15574 (`/v1/server/log-parser-presets`) and PMM-15571 (`/v1/server/otel:purge`)." Tickets: PMM-15567, PMM-15571, PMM-15574.
  - **Context:** the tickets put presets and purge under `/v1/server`; log sources, discovery and status need a home; auth rules are per path prefix.
  - **Options:** the tickets' `/v1/server/...` paths; one domain `api/otel/v1` (`OtelService`) under `/v1/otel`; one service per resource.
  - **Decision:** one domain, `OtelService` under `/v1/otel`, with one rule `"/v1/otel": admin`. Settings stay in `/v1/server/settings`. Reading logs is a separate domain, `api/logs/v1` `LogsService` under `/v1/logs`, because its rule changes when LBAC arrives (ADR-18, ADR-23).
  - **Consequences:** one auth rule; the tickets' paths change; the prototype (#5118) uses the old paths.
- [ ] **Step 3: Run the check again and the link check.** Expected: the file exists; exit 0.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Record the OTel API domain as ADR-24"`

### Task 4: Patterns (D27) and `findQuery` as a follow-up (D28)

**Files:**
- Modify:
  - `adr/ADR-04-schema-owner-and-layout.md` (Proposed): Decision and Consequences
  - `spec.md`: §3 table layout (add the column), §8 rows D27 and D28, §9 the ClickHouse load risk
  - `plans/00-roadmap.md`: Shared contract (ClickHouse: `PatternHash`; Packages: `utils/logpatterns`; Logs read API: `Patterns` row; `Filters` gains two fields), Follow-ups (add D28 with both options)
  - `plans/01-server-receiver.md`: Task 3 (column, package, test); Task 8 (assert `PatternHash != 0`)
  - `plans/08-log-explorer.md`: Goal list, Depends on, new **Task 7: Patterns** at the end

**Interfaces** (written into the plans exactly as below):
- `package logpatterns` in `utils/logpatterns/logpatterns.go` (no license header needed: `utils/` is exempt):
  - `var rules [][2]string`: the 12 rules of `managed/otel/patterns.go` on `tibi-holmes` at `f5a9e9a19`, in that order. Cite the source; don't paste them into the plan.
  - `func Expr(column string) string`: nested `replaceRegexpAll(…)` over the rules, wrapped in `substringUTF8(…, 1, 200)`, with string literals quoted as the prototype's `sqlString` does (`:` as `\x3A`).
  - `func HashExpr(column string) string`: `cityHash64(` + `Expr(column)` + `)`.
- Column in `qan-api2/migrations/otel/sql/01_logs.up.sql`, written literally: `PatternHash UInt64 MATERIALIZED <HashExpr("Body")> CODEC(ZSTD(1))`. It is not in the sort key.
- Test `TestPatternHashMatchesRules` in `qan-api2/migrations/otel_test.go`: read `otel/sql/*.up.sql` in file order, take the last `PatternHash UInt64 MATERIALIZED ` expression up to ` CODEC(`, and assert it equals `logpatterns.HashExpr("Body")`. On failure, print the expected expression and the instruction "add a new migration with ALTER TABLE otel.logs MODIFY COLUMN; never MATERIALIZE COLUMN (ADR-04)".
- Plan 08 Task 7 proto (additive to Task 1's messages):
  - `Filters`: `uint64 pattern_hash = 9; repeated uint64 exclude_pattern_hashes = 10;`
  - `message LogPattern { string pattern = 1; uint64 pattern_hash = 2; uint64 count = 3; uint64 previous_count = 4; bool is_new = 5; Severity max_severity = 6; google.protobuf.Timestamp first_seen = 7; google.protobuf.Timestamp last_seen = 8; string sample = 9; }`
  - `rpc Patterns(PatternsRequest{Filters filters = 1; uint32 limit = 2;}) returns (PatternsResponse{repeated LogPattern patterns = 1;})` at `POST /v1/logs:patterns`. `limit` defaults to 50, capped at 200. Rows ordered by `count` descending.
  - `previous_count` covers the window of the same length just before `start`. `is_new` is `previous_count == 0` while the previous window has rows for the same filters, so a source added in this window doesn't mark everything new.
  - `pattern` is `logpatterns.Expr` applied to one sample `Body` per group, in ClickHouse.
- Plan 08 Task 7 UI: a Lines | Patterns toggle on `/logs` (URL `view=patterns`); a peak-ui `Table` with pattern, count, change against the previous window, a "New" `Chip`, and the max-severity chip. A row click switches to Lines filtered by `pattern_hash` (URL `pattern`); a row action "Hide" adds it to `exclude_pattern_hashes` (URL `xpattern`, repeatable).
- Plan 08 Task 7 tests: `TestPatternsQueryGroupsByStoredHash` (the SQL groups by `PatternHash` and applies `Expr` only to the sample), `TestPatternsIsNewNeedsPreviousRows`, `TestSearchExcludesPatternHashes`, and Vitest `row click filters lines by pattern`, `hide adds xpattern to URL`.

- [ ] **Step 1: Run the failing check.** `grep -rln 'PatternHash' tickets/PMM-15567-otel`. Expected: no output.
- [ ] **Step 2: Edit** the files above. ADR-04 Decision gains a "**Patterns**" bullet (column, package, rules-change procedure); Consequences gain "insert cost: 12 regexes per row, measured in PMM-15592" and "after a rules change, a pattern can appear twice until retention drops the old rows". Spec D27 and D28 rows use this plan's Decisions text. Spec §9's first risk adds "including the `PatternHash` insert cost". Plan 01 Task 3: add the package and column to Files and Interfaces, add `TestPatternHashMatchesRules` to Step 1, and `go test ./utils/logpatterns/ ./qan-api2/migrations/` to Steps 2 and 4.
- [ ] **Step 3: Run the check again.** `grep -rln 'PatternHash' tickets/PMM-15567-otel`. Expected: ADR-04, spec.md, the roadmap, plans 01 and 08. Also `grep -rn 'findQuery' tickets/PMM-15567-otel | grep -v REFRESH-PLAN`: only spec D28 and the roadmap follow-up.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Add log patterns, defer findQuery"`

### Task 5: Plan 01 fixes

**Files:**
- Modify: `plans/01-server-receiver.md`, and `plans/00-roadmap.md` (Shared contract: `Settings.otel = 23` :116, `ChangeSettingsRequest.otel = 17` :117, the `/otlp` auth rule key; Global constraints: "125 today" :176)

Each fix below names the defect, then the change.

- [ ] **Step 1: Run the failing check** (from `tickets/PMM-15567-otel`). `grep -n 'FillDefaults\|"/otlp/"\|every .MergeTree\|entrypoint.sh\|read-only at' plans/01-server-receiver.md; grep -n '= 22\|= 16\|120 today' plans/00-roadmap.md`. Expected: plan 01 lines 94, 215, 330, 353, 387, 398, 469; roadmap lines 116, 117, 176.
- [ ] **Step 2: Edit.**
  1. **HA stop path** (Task 6). The reconcile loop can only restart. Split Task 6:
     - **Task 6:** the supervisord program and its stop path. `supervisord.UpdateConfiguration` removes `otel-collector.ini` and runs `supervisorctl update otel-collector` when the collector is disabled or paused (F17). Test in `supervisord_test.go`.
     - **Task 6b:** `otel.Service` and the reconcile loop. The `supervisordService` interface gains `StartSupervisedService(name string) error` and `StopSupervisedService(name string) error` (both exist in `supervisord.go`). `Run` calls them when the effective running state changes. `TestRunAppliesSettingsChangedByAnotherReplica` asserts `StopSupervisedService("otel-collector")` was called on the mock, not just the `onApplied` value.
  2. **Directories** (Task 6). The image runs as `USER 1000` (`build/docker/server/Dockerfile.el9:46`), and `entrypoint.sh` creates `/srv` directories on first boot only. `/etc/otel-collector` (owner `pmm`, 0700) is created at image build in the Ansible role that installs the collector; `otel.Service` creates its own parent directories with `os.MkdirAll` before writing. Remove `entrypoint.sh` from Task 6's files.
  3. **Defaults in tests** (Tasks 4, 6). `Settings.fillDefaults` is unexported and runs inside `GetSettings`. `TestOtelSettingsDefaultsOnUpgrade` writes the old JSON into the settings row (`testdb.Open`) and reads it back with `models.GetSettings`. Task 6 tests build `&models.Settings{Otel: models.OtelSettings{CollectorEnabled: new(true), LogsRetentionDays: 7, TracesRetentionDays: 7, MaxDiskGB: 10, DiskWatermarkPercent: 80}}`.
  4. **Proto numbers** (Task 4): `Settings.otel = 23`, `ChangeSettingsRequest.otel = 17` (15 is reserved and 16 is `enable_om`).
  5. **Auth rule key** (Task 7 and the roadmap). With the key `"/otlp/"`, `resolveRule` never matches `/otlp` (`nextPrefix("/otlp")` is `/`). Use `"/otlp": admin`; the test cases `/otlp/v1/logs → admin` and `/otlp → admin` then hold. Also fix spec §3 and §7.3 in Task 9.
  6. **Test container mount** (Task 2). Mount the one file, `../build/ansible/roles/clickhouse/files/users.d/otel.xml:/etc/clickhouse-server/users.d/otel.xml:ro`, not the directory: the image writes `users.d/default-user.xml` when `CLICKHOUSE_USER` is set [I, upstream image].
  7. **Purge and cleaner targets** (Tasks 9, 10). Add `var dataTables = []string{"logs"}` in `managed/services/otel/tables.go` (plan 05 appends `otel_traces`, `otel_traces_trace_id_ts`). Purge truncates exactly those; the cleaner reads `system.parts` with `table IN dataTables`. `TestPurgeTruncatesOnlyOtelTables` and `TestCleanerNeverTouchesQAN` also assert nothing touches `otel_schema_migrations`.
  8. **Pause flag write** (Task 10). The cleaner calls `models.SetOtelIngestPaused(tx *reform.TX, paused bool, reason string) error`, which runs `SELECT settings FROM settings FOR UPDATE`, changes only `otel.ingest_paused` and `otel.ingest_paused_reason`, and writes back in the same transaction (see PMM-15600). Test `TestSetOtelIngestPausedKeepsOtherSettings` (`testdb`).
  9. **Placeholders.** Task 5 `TestServerCollectorConfigHasNoGRPC`: assert `receivers.otlp.protocols` has exactly the key `http`. Task 6: remove "either inject the command runner, or assert through the existing reload seam"; the stop path is tested through the mock in Task 6b.
  10. **Task 11 path:** "in percona/percona-helm-charts", not `/srv/runner/2/...`.
- [ ] **Step 3: Run the check again.** Expected: no output. `grep -n '### Task 6b' plans/01-server-receiver.md` finds the new heading.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Fix plan 01 stop path, dirs and tests"`

### Task 6: Plan 02 fixes (and plan 04 cross-references)

**Files:**
- Modify: `plans/02-node-collector.md`, `plans/04-database-logs.md` (:228 → `plan 02, Task 3b`), `plans/00-roadmap.md` (`LogSourceState` enum), `spec.md` §6.2 (`status`/`status_reason` → `state`/`state_reason`)

- [ ] **Step 1: Run the failing check** (from `tickets/PMM-15567-otel`). `grep -n 'version.OtelCollectorSupportVersion)\|SyncBuiltInPresets(q \*reform.Querier, builtIns \[\]presets\|UpdateLogSourceStates(q \*reform.Querier, statuses\|17 after Task 2\|pmm_logrus\|/srv/runner\|scrape_configs.go\|migration \*\*12' plans/02-node-collector.md`. Expected: hits in Tasks 1, 2, 3, 7, 8, 9 and 10.
- [ ] **Step 2: Edit.**
  1. **Version check type** (Tasks 1, 3, 4). `models.PMMAgentSupported` takes a hashicorp `*version.Version` (`managed/models/agentversion.go:48`). Task 1 adds `models.PMMAgentMinVersionForOtelCollector = version.Must(version.NewVersion("3.12.0-0"))` next to the other `PMMAgentMinVersionFor…` values, and `version.OtelCollectorSupportVersion` (the shared-contract `FeatureVersion`) for `state.go`. Task 3 uses the first, Task 4 the second. Both are defined in Task 1, so Task 3 no longer depends on Task 4.
  2. **`models` stays free of service and API imports** (Tasks 3, 7). `SyncBuiltInPresets(q *reform.Querier, builtIns []models.BuiltInPreset) error` with `type BuiltInPreset struct { Name, Description, OperatorsYAML, MinAgentVersion string; Selectable bool }`; `main.go` converts `presets.Preset` to it. `UpdateLogSourceStates(q *reform.Querier, updates []models.LogSourceStateUpdate) error` with `type LogSourceStateUpdate struct { ID, State, Reason string }`; `handler.go` converts from `agentv1.LogSourceStatus`.
  2b. **Migration numbers** (Tasks 1, 3, 3b). Replace "migration **121**" and "**122**" with "the next free number at merge time (126, 127 and 128 on `main` at the pinned commit, in task order)".
  3. **State names.** The `log_sources` columns are `state` and `state_reason`, holding the proto enum name (`LOG_SOURCE_STATE_COLLECTING`, …). Add `LOG_SOURCE_STATE_AGENT_TOO_OLD = 6` to the roadmap's `LogSourceState` enum; only pmm-managed sets it (Task 4). Spec §6.2 uses the same names.
  4. **Splits** (stable numbers, `b` after the parent):
     - Task 2: the format, `presets.go`, `validate.go`, the harness module, and the generic presets `raw`, `json`, `syslog`, `journald`. **Task 2b:** the remaining presets from Task 2's list, each with `input.log` and `expected.json`.
     - Task 3: `log_parser_presets`, its migration, the preset RPCs and the startup sync. **Task 3b:** `log_sources`, its migration (the next number after Task 3's), the partial unique index test, and the log source RPCs. Plan 04 :228 then cites Task 3b.
     - Task 7: privilege drop, `ReadableAs`, the supervisor case, the `usermod` package lines; the supervisor also assigns `TelemetryPort` from its port range and reports it as `listen_port` (Task 9 needs it). **Task 7b:** the status round trip (`StateChangedRequest.log_source_statuses`, `handler.go`, `UpdateLogSourceStates`).
  5. **Counts** (Tasks 2b, 3, 8). The presets api-test asserts "every selectable built-in in `presets.BuiltIn()`", not 17. Task 8's table uses `pmm_agent` for `qan-api2.log` and `vmproxy.log`; delete the `pmm_logrus` option in Task 2 Step 4 and Task 8.
  6. **Server-logs completeness test** (Task 8). `TestServerSourcesCoverEveryShippedLog` also reads `logfile = /srv/logs/<name>.log` (supervisord's own log), not only `stdout_logfile`.
  7. **Server data dir** (Task 5). `/srv/otelcol/data` is created by pmm-agent with `os.MkdirAll` at collector start, not in `entrypoint.sh`. Remove `entrypoint.sh` from Task 5's files.
  8. **Scrape location** (Task 9). `addInternalServicesToScrape` is in `managed/services/victoriametrics/prometheus.go:311`; drop `scrape_configs.go` from the file list and put `TestInternalScrapeOtelServer` in `prometheus_test.go`.
  9. **Order and paths** (Task 10, 10b). Move Task 10b below Task 10. Task 10's fork path becomes "in percona/grafana"; add "If PMM-15002 has moved Inventory into `ui/apps/pmm`, add the type there instead."
- [ ] **Step 3: Run the check again.** Expected: no hits. Then `grep -n '^### Task' plans/02-node-collector.md` lists 1, 2, 2b, 3, 3b, 4, 5, 6, 7, 7b, 8, 9, 10, 10b.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Fix plan 02 types, splits and tests"`

### Task 7: Plans 05, 06 and 07 fixes

**Files:**
- Modify: `plans/05-traces.md`, `plans/06-lbac.md` (Global Constraints :26, Task 3 tests), `adr/ADR-18-otel-lbac.md` (Proposed: Decision item 4), `spec.md` §7.4 item 4, `plans/07-access-hardening.md`

- [ ] **Step 1: Run the failing check.** `grep -n 'without the header is denied\|No header for a non-Admin\|TestSearchFailsClosedWithoutHeader\|PMM-XXXX\|/srv/runner' plans/06-lbac.md plans/07-access-hardening.md adr/ADR-18-otel-lbac.md spec.md`. Expected: hits in all four.
- [ ] **Step 2: Edit.**
  1. **Fail-closed rule** (plan 06, ADR-18, spec §7.4). `auth_server` sends no `X-Proxy-Filter` when LBAC is off or the user has no filters, and refuses the request when a selector doesn't parse (`managed/services/grafana/auth_server.go`, `getLBACFilters` and the `len(filters) == 0` return). New wording: "A request without the header is full access. The guard is that `/v1/logs` and `/v1/traces` are in `lbacPrefixes`; a selector that doesn't parse is refused upstream; service-account tokens get an explicit rule." Replace `TestSearchFailsClosedWithoutHeader` with `TestLBACPrefixesCoverOtelReadPaths` (auth_server unit test) and an api-test `TestRestrictedUserGetsFilterHeader`.
  2. **Traces have no service id** (plan 05 Review Focus 2 and Task 1; plan 06 Task 4). Add to plan 06 Task 4: "Traces store no `PmmServiceId` (plan 05 deletes `pmm.service_id` at ingest), so the predicate for spans is node-only, plus services assigned by plan 05's correlation. Decide at re-plan." Plan 05 Task 1 gets the same one-line note.
  3. **Plan 07 Task 2 is done.** Mark its heading "(done by PMM-15697, `a98506570`)" and replace its steps with one: "Check that the three service-scoped lookups (`QueryExists`, `SchemaByQueryID`, `ExplainFingerprintByQueryID`) return `NotFound` for a hidden service; if not, that is the only remaining change." Roadmap plan 07 row: "Task 2 merged (PMM-15697)".
  4. **Plan 07 placeholders.** Replace each `PMM-XXXX` with `<KEY>` and add one Global Constraints line: "`<KEY>` is the Jira key filed per `SECURITY.md` before the task starts; the branch is `<KEY>-<words>`." Replace `/srv/runner/3/percona/grafana` with "percona/grafana". Add no other text to plan 07.
- [ ] **Step 3: Run the check again.** Expected: no hits.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Fix LBAC fail-closed rule and plan 07"`

### Task 8: Plan 08 and roadmap dependencies

**Files:**
- Modify: `plans/08-log-explorer.md` (:29 Depends on; :295 runner path, if Task 2 left it), `plans/00-roadmap.md` (plan 02 and plan 06 rows; :3)

- [ ] **Step 1: Run the failing check.** `grep -n '01 tasks 1–4 |\|05\. Design-level\|plans 01–06\|/srv/runner' plans/00-roadmap.md plans/08-log-explorer.md`. Expected: hits.
- [ ] **Step 2: Edit.** Roadmap :3 "plans 01–08". Plan 02 row depends on "01 Tasks 1–4 and 9". Plan 06 row depends on "05 and 08. Design-level; re-plan before execution". Plan 08 Depends on: "plan 01, Tasks 2–4 (`otel.logs` with `PatternHash`, `otel_reader`, settings), and plan 02 (data flowing)".
- [ ] **Step 3: Run the check again.** Expected: no hits.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Fix roadmap dependencies"`

### Task 9: Spec consistency

**Files:**
- Modify: `spec.md`, `README.md` (folder), `../../README.md` (repo index row)

- [ ] **Step 1: Run the failing check** (from `tickets/PMM-15567-otel`). `grep -n 'plans 01 to 06\|daily partition drop\|LogSourcesService\|into .TextFiles\|"/otlp/"\|PmmServiceId IN {s}' spec.md`. Expected: lines 7, 69, 112, 144, 207, 213, 297, 320, 344.
- [ ] **Step 2: Edit.**
  - :7 "plans 01 to 08". :112 "pmm-managed sends typed `OtelCollectorParams`, and pmm-agent renders the YAML (D11, ADR-20)". :207 `OtelService`. §6.5 and D1: "a partition-drop job every 10 minutes" (ADR-05). §3 and §7.3: `"/otlp": admin`. §7.4 item 3: the (service, node) pair predicate from ADR-18. F9: `"/otlp": admin`.
  - Spec header: "**Updated:** 2026-11-05 (D25–D28, ADR-23, ADR-24)".
  - Folder README: status "design; refresh for 3.12.0 in review"; decisions "D1–D28"; ADRs "ADR-01..14, ADR-17..24".
  - Repo README index row: status "Design; refresh for 3.12.0 in review; ADRs partly accepted".
- [ ] **Step 3: Run the check again.** Expected: no hits. Run the link check: exit 0.
- [ ] **Step 4: Commit.** `git commit -s -m "PMM-15567 Make the spec match the ADRs and plans"`

### Task 10: Rebase line references on a pinned `main`

**Files:**
- Modify: `spec.md` (header, §5 table, §2 prototype facts), `plans/0[1-8]-*.md`

- [ ] **Step 1: Pin the commits.** `git -C <pmm checkout> fetch origin main && git -C <pmm checkout> rev-parse --short origin/main`; the same for percona/grafana and percona-helm-charts. Spec header: "**Code base:** `main` at `<pmm hash>` (percona/grafana `<hash>`, percona-helm-charts `<hash>`)".
- [ ] **Step 2: List the citations.** `grep -noE '[a-zA-Z0-9_./-]+\.(go|proto|sh|conf|spec|yml|yaml|ini|tpl|xml|ts|tsx|json)(:[0-9][0-9,~ -]*)?|\(~?:[0-9][0-9,~ -]*\)' spec.md plans/0[1-8]-*.md > <scratchpad>/citations.txt`. Each `(~:N-M)` belongs to the path named just before it on the same line.
- [ ] **Step 3: Check each citation** at the pinned commit (`git show <hash>:<path> | sed -n 'N,Mp'`): the named symbol must be in range. Fix the numbers. Known moves: api/Makefile `:22,39,59,78,122`; `server.go` `UpdateConfigurations` `:853`; `main.go` ClickHouse client `:1113`, `"cleaner"` `:1366`, `DiscardUnknown` `:411`; `supervisor.go` `StateChangedRequest` `:833`; `pmm-client.spec` nomad `:113`; helm `_helpers.tpl` secret pattern `:829-841`, haproxy `:62-90`; `auth_server.go` `maybeAddLBACFilters` `:395`/`:414`; `qan/client.go` `maps.Copy` `:429`; `PMMAgentSupported` → `managed/models/agentversion.go:48`; latest managed migration 125. A citation whose code is gone gets the current location or, if none, is removed with its sentence rewritten.
- [ ] **Step 4: Update the prototype facts in spec §2:** #5118 is now based on `pmm-3.10.0`, 614 files, +112k lines, 413 commits (2026-11-03), still a draft and reference only.
- [ ] **Step 5: Run the check.** `grep -rn '/srv/runner' tickets/PMM-15567-otel | grep -v REFRESH-PLAN` gives nothing. Record "N citations checked, M changed" for the PR description.
- [ ] **Step 6: Commit.** `git commit -s -m "PMM-15567 Rebase line references on current main"`

### Task 11: Final checks, delete this plan, open the draft PR

- [ ] **Step 1: Global stale-text check.** `grep -rnE '3\.11|v3_11|ClickHouse-OTEL|percona_otel_admin|plans 01–06|plans 01 to 06|otel = 22|otel = 16|120 today|/srv/runner|PMM-XXXX|getPatterns|/v1/server/log-parser-presets|127–150' tickets/PMM-15567-otel --include=*.md | grep -v REFRESH-PLAN`. Expected: only the ticket paths named in spec D12 and ADR-24's Context, and the prototype description in spec §2 and §4.
- [ ] **Step 2: Accepted ADRs untouched.** `git diff --stat origin/main -- tickets/PMM-15567-otel/adr/ADR-0[1-3]*.md tickets/PMM-15567-otel/adr/ADR-0[6-9]*.md tickets/PMM-15567-otel/adr/ADR-1[0-4]*.md`. Expected: no output.
- [ ] **Step 3: Cross-references.** `grep -rnoE 'plan 0[0-9],? Tasks? [0-9]+b?' tickets/PMM-15567-otel --include=*.md | grep -v REFRESH-PLAN`; open each target heading and confirm it exists and matches the sentence. Then the link check: exit 0.
- [ ] **Step 4: Delete this file and commit.** `git rm tickets/PMM-15567-otel/REFRESH-PLAN.md && git commit -s -m "PMM-15567 Remove the refresh working plan"`, then `git push -u origin HEAD`.
- [ ] **Step 5: Open the draft pull request** with `mcp__github__create_pull_request` (`owner: Percona-Lab`, `repo: pmm-specs`, `head: PMM-15567-otel-spec-refresh`, `base: main`, `draft: true`, no reviewers). Title: `PMM-15567 Refresh the OTel spec for 3.12.0`. Body:
  - **Summary:** D25–D28, ADR-23, ADR-24, and the review fixes, one bullet each.
  - **Commits:** one line per commit.
  - **For reviewers:** please review the Proposed ADRs 04, 05, 17–24; a follow-up pull request flips accepted statuses, including ADR-07 to "Superseded by ADR-23" (as #8 did for MCP).
  - **Jira edits after approval:** fixVersion 3.12.0 on PMM-15590, 15591, 15592, 15571, 15572, 15574, 15575, 15577, 15593, 15594 and 15722; re-scope PMM-15576 to "dashboard and Inventory links into the explorer", or close it; add Patterns to PMM-15722's acceptance criteria; optionally file a follow-up for `findQuery` (D28).
  - **Verification:** the link check, the stale-text grep, the accepted-ADR diff, "N citations checked, M changed".
  - **Reference:** the prototype percona/pmm#5118 is unchanged and reference only.
  - Last line: `https://claude.ai/code/session_018YUBpTVguL8XEU8NzSvDQQ`
- [ ] **Step 6: Hand over.** Give the user the PR link and ask them to read it. Request reviewers JiriCtvrtka, 4nte and matejkubinec and mark it ready only after the user says so.
