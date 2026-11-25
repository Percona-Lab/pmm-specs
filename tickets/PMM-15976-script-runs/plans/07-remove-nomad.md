# Plan 07: Remove Nomad (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans). This plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts. It belongs to PMM 3.13.0, the release after 3.12.0, which ships [plans 01](01-agent-run-script.md) to [06](06-verification.md).

**Goal:** Nomad is gone from PMM Server, PMM Client, PMM Extensions and the docs: no Nomad process, binary, port, endpoint, setting or inventory row, while every old client, server, compose file, side-car setting and API client that still names Nomad keeps working or fails with a clear message.

**Architecture:** Removal only, in two repositories. The rules that shape it ([spec §10.3](../spec.md#103-old-and-new-together), [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md)):
- The `v1` API takes additions only, so the `nomad-agent` type stays in the protocol, marked deprecated, and is never returned.
- pmm-managed deletes the `nomad-agent` rows at every start, and every path that reads agents skips the type instead of panicking: in a rolling HA upgrade a replica still on 3.12.0 creates the rows again.
- An old pmm-managed may still ask a new pmm-agent for a Nomad client, so pmm-agent keeps a stub that answers and logs.
- `PMM_ENABLE_NOMAD` and `PMM_NOMAD_GC_*` in a compose file, pmm-agent's two Nomad flags, and the side-car's fallback values are accepted and ignored, with a warning where the spec gives one, for this release.
- In PMM Extensions `nomad` stays as a retired backend value: stored tasks still load, and running one is refused with a message.
- Leftovers on disk are deleted by the component that owns them: pmm-managed on PMM Server, the packages and `install_tarball` on hosts.

**Tech Stack:** Go (pmm-managed, pmm-agent, pmm-admin), protobuf with `buf breaking`, nginx, the client build scripts and rpm/deb packaging, React in `ui/` (pnpm workspace), MkDocs; Python, Alembic and Poetry in percona/pmm-extensions.

**Spec:** [spec §10](../spec.md#10-removing-nomad), [§10.1](../spec.md#101-nomad-capabilities-and-what-replaces-each), [§10.2](../spec.md#102-two-releases), [§10.3](../spec.md#103-old-and-new-together), [§13 O4](../spec.md#13-risks-and-open-questions), [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md), [ADR-01](../adr/ADR-01-pmm-agent-replaces-nomad.md). Ticket [PMM-15983](https://perconadev.atlassian.net/browse/PMM-15983).

## Global Constraints

- **Needs:** PMM 3.12.0, which ships [plans 01](01-agent-run-script.md) to [06](06-verification.md), is out; [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md) is Accepted, with [O4](../spec.md#13-risks-and-open-questions) answered ([spec §13](../spec.md#13-risks-and-open-questions)).
- **Code base:** percona/pmm `main` at `122590fc6` and percona/pmm-extensions `main` at `285f3c96dc`. Line numbers refer to those commits; the expansion re-checks them on the `main` it starts from, which by then carries [plans 01](01-agent-run-script.md) to [05](05-switch-over.md).
- **Paths:** a bare path is in percona/pmm, except in [Task 15](#task-15-pmm-extensions), whose paths are all in percona/pmm-extensions.
- **Scope:** Nomad is named in 146 files of percona/pmm (`git grep -il nomad` at `122590fc6`) [V]. Generated files are regenerated, never edited:
  - `*.pb.go`, `*.pb.validate.go`, `api/**/json/**`, `api/swagger/*.json` and `api/descriptor.bin` by `make gen`;
  - `ui/packages/extensions/api/specs/*.json` and `ui/packages/extensions/api/src/generated/*` in two steps (`ui/packages/extensions/api/README.md:144-153`) [V]: after [Task 15](#task-15-pmm-extensions)'s PR is merged, `python scripts/dump_openapi.py` in percona/pmm-extensions, the four specs copied into `ui/packages/extensions/api/specs/`, then `pnpm --filter @pmm-extensions/api codegen` and `pnpm --filter @pmm-extensions/api exec oxfmt --write src/generated` in percona/pmm's PR.
- **Additive-only API:** no enum value, message, field or oneof number is removed or renumbered; `buf breaking` runs inside `make gen` (`api/Makefile:6`) [V]. Released release notes (`documentation/docs/release-notes/3.*.md`) and `CHANGELOG.md` history are not edited.
- **pmm-agent's flags:** `--paths-nomad` and `--paths-nomad-data-dir` stay accepted in 3.13.0, hidden and ignored, so their users on PMM Server (`build/docker/server/entrypoint.sh:312`, `managed/services/supervisord/pmm_config.go:182`) [V] and any user's automation keep working whatever order they change in. They are deleted in 3.14.0 ([Task 10](#task-10-pathsnomad-pathsnomaddatadir-and-their-flags-hidden-and-ignored)).
- **Branches:** percona/pmm `PMM-15983-remove-nomad` from `main`, one PR, or one per task group if the expansion splits it; percona/pmm-extensions under its own rules, with a changelog fragment (percona/pmm-extensions `changelog.d/README.md`).

## Review Focus

- **The converter panic.** A `nomad-agent` row that an older replica creates again during a rolling HA upgrade reaches `ToAPIAgent`, whose `default:` panics on an unknown type (`managed/services/converters.go:628-629`) [V], and `SetState`, whose `default:` fails the whole request for that pmm-agent (`managed/services/agents/state.go:388-389`) [V]. Expected: both skip the type, and the rows are deleted at every start ([Task 6](#task-6-nomad-agent-rows-no-new-ones-no-state-push-deleted-at-every-start-skipped-everywhere)).
- **The server's own pmm-agent.** It is started with `--paths-nomad-data-dir` [V]; a deleted flag would stop it on every PMM Server [I: kingpin refuses unknown flags]. Expected: the flag stays accepted and hidden in 3.13.0, and a Feature Build shows `supervisorctl status pmm-agent` RUNNING ([Task 10](#task-10-pathsnomad-pathsnomaddatadir-and-their-flags-hidden-and-ignored)).
- **A new pmm-agent meeting an old server** that still sends the Nomad process. Expected: the stub reports `AGENT_STATUS_DONE`, logs why once, and every other agent process on the host is untouched ([Task 9](#task-9-pmm-agents-supervisor-the-nomad-case-becomes-a-stub)).
- **Nomad's certificate material on the server volume** (`/srv/nomad/certs/`). Expected: pmm-managed deletes `/srv/nomad` at every start, after the `nomad-agent` rows ([Task 12](#task-12-leftovers-on-disk)).
- **A compose file that still sets `PMM_ENABLE_NOMAD=1`.** Expected: PMM Server starts, logs one warning naming the variable, and runs no Nomad ([Task 4](#task-4-pmm_enable_nomad-and-pmm_nomad_gc_-read-and-ignored-with-a-warning)).
- **A side-car that still has the 3.12.0 fallback values.** Expected: it starts, ignores them and logs a warning ([Task 15](#task-15-pmm-extensions)).
- **PMM Extensions rows that name the `nomad` backend.** Expected: no row is rewritten; every stored task still loads, lists, reads and deletes; running one is refused with the message, a 400 on the API and a FAILED history on the periodic path ([Task 15](#task-15-pmm-extensions)).

---

### Task 1: The Nomad server service and its wiring in pmm-managed

**Files:**
- Delete: `managed/services/nomad/nomad.go`, `managed/services/nomad/server.hcl`, `managed/models/nomad.go`, `managed/services/server/mock_nomad_service_test.go`
- Modify: `managed/cmd/pmm-managed/main.go` (import `:97`; GC flags `:843-866`; `nomadClientConfig` and `nomad.New` `:1090-1100`; `NewStateUpdater(…, nomad)` `:1103`; `Nomad:` in the server params `:1183`)
- Modify: `managed/services/server/server.go` (`:73`, `:106`, `:132`, `:877-880`), `managed/services/server/deps.go` (`nomadService`, `:116-119`), `.mockery.yaml` (`:86`)
- Modify: `managed/services/agents/deps.go` (the `nomad` interface, `:79-84`), `managed/services/agents/state.go` (field `:70`, `NewStateUpdater` `:74`, `:80`)
- Test: `managed/services/server/server_test.go`, `managed/services/agents/state_test.go`

**Interfaces:**
- `agents.NewStateUpdater(db, r, vmdb, vmParams)` loses its `nomad` parameter. `server.Params` loses `Nomad`.
- Nothing creates `/srv/nomad/certs` any more; today `nomad.New` creates it on every start, Nomad on or off (`managed/services/nomad/nomad.go:63-66`, called at `main.go:1097`) [V].

**Steps:**
- Remove the package and every reference; run `make gen` to regenerate the mocks (`.mockery.yaml`).
- Run `go build ./...` and `make test` in `managed/`.

### Task 2: The supervisord program

**Files:**
- Modify: `managed/services/supervisord/supervisord.go` (the skip at `:125-131`; the `nomad-server` template `:365-379`; `NomadEnabled` `:451`)
- Delete: `managed/testdata/supervisord.d/nomad-server.ini`
- Modify: `build/ansible/pmm-docker/post-build.yml` (`nomad-server.ini` in the list at `:53`)
- Test: `managed/services/supervisord/supervisord_test.go` (`:56`)

**Interfaces:**
- `PMMServerHost` stays: Grafana's `GF_SERVER_DOMAIN` uses it too (`supervisord.go:344-345`) [V].
- `/etc/supervisord.d` is in the image: pmm-managed is started with `--supervisord-config-dir=/etc/supervisord.d` (`managed/services/supervisord/pmm_config.go:168`) [V], and the image's only volume is `/srv` (`build/docker/server/Dockerfile.el9:48`) [V]. A recreated container therefore never carries an old `nomad-server.ini` [I: PMM Server is upgraded by recreating its container].

**Steps:**
- Remove the template, its parameter and the skip, and the `post-build.yml` entry, which no build step can produce any more.
- Run `make test` in `managed/services/supervisord/`.

### Task 3: The settings field and a migration that strips it

**Files:**
- Modify: `managed/models/settings.go` (`Nomad` field `:98-100`; `IsNomadEnabled` `:199-202`), `managed/models/settings_helpers.go` (`EnableNomad` `:83`, `:211-213`)
- Modify: `managed/models/database.go` (a migration with the next free number in `databaseSchema`, `:104`; the last at `122590fc6` is 129, `:1379`) [V]
- Test: `managed/models/settings_helpers_test.go`, `managed/models/database_test.go`

**Interfaces:**
- Migration: `UPDATE settings SET settings = settings - 'Nomad';`. The JSON key is `"Nomad"` (`settings.go:100`) [V]. Precedent: migration 66 strips `ia` (`database.go:796-800`) [V].
- The public settings API has no Nomad field (`git grep -i nomad api/server` finds nothing) [V], so no API change.

**Steps:**
- Write the failing test on `testdb.Open`: settings JSON with `{"Nomad":{"enabled":true}}` loses the key and keeps every other key.
- Add the migration; remove `IsNomadEnabled` and its callers ([Tasks 2](#task-2-the-supervisord-program), [6](#task-6-nomad-agent-rows-no-new-ones-no-state-push-deleted-at-every-start-skipped-everywhere), [8](#task-8-pmm-admin-the-pmm-ui-and-victoriametrics)).

### Task 4: `PMM_ENABLE_NOMAD` and `PMM_NOMAD_GC_*` read and ignored, with a warning

**Files:**
- Modify: `managed/utils/envvars/parser.go` (the case at `:236-242`; the public-address warning at `:363-368`; [plan 05](05-switch-over.md)'s deprecation warning beside it)
- Modify: `managed/cmd/pmm-managed/main.go` (the five kingpin flags at `:843-866`, with [Task 1](#task-1-the-nomad-server-service-and-its-wiring-in-pmm-managed))
- Test: `managed/utils/envvars/parser_test.go`

**Interfaces:**
- One case for `PMM_ENABLE_NOMAD`, `PMM_NOMAD_GC_INTERVAL`, `PMM_NOMAD_GC_DISK_USAGE_THRESHOLD`, `PMM_NOMAD_GC_INODE_USAGE_THRESHOLD`, `PMM_NOMAD_GC_MAX_ALLOCS` and `PMM_NOMAD_GC_PARALLEL_DESTROYS`, appending one warning per variable to `warns`: the variable has no effect, because Nomad was removed from PMM in 3.13.0.
- Today the five GC variables already reach the parser's `default:` branch and get `unknown environment variable` (`parser.go:285`, `:359`) [V], because only kingpin reads them. The new case replaces that generic line with one that says why.

**Steps:**
- Write the failing test: each variable, with any value, `PMM_ENABLE_NOMAD=1` included, gives its warning and no error, and no setting changes.
- Add the case; remove the public-address warning and [plan 05](05-switch-over.md)'s deprecation warning.

### Task 5: nginx `/nomad/` and its auth rule

**Files:**
- Modify: `build/ansible/roles/nginx/files/conf.d/pmm.conf` (upstream `nomad-server-json` `:39-44`; `location /nomad/` `:294-316`)
- Modify: `managed/services/grafana/auth_server.go` (`"/nomad": admin`, `:127`)
- Test: `managed/services/grafana/auth_server_test.go`

**Interfaces:** the `/nomad/` endpoint goes. It was documented for admins (`documentation/docs/reference/nomad.md:108-117`) [V] and announced in the release notes of 3.12.0 ([plan 05 Task 7](05-switch-over.md#task-7-release-notes-and-api-docs)). An unmatched prefix falls back to `grafanaAdmin` with a warning (`resolveRule`, `auth_server.go:604-623`) [V].

**Steps:**
- Remove both. Record in the test what `/nomad/v1/nodes` answers to an authenticated Admin.
- Check that `nginx -t` passes in the Feature Build.

### Task 6: `nomad-agent` rows: no new ones, no state push, deleted at every start, skipped everywhere

**Files:**
- Modify: `managed/services/agents/registry.go` (the call `:387`; `addNomadAgentToPMMAgent` `:526-544`), `version/features.go` (`NomadAgentSupportVersion`, `:26`; its only user is `registry.go:527`) [V]
- Modify: `managed/services/agents/state.go` (`IgnoreNomad` `:225`; `case models.NomadAgentType` `:281-290`)
- Delete: `managed/services/agents/nomad.go`, `managed/services/agents/nomad_test.go`
- Modify: `managed/models/agent_model.go` (`NomadAgentType`, `:96`), `managed/models/agent_helpers.go` (`IgnoreNomad` `:258-259`, `:343-347`; `FindAgentByID` `:427-438`)
- Modify: the `IgnoreNomad` callers: `managed/services/inventory/agents.go:108`, `managed/services/inventory/inventory_metrics.go:113`, `managed/services/management/agent.go:70`, `:116`, `managed/services/management/node.go:252`, `managed/services/management/service.go:263`
- Modify: `managed/services/converters.go` (the `NomadAgentType` case `:580-588`; `default:` `:628-629`)
- Modify: `managed/cmd/pmm-managed/main.go` (the deletion, after `migrateDB`, `:988`)
- Test: `managed/models/agent_helpers_test.go`, `managed/models/agent_model_test.go`, `managed/services/inventory/agents_test.go`, `managed/services/agents/registry_test.go`, `managed/services/agents/state_test.go`

**Interfaces:**
- The type's name stays known to pmm-managed as a retired value (`models.NomadAgentType`, `"nomad-agent"`), so that it can be recognized and skipped; nothing creates it.
- **At every start**, after `migrateDB` (`main.go:988`) and before the agents registry is built (`main.go:1022`) [V]: `DELETE FROM agents WHERE agent_type = 'nomad-agent';`. It names only `agents`: the link tables `agent_nodes` and `agent_services` were dropped long ago (`database.go:269`) [V], and the rows' `pmm_agent_id` points from the row to its pmm-agent, so nothing references them [V].
- **Skipped everywhere:** `FindAgents` always excludes the type (today's `IgnoreNomad` condition, `agent_helpers.go:343-347`, made unconditional); `FindAgentByID` answers `NotFound` for it, which today it does not (`agent_helpers.go:427-438`) [V]; `ToAPIAgent` recognizes it and returns an error the list paths skip, instead of reaching the panic. So `SetState` never meets the type, and its `default:` (`state.go:388-389`) is never reached for it.
- **Why every start and not one migration** ([spec §10.3](../spec.md#103-old-and-new-together)): in a rolling HA upgrade a replica still on 3.12.0 creates the row again on every connect (`registry.go:387`) [V].

**Steps:**
- Write the failing tests: on `testdb.Open`, a pmm-agent with a `nomad-agent` row; after the start-up deletion `FindAgents` with no filter returns the pmm-agent and nothing of the type. With the row inserted again after start: `FindAgents`, `FindAgentByID`, `ToAPIAgent` over a list, `ListAgents` and `SetState` for that pmm-agent all work and never show it. A pmm-agent of any version that connects creates no row.
- Make the changes; remove the six callers' `IgnoreNomad` settings, since the exclusion is now unconditional.
- Check that an old pmm-agent's Nomad client stops on the next `SetState`: today's "Nomad disabled" path (`agent/agents/supervisor/supervisor.go:574-611`) [V].

### Task 7: The inventory API type: kept, deprecated, never returned

**Files:**
- Modify: `api/inventory/v1/agents.proto` (`AGENT_TYPE_NOMAD_AGENT = 16` `:35`; `message NomadAgent` `:79-99`; the repeated field `nomad_agent` in `ListAgentsResponse` `:809`; the oneof members in `GetAgentResponse` `:839`, `ChangeAgentRequest` `:927` and `ChangeAgentResponse` `:951`; `ChangeNomadAgentParams` `:1967-1970`)
- Modify: `managed/services/inventory/grpc/agents_server.go` (type map `:59`; list `:120-121`; get `:174-175`; change `:274-275`), `managed/services/inventory/agents.go` (`ChangeNomadAgent`, `:1773-1799`)
- Regenerate: `make gen`
- Test: `managed/services/inventory/agents_test.go` (`managed/services/inventory/grpc/` has no test file) [V]; `api-tests/inventory/`

**Interfaces:**
- `deprecated = true` on the enum value, the message, the repeated field, the three oneof members and `ChangeNomadAgentParams`, each with a comment that Nomad was removed and the type is never returned. Precedent for `deprecated = true` with a reason: `api/server/v1/server.proto:105-119` [V].
- `api/inventory/v1/agents.go` (`:31`) and `api/inventory/v1/types/agent_types.go` (`:23`, `:46`) keep the type: they follow the protocol.
- `ListAgents` returns no `nomad_agent`, also when filtered by `AGENT_TYPE_NOMAD_AGENT`; `ChangeAgent` with `nomad_agent` falls to the existing `default:` and answers `InvalidArgument` (`agents_server.go:278-279`) [V].

**Steps:**
- Write the failing tests for both behaviors, then remove the server-side cases.
- Run `make gen`.

### Task 8: pmm-admin, the PMM UI, and VictoriaMetrics

**Files:**
- Delete: `admin/commands/inventory/change_agent_nomad_agent.go`, `admin/commands/inventory/change_agent_nomad_agent_test.go`
- Modify: `admin/commands/inventory/inventory.go` (`:113`), `admin/commands/list.go` (`:311`, `nomadAgents` `:556-570`), `admin/commands/list_test.go`
- Modify: `ui/apps/pmm/src/types/agent.types.ts` (`:37`), `ui/apps/pmm/src/pages/inventory/agents/Agents.messages.ts` (`:35`)
- Modify: `managed/services/victoriametrics/scrape_configs.go` (`scrapeConfigForNomadServer` `:111-130`; `scrapeConfigsForNomadAgent` from `:132`), `managed/services/victoriametrics/victoriametrics.go` (`:431-433`), `managed/services/victoriametrics/prometheus.go` (`:285-292`)
- Test: `managed/services/victoriametrics/victoriametrics_test.go` (`:96`), the UI's inventory tests

**Interfaces:**
- `pmm-admin inventory change agent nomad-agent` goes; the `inventory` group is hidden (`admin/cli/cli.go:58`) [V].
- `pmm-admin list` stops rendering `nomad_agent` entries. Against a 3.12.0 server that still returns them, they are not shown.

**Steps:**
- Remove the command and the list entry; update `list_test.go`.
- Remove the UI type and its label; run `pnpm --filter ui lint` and `pnpm --filter ui test` (`ui/apps/pmm/package.json:2`, `:11`, `:14`) [V].
- Remove both scrape configs. The Nomad metric series stop; no dashboard in percona/pmm reads them (`git grep -i nomad` finds no dashboard JSON) [V].

### Task 9: pmm-agent's supervisor: the Nomad case becomes a stub

**Files:**
- Modify: `agent/agents/supervisor/supervisor.go` (the init-failure branch `:857-862`; `handleNomadAgent` `:883-911`; the `processParams` case `:1159-1163`)
- Test: `agent/agents/supervisor/supervisor_test.go` (the rendered-HCL expectations at `:894` and `:960` go)

**Interfaces:**
- For an `AgentProcess` of type `AGENT_TYPE_NOMAD_AGENT`, pmm-agent starts no process, records the agent as tracked, reports `AGENT_STATUS_DONE`, and logs once per agent ID that Nomad is no longer part of pmm-agent and the server's request is ignored ([spec §10.3](../spec.md#103-old-and-new-together)) [D].
- Without the stub, the removed case would make `startProcess` return `unhandled agent type` (`supervisor.go:1164-1165`), be retried three times and logged with no status to the server (`:746-786`, `:627-642`) [V].

**Steps:**
- Write the failing test: a `SetState` with one exporter and one Nomad process starts the exporter, reports `DONE` for the Nomad agent, and logs the line once across two `SetState`s.
- Reuse `handleNomadAgent`'s reporting without the process, with a true message in place of "cgroups are not writable" (`:893`).

### Task 10: `Paths.Nomad`, `Paths.NomadDataDir` and their flags: hidden and ignored

**Files:**
- Modify: `agent/config/config.go` (`Nomad` `:125`, `NomadDataDir` `:128`; default `tools/nomad` `:278`; data dir default `:304-307`; carried across `setup` `:455`, `:457`; flags `:543-546`)
- Modify: `build/docker/server/entrypoint.sh` (`:312`), `managed/services/supervisord/pmm_config.go` (`:182`), `managed/testdata/supervisord.d/pmm-db_disabled.ini` (`:67`), `managed/testdata/supervisord.d/pmm-db_enabled.ini` (`:91`)
- Test: `agent/config/config_test.go`, `managed/services/supervisord/pmm_config_test.go`

**Interfaces:**
- `--paths-nomad` (`PMM_AGENT_PATHS_NOMAD`) and `--paths-nomad-data-dir` (`PMM_AGENT_PATHS_NOMAD_DATA_DIR`) stay accepted in 3.13.0, marked with kingpin's `Hidden()` (`github.com/alecthomas/kingpin/v2`, `FlagClause.Hidden`, v2.4.0) [V], and bound to nothing. They are deleted in 3.14.0.
- `Paths.Nomad` and `Paths.NomadDataDir` leave the config struct. An existing `pmm-agent.yaml` with `nomad:` and `nomad_data_dir:` still loads: `config.go:684` uses `yaml.Unmarshal` (`gopkg.in/yaml.v3`), which ignores unknown keys [I: library default]. That covers the server's own `pmm-agent.yaml`, which the entrypoint writes only once (`entrypoint.sh:305`) [V].

**Steps:**
- Write the failing tests: `pmm-agent setup --paths-nomad-data-dir=/x`, and pmm-agent started with `PMM_AGENT_PATHS_NOMAD=/y`, both succeed; neither flag appears in `--help`; nothing is written for them to `pmm-agent.yaml`; a `pmm-agent.yaml` with both old keys loads.
- Drop the flag from `entrypoint.sh:312` and `pmm_config.go:182`, with its testdata. Because pmm-agent still accepts it, the order of these changes does not matter.
- Link [PMM-15984](https://perconadev.atlassian.net/browse/PMM-15984), the follow-up for 3.14.0 that deletes the two flags, from [PMM-15983](https://perconadev.atlassian.net/browse/PMM-15983).
- Check on the Feature Build that `supervisorctl status pmm-agent` reads RUNNING on a fresh server and on one upgraded from 3.12.0.

### Task 11: Packaging

**Files:**
- Modify: `build/scripts/vars` (`:59-60`)
- Modify: `build/scripts/build-client-binary` (the target by architecture `:27-35`; the build command `:71-72`; `gobuild_component "nomad"` `:136`; the copy `:169`)
- Modify: `build/scripts/build-client-source` (`:69`), `build/scripts/install_tarball` (`:85`)
- Modify: `build/packages/rpm/client/pmm-client.spec` (`:113`; a changelog entry at the top of `%changelog`)
- Modify: `build/packages/deb/files` (`:44`), `build/packages/deb/install` (`:7`), `build/packages/deb/rules` (`:61`)

**Interfaces:**
- The PMM Client Docker image and the PMM Server image both take the binary from the client tarball (`build/docker/client/Dockerfile.el9:27-29`; `build/ansible/roles/pmm-client/tasks/main.yml:25`) [V], so neither needs its own change.
- An rpm or deb upgrade removes the old `tools/nomad`, a file the old package owned [I: standard package behavior; `%files` owns `/usr/local/percona/pmm`, `pmm-client.spec:212-214`].

**Steps:**
- Remove every line. Check that the target variable at `:27-35` is used by no other component before removing it.
- Check on the Feature Build that `tools/nomad` is absent from the rpm, the deb, the tarball, the PMM Client image and the PMM Server image.

### Task 12: Leftovers on disk

**Files:**
- Modify: `managed/cmd/pmm-managed/main.go` (after [Task 6](#task-6-nomad-agent-rows-no-new-ones-no-state-push-deleted-at-every-start-skipped-everywhere)'s deletion of the rows): delete `/srv/nomad`
- Modify: `build/packages/rpm/client/pmm-client.spec` (`%posttrans`, `:44`), `build/packages/deb/postinst` (`configure)`, `:11`): delete `/usr/local/percona/pmm/data/nomad`
- Modify: `build/scripts/install_tarball`: delete `${PMM_DIR}/tools/nomad` and `${PMM_DIR}/data/nomad` (`PMM_DIR`, `:33`)
- Test: a pmm-managed test of the deletion on a temporary directory; the package checks of the Feature Build

**Interfaces:**
- What stays after an upgrade today, since nothing removes it [V: no delete outside the per-address server certificate, `managed/services/nomad/nomad.go:160-172`]:

  | Where | What |
  |---|---|
  | PMM Server, `/srv/nomad/` | Nomad's server state (`server.hcl:4`) |
  | PMM Server, `/srv/nomad/certs/` | Nomad's certificate material (`nomad.go:39`, `:132-241`) |
  | PMM Server, `/srv/nomad/nomad-server-*.hcl` | one per public address used (`nomad.go:40`) |
  | PMM Server, `/srv/nomad/data` | the data of the server's own Nomad client (`entrypoint.sh:312`) |
  | PMM Server, `/srv/logs/nomad-server.log*` | the program's logs (`supervisord.go:375-377`) |
  | Each host, `<PathsBase>/data/nomad` | Nomad's allocation directories, with task output (`agent/config/config.go:304-307`; default `/usr/local/percona/pmm/data/nomad`), or a custom path from the old `nomad_data_dir` key |
  | A tarball-installed host, `tools/nomad` | the binary |

**Steps:**
- **PMM Server:** at every start, after the rows are deleted, pmm-managed removes `/srv/nomad`; a start that finds none does nothing. `/srv/logs/nomad-server.log*` lies outside it and is named in the release notes.
- **Hosts:** the rpm deletes `<base>/data/nomad` in `%posttrans`, which runs after the old package's scriptlets have restarted pmm-agent [I: rpm's scriptlet order], so the old Nomad client is gone with the old pmm-agent; the deb deletes it in `postinst` `configure)`. Both tolerate a failure (`rm -rf … || true`), so a mount Nomad left under an allocation directory cannot fail the upgrade; what is left is named in the release notes. `install_tarball` deletes `tools/nomad` and the data directory.
- A custom data directory set through the old `nomad_data_dir` key is not known to the packages; the release notes name it.
- The Docker image of PMM Client keeps nothing: a new image has neither the binary nor the directory.
- Write the failing tests first for the pmm-managed deletion (present, absent, a file in place of the directory).

### Task 13: Docs and release notes

**Files:**
- Modify: `documentation/docs/reference/nomad.md` (to a short page: Nomad was removed in 3.13.0; what PMM deletes and what is left to remove by hand, [Task 12](#task-12-leftovers-on-disk); how PMM Extensions runs tasks now)
- Modify: `documentation/docs/install-pmm/install-pmm-server/deployment-options/docker/env_var.md` (the GC section, `:237-272`; `PMM_ENABLE_NOMAD` mentions)
- Modify: `documentation/docs/apps/deploy-pmm-extensions.md` (the 3.12.0 fallback note, [plan 05 Task 6](05-switch-over.md#task-6-user-documentation)), `documentation/docs/reference/index.md` (`:37`, `:64`, `:109`), `documentation/docs/reference/pmm_components_and_versions.md` (`:13`)
- Modify: `documentation/AGENTS.md` (`:139`, `:189`: example links that point at `nomad.md`), `CONTRIBUTING.md` (`:54`), `agent/AGENTS.md` (`:16`)
- Modify: `docker-compose.yml`, `.env.example`, `.env.dev.example` (the fallback comments [plan 05 Task 3](05-switch-over.md#task-3-pmm-server-with-and-without-pmm_enable_nomad-in-3120) left)
- Modify: `documentation/api/extensions-tasks/connectivity-check.md` (the `nomad` target goes)
- Modify: `documentation/docs/release-notes/next.md`; Create: `documentation/api/release-notes/3.13.0.md`, in the form of `documentation/api/release-notes/3.11.0.md`
- Modify, while `nomad.md` links Nomad's site: `documentation/.linkspector.yml` (`:14-15`)

**Interfaces:**
- `reference/nomad.md` stays a page, and in the nav (`documentation/mkdocs-base.yml:610`): the release notes of 3.2.0, 3.9.0 and 3.10.0 link to it, and they are not edited [V].

**Steps:**
- Write the release notes: an entry, and the removal drafted for the doc team's highlights, as `release-notes/3.4.0.md:72-76` did for VMware: what is gone; that `PMM_ENABLE_NOMAD`, `PMM_NOMAD_GC_*` and the side-car's fallback values are ignored with a warning; that hosts below the version gate cannot run tasks; what PMM deletes and what is left to remove by hand.
- Write the API changes: `/nomad/` is gone; `nomad_agent` is never returned; `pmm-admin inventory change agent nomad-agent` is gone; the `nomad` connectivity target is gone.
- Preview with `make doc-build-preview`.

### Task 14: Tests and test data in percona/pmm

**Files:**
- Modify: `admin/commands/list_test.go`, `agent/agents/supervisor/supervisor_test.go`, `agent/config/config_test.go`, `managed/models/agent_helpers_test.go`, `managed/models/agent_model_test.go`, `managed/services/inventory/agents_test.go`, `managed/services/server/server_test.go`, `managed/services/supervisord/supervisord_test.go`, `managed/services/victoriametrics/victoriametrics_test.go`, `managed/utils/envvars/parser_test.go`
- Delete: `admin/commands/inventory/change_agent_nomad_agent_test.go`, `managed/services/agents/nomad_test.go`, `managed/services/server/mock_nomad_service_test.go`, `managed/testdata/supervisord.d/nomad-server.ini`
- Modify: `managed/testdata/supervisord.d/pmm-db_disabled.ini`, `managed/testdata/supervisord.d/pmm-db_enabled.ini`
- Modify: `ui/packages/plugins/om/tests/NodesPage.test.tsx`, `ui/packages/plugins/om/tests/NotOnboardedDialog.test.tsx`; the extensions-framework tests that use "nomad" as a host id may keep it as plain data

**Interfaces:** none. `managed/services/om/inventory_test.go` keeps its four assertions that a message does not mention Nomad (`:578`, `:918`, `:941`, `:964`) [V].

**Steps:**
- After all tasks, run `git grep -il nomad` and record the list: only generated files, the deprecated protocol type and its comments, the retired model constant, the pmm-agent stub, the ignored flags, [Task 4](#task-4-pmm_enable_nomad-and-pmm_nomad_gc_-read-and-ignored-with-a-warning)'s case, the removal docs, released release notes, history and the guard assertions above.
- Run `make prepare-pr`; `make test` in `managed/`, `agent/` and `admin/`; `api-tests/` against the Feature Build.

### Task 15: PMM Extensions

All paths in this task are in percona/pmm-extensions.

**Files:**
- Delete: `app/tasks/execution/executors/nomad/` (`models.py`, `log_follow.py`, `steps.py`, `constants.py`, `exceptions.py`, `__init__.py`), `app/tasks/execution/nomad_lifecycle.py`, `scripts/check_nomad_payload_size.py`, `data/http-tests/nomad.http`, `docs/customer/nomad-driver-deployment.md`
- Modify: `pyproject.toml` (`python-nomad`, `:46`), through Poetry's CLI (`poetry remove python-nomad`), never by hand
- Modify: `app/tasks/config.py` (the import `:46-52`; `NOMAD: NomadExecutor` `:221`; the code default of `DEFAULT_BACKEND`), `app/tasks/models/enums.py` (`NOMAD`, `:32`, kept as a retired value), `app/tasks/deps.py` (`:44`; `get_executor` `:77-105`; `:124-134`; `get_request_executor` `:136-162`)
- Modify: `app/tasks/main.py` (the import `:25`; `NomadLifecycle` import `:56` and lifespan `:132`; `_reconcile_nomad` `:64-84`; the 410 body `:194-234`; `nomad_exception_handler` `:237-243`), `app/tasks/celery.py` (`:45`, `:88-90`, `:240-245`, `:327-347`, `:350-386`; the finishing probe `:1091-1161`; `check_nomad_cert_expiry` `:1414-1510`), `app/tasks/crud.py` (`:41`), `app/tasks/db/seed.py` (`:43`, `:47`, `:835-866`), `app/tasks/models/constants.py` (`:67`)
- Modify: `app/tasks/connectivity/service.py` (`:44`, `:62-64`), `app/extensions/api/routes/connectivity_check.py` (`ServiceEnum.NOMAD` `:69`), `frontend/packages/shell/src/components/settings/TestConnectionButton.tsx` (`:37`), `app/extensions/apps/framework/spec.py` (`:73`), `app/extensions/apps/om_bootstrap/reconcile.py` (`:92`), `app/extensions/apps/om_inventory/dispatch.py` (`:58`), wherever [plan 04](04-extensions-executor.md) left an import of the Nomad package; comments that name it: `app/extensions/config.py:93`, `app/extensions/apps/om_inventory/mapping.py:24`
- Modify, the payloads' `NOMAD_*` fallback reads: `app/extensions/apps/backup_mongo/pbm_creds_common.py` (`:79`, `:189`, `:322`), then `make regen-pbm-payloads`, which rewrites the generated regions of the eleven payloads in `app/extensions/apps/backup_mongo/` and `restore/`; the hand-written reads outside those regions (`# --- BEGIN GENERATED …` / `# --- END GENERATED …`) in seven of them; `app/extensions/apps/om_inventory/payload/probe.py` (`:106`); `app/extensions/apps/backup_mongo/README.md` (`:102`); `tests/app/host_payloads.py` (`:465`)
- Modify: `settings.yaml` (`:42`, `:409-411`, `:434`, `:455-467`, `:516-518`, `:619-639`), `sidecar/settings.yaml` (`:328-337`), `sidecar/settings-env.sh` (`:126`, `:151`, `:165-167`), `sidecar/README.md` (`:66-67`, `:188-190`, `:233`, `:357-393`, `:457`)
- Modify: `.pre-commit-config.yaml` (`:48-51`), `Makefile` (`:254-259`, `:438`)
- Modify: `docs/customer/pmm-extensions-task-execution-dfd/` (`README.md`, `security-review-checklist.md`, `data-capture-redaction-retention.md`, the two `.mmd` files), `docs/customer/pmm-extensions-user-guide/README.md`, `docs/development/ty-policy.md`, `README.md`
- Create: `changelog.d/PMM-15983.breaking.md`
- Delete: `tests/app/tasks/execution/executors/nomad/`, `tests/app/tasks/execution/test_nomad_lifecycle.py`, `tests/app/tasks/nomad_log_stub.py`
- Test: `tests/app/tasks/conftest.py` (fixtures `nomad_stub` `:127`, `live_executor` `:139`, `live_route_overrides` `:179`), every other importer (`grep -rl NomadExecutor tests/`), `tests/app/tasks/test_routes.py`, `tests/app/tasks/test_celery.py`, `tests/sidecar/test_settings_env.py`, the payload tests [plan 04 Task 5](04-extensions-executor.md#task-5-inputs-files-the-command-configuration-artifacts-and-the-payloads-that-read-nomad_) names

**Interfaces:**
- `TaskBackendEnum` keeps `NOMAD` as a retired value beside `PMM_AGENT`, `PROXY` and `CELERY`. No row of `task` is rewritten: `task.backend` is stored as text (`EnumField(TaskBackendEnum, native_enum=False)`, `app/tasks/models/bases.py:77-79`) [V], and a stored task that names `nomad` still loads, lists, reads and deletes.
- **Running a `nomad` task is refused**, the same refusal [plan 04](04-extensions-executor.md) gives in 3.12.0 when the default backend is not `nomad`, now unconditional: on the execute route a 400 with the message, raised as [plan 04](04-extensions-executor.md)'s `NomadNotInUseError`; on the periodic and chained paths a history saved FAILED with the message through `_persist_failed_dispatch` (`app/tasks/celery.py:389`) [V], with the task's failure alert. The message says that Nomad is no longer part of PMM.
- New tasks cannot be created or changed to `nomad`: the create and update routes (`app/tasks/routes.py:174`, `:194`) [V] answer 400.
- The code default of `TASKS.DEFAULT_BACKEND` changes to `pmm_agent`, and the setting accepts `pmm_agent` only. The four seeded kinds are seeded with it at start-up (`app/tasks/db/seed.py:1115`) [V].
- **A side-car that still has the 3.12.0 fallback values** starts, ignores them and logs one warning per value, for 3.13.0 only: `TASKS__DEFAULT_BACKEND=nomad` is read as `pmm_agent`; a `TASKS.NOMAD` value (from `TASKS__NOMAD__*` or a file) is accepted and ignored; `EXTENSIONS_NOMAD_ENDPOINT` is no longer expanded by `sidecar/settings-env.sh` (`:165-167`) and is reported instead. The acceptance goes in 3.14.0, with pmm-agent's flags ([PMM-15984](https://perconadev.atlassian.net/browse/PMM-15984)).
- **History of Nomad-era runs:** stored rows and stored output in `taskhistory_log` stay readable. Live logs and files of such runs answer 410, as they do today once Nomad has collected them (`TaskDataNotFoundInExecutorError`, `app/tasks/execution/exceptions.py:19`) [V].
- The certificate-expiry and finishing-probe periodic rows (`tasks__check_nomad_cert_expiry` and the finishing probe's) need no migration: seeding deletes every row with the system prefix that it no longer lists (`init_periodic_tasks_db`, `app/core/celery/utils.py:133-137`, called with `SYSTEM_PERIODIC_TASK_PREFIX = "tasks__"` at `app/tasks/db/seed.py:1112`, `:881`) [V].

**Steps:**
- Write the failing tests: a stored task with `backend = nomad` loads, lists, reads and deletes; running it answers 400 on the execute route, and on a periodic run saves a FAILED history with the message; creating or updating a task with `nomad` answers 400; the seeded kinds read `pmm_agent` after start-up; a Nomad-era history serves its stored output and answers 410 for live logs and files; the side-car starts with each fallback value set and logs its warning; no payload reads a `NOMAD_*` name (`grep -rnE "NOMAD_(META|TASK_DIR|ALLOC_DIR)" app/` finds nothing outside the release notes).
- Remove the code, the dependency and the settings; change the payloads' shared module, run `make regen-pbm-payloads`, edit the hand-written reads, and check with `make regen-pbm-payloads-check`.
- Run `make lint`, `make typecheck`, `make test`, `make changelog-check`; then `make regen-specs` and hand the four specs to percona/pmm's UI regeneration (Global Constraints).

### Task 16: Acceptance: old and new together

**Files:** none; results on [PMM-15983](https://perconadev.atlassian.net/browse/PMM-15983), on a Feature Build of this plan.

**Interfaces:** none.

**Steps:**
- Post each case's bar before its run, and run every row of [spec §10.3](../spec.md#103-old-and-new-together), plus the side-car's fallback values:

  | Case | Set-up | Bar |
  |---|---|---|
  | New server, old client | this plan's server; one host on PMM Client 3.11.0 | Monitoring works; the host list says too old; a run for it is `not_started`; no Nomad client runs on the host after the first `SetState` |
  | The server stops sending the Nomad client's config | an old pmm-agent that ran a Nomad client before the server upgrade | It stops its Nomad client and removes `<TempDir>/nomad_agent/<agent_id>` (`agent/agents/supervisor/supervisor.go:605-611`) [V]; every other agent process keeps running |
  | New client, old server | this plan's PMM Client against PMM Server 3.12.0 with `PMM_ENABLE_NOMAD=1` | The Nomad agent reads `DONE`; pmm-agent logs the stub's line once; every exporter runs; nothing retries ([Task 9](#task-9-pmm-agents-supervisor-the-nomad-case-becomes-a-stub)) |
  | `nomad-agent` rows in the inventory | a server upgraded from 3.12.0 with Nomad enabled and rows present; then a row inserted again while it runs | No `nomad-agent` row after the start; with the row inserted again, `ListAgents`, `GetAgent` of every remaining agent, `SetState`, `pmm-admin list` and the inventory page all work and never show it ([Task 6](#task-6-nomad-agent-rows-no-new-ones-no-state-push-deleted-at-every-start-skipped-everywhere)) |
  | `AGENT_TYPE_NOMAD_AGENT` and `NomadAgent` | the generated client of 3.12.0 | `ListAgents` parses and returns no `nomad_agent`; `buf breaking` passed ([Task 7](#task-7-the-inventory-api-type-kept-deprecated-never-returned)) |
  | `PMM_ENABLE_NOMAD` in a compose file | `PMM_ENABLE_NOMAD=1` and `PMM_NOMAD_GC_INTERVAL=5m` set | PMM Server starts; one warning per variable; no Nomad process; nothing listens on 4646 or 4647 ([Task 4](#task-4-pmm_enable_nomad-and-pmm_nomad_gc_-read-and-ignored-with-a-warning)) |
  | `pmm-agent --paths-nomad` and `--paths-nomad-data-dir` | the server's own pmm-agent, fresh and upgraded; `pmm-agent setup --paths-nomad-data-dir=…` on a host | RUNNING under supervisord; `setup` succeeds and ignores the flag, which `--help` does not list ([Task 10](#task-10-pathsnomad-pathsnomaddatadir-and-their-flags-hidden-and-ignored)) |
  | Leftovers on disk | a server, and an rpm, a deb and a tarball host, upgraded from 3.12.0 with Nomad enabled | No `/srv/nomad` after the first start; no `<base>/data/nomad` and no `tools/nomad` on the hosts ([Task 12](#task-12-leftovers-on-disk)) |
  | History of runs made under Nomad | a history from 3.12.0's fallback | Its stored output reads; live logs and files answer 410 ([Task 15](#task-15-pmm-extensions)) |
  | `pmm-admin inventory change agent nomad-agent` | the new pmm-admin | The command does not exist ([Task 8](#task-8-pmm-admin-the-pmm-ui-and-victoriametrics)) |
  | A stored task that is a Nomad job | PMM Extensions upgraded from 3.12.0 | It lists, reads and deletes; running it answers 400 with the message, and a periodic run saves a FAILED history with it ([Task 15](#task-15-pmm-extensions)) |
  | The side-car's fallback values | the side-car upgraded from 3.12.0 with `TASKS__DEFAULT_BACKEND=nomad`, `TASKS__NOMAD__ENDPOINT` and `EXTENSIONS_NOMAD_ENDPOINT` set | It starts, logs one warning per value, and runs tasks through pmm-agent ([Task 15](#task-15-pmm-extensions)) |
