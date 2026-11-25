# Plan 05: Switch-over and deprecation (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans). This plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts.

**Goal:** The PMM bundle runs PMM Extensions' tasks through pmm-agent by default, two settings fall back to Nomad for 3.12.0 only, every text that tells a user to enable Nomad says what is true in 3.12.0, the release notes announce Nomad's removal in 3.13.0, and, once [plan 06](06-verification.md)'s gate has passed, the integration branch merges into `main`.

**Architecture:** No new mechanism. This plan sets the default that [plan 04](04-extensions-executor.md) made selectable in the bundle's profile, wires the side-car to the credentials [plan 02](02-managed-runs-api.md) checks, and changes texts. Nomad keeps shipping and starting where `PMM_ENABLE_NOMAD` is set, so an install can fall back ([spec §10.2](../spec.md#102-two-releases)).

**Tech Stack:** pydantic settings and the side-car's shell entrypoint in percona/pmm-extensions; Go and protobuf comments in percona/pmm (`make gen`); React and TypeScript in `ui/` (pnpm workspace); MkDocs Markdown in `documentation/docs/` and readme.io Markdown in `documentation/api/`.

**Spec:** [spec §10.2, §10.3](../spec.md#102-two-releases), [§8.1](../spec.md#81-a-new-executor), [§8.2](../spec.md#82-the-four-task-kinds), [§8.5](../spec.md#85-hosts-logs-files-stop), [§9.1](../spec.md#91-who-can-start-a-run), [§13 O5](../spec.md#13-risks-and-open-questions), [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md), [ADR-09](../adr/ADR-09-who-may-start-a-run.md), [ADR-01](../adr/ADR-01-pmm-agent-replaces-nomad.md). Ticket [PMM-15981](https://perconadev.atlassian.net/browse/PMM-15981).

## Global Constraints

- **Needs:** [plans 01](01-agent-run-script.md) to [04](04-extensions-executor.md) merged, and [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md) Accepted ([00](00-roadmap.md)). [Task 9](#task-9-merge-the-integration-branch-into-main), the merge into `main`, waits for [plan 06](06-verification.md)'s gate ([plan 06 Task 10](06-verification.md#task-10-release-gate)); it is not part of this plan's PR.
- **Code base:** percona/pmm `main` at `122590fc6` and percona/pmm-extensions `main` at `285f3c96dc`. Line numbers refer to those; re-check before editing.
- **Paths:** a bare path is in percona/pmm. A path in percona/pmm-extensions carries the prefix "percona/pmm-extensions".
- **Branches** ([00](00-roadmap.md#branch-and-pr-rules)):
  - percona/pmm: `PMM-15981-switch-over`, cut from the integration branch `PMM-15976-script-runs`, one PR into it.
  - percona/pmm-extensions: that repository's own rules, with a changelog fragment (`make changelog-add TICKET=PMM-15981 SECTION=changed …`, percona/pmm-extensions `changelog.d/README.md`).
- **Nothing is removed in this plan.** Nomad's server, client, binary, settings, `/nomad/` and the `nomad-agent` type stay as they are on `main`; [plan 07](07-remove-nomad.md) removes them in 3.13.0.
- **The fallback is two settings, for 3.12.0 only** ([spec §10.2](../spec.md#102-two-releases)): PMM Extensions' `TASKS.DEFAULT_BACKEND` set to `nomad`, and Nomad enabled on PMM Server (`PMM_ENABLE_NOMAD` and a public address, with port 4647 published for hosts other than PMM Server). It is the whole install, not a host.
- **What runs where, in 3.12.0** ([plan 04](04-extensions-executor.md)): a task row keeps its own `backend`; `TASKS.DEFAULT_BACKEND` decides how the four seeded kinds are seeded and what a new task gets. A run is followed to its end by the executor that dispatched it. A task whose backend is `nomad` runs only on an install that has fallen back (`TASKS.DEFAULT_BACKEND` is `nomad`); anywhere else its dispatch is refused with the message, a 400 on the API and a history saved FAILED with the message on the periodic path. The Nomad machinery (the lifecycle, the certificate-expiry beat, the finishing probe) is active when the default backend is `nomad`, or while a run that Nomad dispatched is not final. No other signal is used.
- **The code default does not change in 3.12.0.** Only the bundle's profile sets `TASKS.DEFAULT_BACKEND` to `pmm_agent`; the default in percona/pmm-extensions' code stays `nomad` until 3.13.0 ([plan 07](07-remove-nomad.md)). `TASKS.DEFAULT_BACKEND` is a start-up setting, not overridable at runtime ([plan 04](04-extensions-executor.md)).
- **Certificate verification:** [plan 04](04-extensions-executor.md) adds a CA setting to PMM Extensions' connection to PMM, so that the connection can verify PMM Server's certificate where that certificate names the address PMM Extensions dials. Which certificate the bundle uses is open question [O5](../spec.md#13-risks-and-open-questions) ([spec §13](../spec.md#13-risks-and-open-questions)); this plan adds no step for it.
- **Release numbers in shipped text.** Shipped strings name the releases, 3.12.0 and 3.13.0, as PMM's deprecation notices do (`documentation/docs/release-notes/3.4.0.md:72-76`) [V]. If the release moves, every row below changes together:

  | # | Shipped text | Task |
  |---|---|---|
  | 1 | pmm-managed's start-up warning when `PMM_ENABLE_NOMAD` is set (`managed/utils/envvars/parser.go`) | 3 |
  | 2 | The comments for `PMM_ENABLE_NOMAD` in `docker-compose.yml`, `.env.example`, `.env.dev.example` | 3 |
  | 3 | `documentation/docs/reference/nomad.md` | 6 |
  | 4 | The fallback note in `documentation/docs/apps/deploy-pmm-extensions.md` | 6 |
  | 5 | The deprecation note on the GC section of `…/docker/env_var.md` | 6 |
  | 6 | The Nomad row of `documentation/docs/reference/pmm_components_and_versions.md` | 6 |
  | 7 | The improvement entry and the highlight draft in `documentation/docs/release-notes/next.md` | 7 |
  | 8 | `documentation/api/release-notes/3.12.0.md`, its name and its text | 7 |
  | 9 | The `nomad` target in `documentation/api/extensions-tasks/connectivity-check.md` | 7 |
  | 10 | percona/pmm-extensions `sidecar/README.md` (the fallback setting) | 1 |
  | 11 | percona/pmm-extensions `docs/customer/nomad-driver-deployment.md` (the note at the top) | 6 |
  | 12 | percona/pmm-extensions `changelog.d/PMM-15981.changed.md` | 1 |
  | 13 | The message that refuses a `nomad` task, if [plan 04](04-extensions-executor.md)'s text names a release | 1 (check only) |
- **Docs ride with the code** ([00](00-roadmap.md#branch-and-pr-rules)):
  - `documentation/docs/` is published from the release branch of the latest GA version, so pages changed here stay private until 3.12.0 ships (`AGENTS.md:246`) [V].
  - `documentation/api/` and the Swagger spec are uploaded from `main` on push (`.github/workflows/api-docs.yml:33-41`) [V]. [Task 7](#task-7-release-notes-and-api-docs)'s API pages go public at the merge in [Task 9](#task-9-merge-the-integration-branch-into-main), not at the release.
- **Release-note rules** are those of `documentation/AGENTS.md:173-197` [V]: entries in `documentation/docs/release-notes/next.md`, one bullet per ticket under `## 📈 Improvements`; the doc team writes the highlights.

## Review Focus

- **An upgraded install that had `PMM_ENABLE_NOMAD=1`** keeps a Nomad server and a Nomad client on every host that nothing uses any more. Expected: the start-up warning, the release notes and `reference/nomad.md` say how to switch it off once every host reads `can_run` ([Tasks 3](#task-3-pmm-server-with-and-without-pmm_enable_nomad-in-3120), [6](#task-6-user-documentation), [7](#task-7-release-notes-and-api-docs)).
- **A host below the version gate on an install that uses the new default.** Expected: the host list says "too old", a run for it is `not_started`, and the docs name the fallback ([Tasks 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback), [6](#task-6-user-documentation)).
- **The fallback is two settings.** Expected: every place that names it names both ([Tasks 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback), [3](#task-3-pmm-server-with-and-without-pmm_enable_nomad-in-3120), [6](#task-6-user-documentation), [7](#task-7-release-notes-and-api-docs)).
- **A stored task that is a Nomad job, on the bundle's default.** Expected: its dispatch is refused with the message, a 400 on the API and a FAILED history on the periodic path; with the fallback set it runs on Nomad ([Task 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback)).
- **Runs in flight at the switch.** Expected: a run that Nomad dispatched before the upgrade is followed to its final state by the Nomad executor; only new runs use the new default ([Task 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback)).
- **The side-car calling `/v1/scripts` without the second token** gets 403 ([plan 02](02-managed-runs-api.md)). Expected: the bundled side-car always sends it, keyed with the internal token it shares with pmm-managed ([Task 2](#task-2-side-car-wiring-pmm-endpoint-token-and-the-second-token)).
- **A release number in a shipped string that the table above does not list.** Expected: none; the expansion greps the diff for `3.12` and `3.13` (Global Constraints).

---

### Task 1: The new executor is the bundle's default; the fallback

**Files:**
- Modify: percona/pmm-extensions `sidecar/settings.yaml` (the `TASKS:` block at `:324-337`: `DEFAULT_BACKEND: pmm_agent`, beside the `NOMAD:` block, which stays for the fallback)
- Modify: percona/pmm-extensions `sidecar/README.md` (the settings tables at `:66-67`, `:188-190`)
- Create: percona/pmm-extensions `changelog.d/PMM-15981.changed.md`
- Test: percona/pmm-extensions `tests/sidecar/test_embedded_settings.py`, `tests/app/tasks/test_celery.py`, `tests/app/tasks/test_routes.py`

**Interfaces:**
- `TASKS.DEFAULT_BACKEND` and `TaskBackendEnum.PMM_AGENT` (`pmm_agent`), as [plan 04](04-extensions-executor.md) defines them ([00](00-roadmap.md#pmm-extensions-plan-04)). Environment form: `TASKS__DEFAULT_BACKEND`, the side-car's `__`-nested convention (percona/pmm-extensions `sidecar/settings-env.sh:2-3`) [V].
- Values: `pmm_agent`, the bundle's default; `nomad`, the fallback, 3.12.0 only.

**Steps:**
- Write the failing tests with the embedded profile:
  - `TASKS.DEFAULT_BACKEND` resolves to `pmm_agent`; with `TASKS__DEFAULT_BACKEND=nomad` it resolves to `nomad`, and the Nomad executor's settings validate.
  - The four seeded kinds are seeded with `pmm_agent`.
  - A run dispatched with `nomad`, then a restart with `pmm_agent` as the default: the Nomad executor syncs the run until it is final, and the next run of the same kind goes through pmm-agent.
  - A task whose `data` is a Nomad job (stored through `POST /`, percona/pmm-extensions `app/tasks/routes.py:174`) [V]: with the default `pmm_agent`, the execute route answers 400 with the message and a periodic run saves a FAILED history with it; with `TASKS__DEFAULT_BACKEND=nomad` it is dispatched to Nomad.
  - With the default `pmm_agent` and no Nomad run open, no certificate-expiry beat entry and no finishing probe run.
- Set `DEFAULT_BACKEND: pmm_agent` in `sidecar/settings.yaml`. Leave `TASKS.NOMAD` and the `TASKS__NOMAD__*` exports (percona/pmm-extensions `sidecar/settings-env.sh:126`, `:148-152`, `:165-167`) in place: the fallback needs them.
- Check that [plan 04](04-extensions-executor.md)'s refusal message names no release, or add it to row 13 of the Global Constraints table.
- Document in `sidecar/README.md`: the setting, both values, that `nomad` is removed in 3.13.0, and the PMM Server half of the fallback.
- Write the changelog fragment: the bundle runs tasks through pmm-agent; the fallback and its two settings; Nomad-backed tasks need the fallback.

### Task 2: Side-car wiring: PMM endpoint, token and the second token

**Files:**
- Modify: percona/pmm-extensions `sidecar/settings.yaml` (the `TASKS.PMM_AGENT` block [plan 04](04-extensions-executor.md) adds)
- Modify: percona/pmm-extensions `sidecar/settings-env.sh` (only if [plan 04](04-extensions-executor.md)'s settings need a canonical name in `blank_cleared_names`, `:121-129`)
- Modify: percona/pmm-extensions `sidecar/README.md` (the `BASE_URL` row, `:233`)
- Modify: `.env.example` (the `PMM_EXTENSIONS_BASE_URL` comment, `:76-79`), `docker-compose.yml` (the `BASE_URL` comment, `:190`)
- Test: percona/pmm-extensions `tests/sidecar/test_settings_env.py`, `tests/sidecar/test_entrypoint.py`

**Interfaces:**
- Where each input comes from in the bundle:

  | Input | Source |
  |---|---|
  | PMM endpoint | `PMM.ENDPOINT: https://pmm-server:8443` (percona/pmm-extensions `sidecar/settings.yaml:81`) [V], or `EXTENSIONS_PMM_ENDPOINT` → `PMM__ENDPOINT` (percona/pmm-extensions `sidecar/settings-env.sh:158-163`) [V] |
  | Service-account token | Minted by percona/pmm-extensions `sidecar/grafana_service_account.py` and fanned out to `PMM__API_KEY` by `export_grafana_token` (percona/pmm-extensions `sidecar/entrypoint.sh:70-73`, `sidecar/settings-env.sh:148-152`) [V], or given as `EXTENSIONS_GRAFANA_TOKEN` |
  | Internal token | PMM Extensions' `settings.EXTENSIONS_INTERNAL_TOKEN`, derived from the side-car's `SECRET_KEY` unless set explicitly (percona/pmm-extensions `app/core/config.py:774`, `:842-875`) [V]. On a single PMM Server with the built-in PostgreSQL, pmm-managed derives the same internal token from the same secret (`managed/services/om/extensions_connection.go:57-66`) [V]. In PMM HA and with an external PostgreSQL the secret is not shared (`build/ansible/roles/extensions/files/extensions-secrets:146-149`) [V], and the internal token is `PMM_EXTENSIONS_TOKEN` on pmm-managed's side, the same value on every replica |
- The second token: header `X-PMM-Scripts-Token`, HMAC-SHA256, hex, keyed with the internal token, over the label `pmm-managed-scripts-token` ([00](00-roadmap.md#pmm-managed-plan-02)). One rule in the bundle and outside it; it is never a setting of its own ([plan 04 Task 3](04-extensions-executor.md#task-3-the-client-for-scriptsservice-and-its-test-stub)).
- `BASE_URL` builds the artifact address that a Nomad host downloads a snippet from (percona/pmm-extensions `app/extensions/apps/framework/script_helpers.py:143-168`) [V]; it has no other reader in percona/pmm-extensions (`get_base_url`, `app/extensions/deps.py:82-91`) [V]. Under `pmm_agent` the tasks service reads artifacts from PMM Extensions' internal address ([plan 04](04-extensions-executor.md)), and the host fetches nothing ([spec §8.2](../spec.md#82-the-four-task-kinds)). So `BASE_URL` is needed only for the Nomad fallback.

**Steps:**
- Write the failing tests: with the embedded profile and a `SECRET_KEY` file under `SECRETS_DIR`, the executor's requests carry `Authorization: Bearer <PMM__API_KEY>` and the `X-PMM-Scripts-Token` that [plan 02](02-managed-runs-api.md)'s fixed test vector gives for the same internal token; the same with `EXTENSIONS_INTERNAL_TOKEN` set explicitly; no new secret reaches the environment of a supervised program (the rule at percona/pmm-extensions `sidecar/entrypoint.sh:25-30`).
- Wire `TASKS.PMM_AGENT` to `settings.PMM`: no second endpoint and no second token variable.
- Rewrite the `BASE_URL` texts in `sidecar/README.md:233`, `.env.example` and `docker-compose.yml`: what it is for (the Nomad fallback's downloads), and that the default executor does not need it.

### Task 3: PMM Server with and without `PMM_ENABLE_NOMAD` in 3.12.0

**Files:**
- Modify: `managed/utils/envvars/parser.go` (a deprecation warning beside the one at `:363-368`)
- Modify: `docker-compose.yml` (comment at `:12`, `PMM_ENABLE_NOMAD` at `:34`), `.env.example` (`:18-19`, `:26`, `:71-72`), `.env.dev.example` (`:13-14`, `:23`)
- Test: `managed/utils/envvars/parser_test.go`

**Interfaces:**
- One warning appended to `warns` when `PMM_ENABLE_NOMAD` is true: Nomad is deprecated in 3.12.0 and removed in 3.13.0, and PMM Extensions does not need it. The public-address warning stays.
- `IsNomadEnabled` (`managed/models/settings.go:199-202`) and its callers stay as they are.
- Behavior in 3.12.0, unchanged in code:

  | Install | PMM Server | Hosts | Tasks |
  |---|---|---|---|
  | `PMM_ENABLE_EXTENSIONS` set, `PMM_ENABLE_NOMAD` not set | No Nomad server (`managed/services/supervisord/supervisord.go:125-131`) [V] | No Nomad client: `IgnoreNomad` drops the row from `SetState` (`managed/services/agents/state.go:225`) [V] | Through pmm-agent on hosts at or above the gate |
  | Both set, with a public address | Nomad server as today | A Nomad client on every pmm-agent at or above 3.2.0 (`managed/services/agents/registry.go:526-544`) [V] | Through pmm-agent, or through Nomad with the fallback. The Nomad clients run, and hold their memory ([spec §4.1](../spec.md#41-memory)), whether or not they are used |
  | `PMM_ENABLE_NOMAD` set, `PMM_ENABLE_EXTENSIONS` not set | Nomad server as today | Nomad client as today | No script runs: the API answers as an unknown path does ([spec §9.1](../spec.md#91-who-can-start-a-run)) |

**Steps:**
- Write the failing tests: `PMM_ENABLE_NOMAD=1` gives the deprecation warning and still sets `EnableNomad`; `PMM_ENABLE_NOMAD=0` and an unset variable give none. Then add the warning.
- Rewrite the compose and `.env` comments: `PMM_ENABLE_NOMAD` is not needed for PMM Extensions; it is the fallback's server half until 3.13.0.
- Write the operator's steps for [Task 6](#task-6-user-documentation): confirm every host reads `can_run` in PMM Extensions' host list, then remove `PMM_ENABLE_NOMAD` and the published port 4647, and recreate the container. The hosts' Nomad clients then stop through the existing "Nomad disabled" path (`agent/agents/supervisor/supervisor.go:574-611`; `documentation/docs/reference/nomad.md:75`) [V].

### Task 4: Texts in pmm-managed's `om` service and its API that say "Nomad"

**Files:**
- Modify: `api/om/v1/om.proto` (`executor_host` at `:536-537`; `:856`; `:870`; the OpenAPI description of the bootstrap call at `:1320`; `:1351`)
- Modify: `managed/services/om/bootstrap_client.go` (`:28`), `managed/services/om/inventory.go` (`:627`)
- Regenerate: `make gen`

**Interfaces:** no field, number or behavior changes. `executor_host` keeps its meaning: the executor's name for the host, which is the PMM node name under both executors (`managed/services/agents/nomad.go:35`; [spec §8.5](../spec.md#85-hosts-logs-files-stop)) [V].

**Steps:**
- Rewrite each text that says Nomad in terms of "task execution", in wording that is true for both executors: for example "the task execution host that serves it" for `executor_host`, "a refresh starts one task per host", "installs MongoDB through task execution on the host".
- Run `make gen`; `buf breaking` passes inside it (`api/Makefile:6`) [V].
- Leave `managed/services/om/inventory_test.go` as it is: its four Nomad mentions (`:578`, `:918`, `:941`, `:964`) assert that a message does not mention Nomad [V], which is what this task keeps true.

### Task 5: The PMM UI

**Files:**
- Modify: `ui/packages/plugins/om/src/components/NotOnboardedDialog.tsx` (`:28`, the checklist at `:84-112`, the link at `:122`), `ui/packages/plugins/om/src/constants.ts` (`NOMAD_DOC_URL` at `:509-510`; `PMM_AGENT_AUTOMATION_MIN_VERSION` and its comment at `:516-522`)
- Modify: `ui/packages/plugins/om/src/inventoryHooks.ts` (`:29`, `:445`), `ui/packages/plugins/om/src/topologyHooks.ts` (`:29`), `ui/packages/plugins/om/src/NodesPage.tsx` (`:861`)
- Modify: `ui/packages/extensions/framework/src/components/HostSelector/isHostMismatch.ts` (`:22`), `ui/packages/extensions/framework/src/components/HostSelector/resolveExecutorHostForService.ts` (`:30`), `ui/packages/extensions/framework/src/hooks/useTaskHistoryFiles.ts` (`:32`)
- Modify: `ui/packages/extensions/api/specs/*.json` and `ui/packages/extensions/api/src/generated/*`, regenerated after [plan 04](04-extensions-executor.md)'s PR is merged
- Test: `ui/packages/plugins/om/tests/NotOnboardedDialog.test.tsx`, `ui/packages/plugins/om/tests/NodesPage.test.tsx`

**Interfaces:** none.

**Steps:**
- Write the failing test for the dialog's new checklist: it holds what is true under either executor: PMM Client connected and at or above the version gate, task execution enabled for the install, and the reason PMM Extensions' host list gives for the node. Today it lists Nomad's needs: `iproute`, writable cgroups, pmm-agent 3.2.0, a server flag with a public address (`NotOnboardedDialog.tsx:84-112`) [V]; those move to the documentation page it links to ([Task 6](#task-6-user-documentation)).
- Rewrite every UI text that says Nomad in terms of "task execution", true for both executors; the UI does not know which backend PMM Extensions uses.
- Make `PMM_AGENT_AUTOMATION_MIN_VERSION` mirror `ScriptRunsSupportVersion` ([00](00-roadmap.md#pmm-managed-plan-02)), the gate of the default executor, and say so in its comment. Point the link at the page that covers task execution ([Task 6](#task-6-user-documentation)), not at `reference/nomad.md`.
- Leave the inventory's "Nomad agent" label (`ui/apps/pmm/src/pages/inventory/agents/Agents.messages.ts:35`) and type (`ui/apps/pmm/src/types/agent.types.ts:37`): the rows still exist in 3.12.0. [Plan 07](07-remove-nomad.md) removes them.
- Once [plan 04](04-extensions-executor.md)'s PR is merged, regenerate the extensions API types in two steps (`ui/packages/extensions/api/README.md:144-153`) [V]: in percona/pmm-extensions, `python scripts/dump_openapi.py`; copy the four `specs/*.json` into `ui/packages/extensions/api/specs/`; then `pnpm --filter @pmm-extensions/api codegen` and `pnpm --filter @pmm-extensions/api exec oxfmt --write src/generated`.
- Run `pnpm --filter @pmm/plugins-om lint` and `pnpm --filter @pmm/plugins-om test` (`ui/packages/plugins/om/package.json:2`, `:11`, `:13`) [V].

### Task 6: User documentation

**Files:**
- Modify: `documentation/docs/reference/nomad.md` (whole page; the promise at `:121`)
- Modify: `documentation/docs/apps/deploy-pmm-extensions.md` (`:38-44`, `:71`, `:74`, `:90`, `:143`, `:145`, `:163`, `:176`, `:194`, `:197`, `:213`)
- Modify: `documentation/docs/install-pmm/install-pmm-server/deployment-options/docker/env_var.md` (`:208`, the GC section at `:237-272`)
- Modify: `documentation/docs/apps/mysql-backup.md` (`:45`, `:263`), `documentation/docs/use/mongodb-operations.md` (`:17-18`, `:64`)
- Modify: `documentation/docs/reference/index.md` (`:37`, `:64`, `:109`), `documentation/docs/reference/pmm_components_and_versions.md` (`:13`)
- Modify: percona/pmm-extensions `README.md`, `docs/customer/pmm-extensions-user-guide/README.md`, `docs/customer/nomad-driver-deployment.md` (a note at the top: the fallback only, until 3.13.0)

**Interfaces:** none.

**Steps:**
- Rewrite `reference/nomad.md`: deprecated in 3.12.0 and removed in 3.13.0; PMM Extensions does not need it; the fallback's two settings; how to switch Nomad off ([Task 3](#task-3-pmm-server-with-and-without-pmm_enable_nomad-in-3120)); what PMM 3.13.0 deletes (`/srv/nomad`, `<base>/data/nomad`; [spec §10.3](../spec.md#103-old-and-new-together)). Drop the sentence at `:121`, "Nomad will remain within PMM …" ([00](00-roadmap.md#release-gate)).
- Rewrite `deploy-pmm-extensions.md`:
  - drop `PMM_ENABLE_NOMAD=1`, `PMM_PUBLIC_ADDRESS` as a requirement, and `-p 4647:4647` from the three install forms, and the warning at `:176` that tasks fail without the public address;
  - drop `BASE_URL` from the three install forms (`:90`, `:163`, `:213`), and say in the fallback note that it is needed only there ([Task 2](#task-2-side-car-wiring-pmm-endpoint-token-and-the-second-token));
  - add: PMM Client at or above the version gate on every host that runs tasks; Python's `venv` module on hosts that run the two Python kinds, without which a run reads as not launchable, with the reason; the `scripts.disabled` switch on a host ([plan 03](03-containment.md));
  - add the fallback note: its two settings, for 3.12.0 only.
- Rewrite `env_var.md`: `PMM_PUBLIC_ADDRESS` is not needed for tasks; the GC section is deprecated with Nomad. Correct its defaults table (`:249-253`: 90, 90, 5000) to the code (`managed/cmd/pmm-managed/main.go:843-866`: 80, 70, 50) [V] while the section lives.
- Rewrite `mysql-backup.md`: at `:45`, the execution host needs PMM Client at or above the gate, not "Nomad enabled"; at `:263`, output files follow `keep_files_for` on the host and PMM Extensions' own retention ([spec §6.2](../spec.md#62-what-a-run-is)).
- Drop the port 4647 step (`:18`) and table row (`:64`) from `mongodb-operations.md`.
- Rewrite the architecture in `reference/index.md`: pmm-agent runs PMM Extensions' tasks over its existing connection; Nomad is deprecated. In `pmm_components_and_versions.md:13`, correct Nomad v2.0.0 to the pinned v2.1.1 (`build/scripts/vars:59-60`) [V] and mark it deprecated.
- Preview with `make doc-build-preview` (`documentation/AGENTS.md`, "Adding a page").

### Task 7: Release notes and API docs

**Files:**
- Modify: `documentation/docs/release-notes/next.md` (`## 📈 Improvements`; a draft highlight for the doc team; `## 🧩 API changes`, as at `next.md:65`)
- Create: `documentation/api/release-notes/3.12.0.md`, in the form of `documentation/api/release-notes/3.11.0.md`
- Modify: `documentation/api/extensions-tasks/connectivity-check.md` (the target list at `:21`, the table at `:36`, the examples at `:46`, `:58`)

**Interfaces:**
- Connectivity targets ([plan 04](04-extensions-executor.md)): `task_execution` is the existing shared `/hosts/` probe, for the default backend. `nomad` stays while Nomad ships, and answers "not in use" when the default backend is not `nomad`.

**Steps:**
- Write the improvement entry, one bullet with the epic's link: PMM Extensions runs tasks through pmm-agent; no public address, port 4647 or Nomad client on hosts is needed; each run at most once, with its true outcome. Link `../apps/deploy-pmm-extensions.md`.
- Draft the deprecation highlight for the doc team, after `release-notes/3.4.0.md:72-76`: Nomad, its `/nomad/` API, `PMM_ENABLE_NOMAD`, `PMM_NOMAD_GC_*`, the `nomad-agent` inventory type and `pmm-admin inventory change agent nomad-agent` are removed in 3.13.0. What to do: [Task 3](#task-3-pmm-server-with-and-without-pmm_enable_nomad-in-3120)'s steps. Link `../reference/nomad.md`.
- Write the API changes: `/nomad/` is deprecated; `AGENT_TYPE_NOMAD_AGENT` and `NomadAgent` stay in the API and will not be returned from 3.13.0 ([spec §10.3](../spec.md#103-old-and-new-together)). No entry for `/v1/scripts`: only PMM Extensions can call it ([spec §9.1](../spec.md#91-who-can-start-a-run)), and it has no public reference.
- Rewrite `connectivity-check.md` for the two targets of Interfaces, and say that `nomad` goes in 3.13.0.

### Task 8: Feature Build and PR

**Files:** none beyond [Tasks 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback) to [7](#task-7-release-notes-and-api-docs).

**Interfaces:** none.

**Steps:**
- Merge `origin/PMM-15976-script-runs` into `PMM-15981-switch-over`; run `make gen` and `make prepare-pr`.
- Build a Feature Build with this branch and the percona/pmm-extensions commit of [Tasks 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback) and [2](#task-2-side-car-wiring-pmm-endpoint-token-and-the-second-token). On it, check live: a task runs through pmm-agent on a fresh install with only `PMM_ENABLE_EXTENSIONS` set; the same install with `PMM_ENABLE_NOMAD=1`, a public address, 4647 published and `TASKS__DEFAULT_BACKEND=nomad` runs it through Nomad.
- Grep the two diffs for `3.12` and `3.13`; every hit is a row of the Global Constraints table.
- Open the PR `PMM-15981 Make pmm-agent the default task executor` into the integration branch, with the Feature Build link.

### Task 9: Merge the integration branch into `main`

**Files:** none; the merge of `PMM-15976-script-runs` into `main`.

**Interfaces:** none.

**Preconditions:**
- [Plan 06](06-verification.md)'s release gate passed ([plan 06 Task 10](06-verification.md#task-10-release-gate)), with its evidence on [PMM-15982](https://perconadev.atlassian.net/browse/PMM-15982) ([00](00-roadmap.md#release-gate)).
- Every finding of the implementation security review closed or accepted in writing ([plan 06 Task 9](06-verification.md#task-9-implementation-security-review)).
- Every PR into the integration branch after [plan 06](06-verification.md)'s runs has been re-checked against the cases it touches.
- The docs rules re-checked on the `main` being merged into: `documentation/docs/` still published from the release branch (`AGENTS.md:246`, `.github/workflows/documentation.yml`), `documentation/api/` still uploaded on push (`.github/workflows/api-docs.yml`).

**Timing:** agreed with the PMM release manager. The release-candidate job cuts `pmm-3.12.0` from `main` and turns `next.md` into `3.12.0.md` (`documentation/AGENTS.md:193`) [V], so the merge lands shortly before that cut. [Task 7](#task-7-release-notes-and-api-docs)'s `documentation/api/` pages go public at the merge.

**Steps:**
- Merge `main` into the integration branch; regenerate, never hand-merge, generated files; get CI and a Feature Build green; check that `git rev-list --count origin/PMM-15976-script-runs..origin/main` is `0`.
- Open the PR into `main`, titled `PMM-15976 Run PMM Extensions tasks in pmm-agent` (at most 50 characters), listing every PR merged into the integration branch. Merge with **Squash and merge** (`dev/docs/process/GIT_AND_GITHUB.md:54`) [V]. Delete the branch.
- Run the regression on a `main` build: [Task 8](#task-8-feature-build-and-pr)'s checks again, and `GET /v1/scripts/hosts` answering as an unknown path does on a server without `PMM_ENABLE_EXTENSIONS` ([plan 02](02-managed-runs-api.md)).
- Release the percona/pmm-extensions version that pairs with 3.12.0, carrying [Tasks 1](#task-1-the-new-executor-is-the-bundles-default-the-fallback) and [2](#task-2-side-car-wiring-pmm-endpoint-token-and-the-second-token); keep the two images on the same version (`.env.example`'s note on mismatched images) [V].
