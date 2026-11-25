# Plan 03: Containment and host-side controls (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans). This plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts.

**Goal:** Each run gets a control group of its own where the packaged unit declares delegation, so that a stop and the end of a run reach every process of the run, a run cannot fork without bound, and a run that fills its memory is killed alone and as a whole. pmm-agent clears the groups a previous life left behind, runs a script as another OS user when asked, refuses every run when the host's owner switches script runs off, and reports what it can do in `ListRunsResponse`.

**Architecture:** Three lines in PMM Client's systemd unit delegate pmm-agent's control group to it, say so to pmm-agent through a variable, and keep the unit running through a memory kill. At start-up, before any exporter or run starts, pmm-agent checks the variable and that its group can be used, moves itself into a child group `agent`, enables the `memory` and `pids` controllers, and kills and removes every other child group. Each run then starts directly inside a group of its own, with a process limit; plan 01's stop and end of a run gain `cgroup.kill`. Where no group can be used, pmm-agent keeps plan 01's process group, adds the environment mark, and says `contained: false`. `run_as` and `scripts.disabled` are checks in the `Manager` of plan 01 (`agent/runner/scripts`). `oom_score_adj` 1000 is set on every run by plan 01 Task 4, where the process is started, contained or not; this plan does not repeat it. Nothing changes in pmm-managed: plan 02 stores and shows what `ListRunsResponse` carries, and refuses `run_as` for a pmm-agent that is not root.

**Tech Stack:** Go 1.27, `golang.org/x/sys/unix`, `syscall.SysProcAttr` (`UseCgroupFD`, `Credential`), cgroup v2, systemd unit settings, rpm and deb packaging.

**Spec:** [spec §6.5](../spec.md#65-containment), [§6.2](../spec.md#62-what-a-run-is) (`run_as`, `memory_max`, the run directory), [§6.8](../spec.md#68-the-host-list) (`user`, `contained`, `capacity`, `queue`), [§9.1](../spec.md#91-who-can-start-a-run) (the host switch), [§11](../spec.md#11-tests) T4, T5, T11, T18; [ADR-06](../adr/ADR-06-stop-and-containment.md), [ADR-07](../adr/ADR-07-run-as-user.md), [ADR-09](../adr/ADR-09-who-may-start-a-run.md), [ADR-12](../adr/ADR-12-host-list.md); open questions O1 and O2 in [spec §13](../spec.md#13-risks-and-open-questions). Ticket PMM-15979.

## Global Constraints

- Starts after plan 01's second PR is merged into `PMM-15976-script-runs`. Branch `PMM-15979-containment` from it; one PR into it ([00](00-roadmap.md#branch-and-pr-rules)).
- The security design review reads this folder before this plan starts ([00](00-roadmap.md#plans-and-order)). ADR-06, ADR-07, ADR-09 and ADR-12 are Accepted first, and O1 (the unit settings) is answered.
- **Delegation is declared, not guessed.** pmm-agent uses run groups only when the variable `PMM_AGENT_RUN_GROUPS=1` is in its environment, set by the unit beside `Delegate=`, **and** its group files can be written. A root pmm-agent can create groups under any unit, and must not take that for delegation (ADR-06).
- **cgroup v2 only.** A host on cgroup v1, or in hybrid mode, is not contained. pmm-agent never mounts, and never writes outside its own group.
- **The unit change reaches every PMM Client host on upgrade, whether it runs scripts or not** (ADR-06). It is the only change of this epic that does.
- **What containment promises.** It bounds accidents and ordinary children: a run that fills its memory, a child that leaves its session, a fork that does not stop. A script that runs as pmm-agent's own user owns the delegated groups and can move itself out of its group; one that runs as another user cannot write the group files. It is not a wall against a script that sets out to leave it ([spec §6.5](../spec.md#65-containment)).
- The names and settings come from the [shared contract](00-roadmap.md#shared-contract): `--scripts-disabled`, `PMM_AGENT_SCRIPTS_DISABLED`, `scripts.disabled`, default false; `PMM_RUN_ID` as the environment mark; the reasons of `not_started`, word for word; the host facts of `ListRunsResponse` as plan 01 Task 1 defines them; `RunScriptPidsMax` from `api/agent/v1/scripts.go`.
- Tests that need a delegated cgroup, or root, skip themselves when the environment does not offer one, and say why. The expansion names how CI provides them: the agent job runs on an Ubuntu host (`.github/workflows/agent.yml:34`) where a delegated scope can be made with `systemd-run` [I]. They stay within the agent's 80 s per package (`agent/Makefile:64`).
- Every task ends with its own commit, `PMM-15979 Short summary` (at most 50 characters), signed off. `make gen` after any generated change, `make prepare-pr` before the PR. The sketches follow the repository's rules: no named results, no comment beside a line.

## Review Focus

- **A run fills the host's memory, with `memory_max` and without (T5: 16 takes per test host, 8 with a limit and 8 without).** Expected: the run is killed, and not the database or pmm-agent; the unit, the exporters and the other runs go on. With a limit the run's own group triggers the kill and `memory.oom.group` takes the whole run; without one, `oom_score_adj` 1000 (plan 01) makes the kernel pick the run first. The record's reason says the kill was for memory when the group's `memory.events` counted one.
- **`memory_max` on a host that is not contained.** Expected: the run is refused, and pmm-managed records `not_started` with the reason; it never runs without the limit it asked for.
- **A child that leaves its session and clears its environment (T4, the stop, the end of a run).** Expected: a stop and the end of the run end it through `cgroup.kill`; after `kill -9` of pmm-agent, no process of the run is alive 10 s after pmm-agent is back.
- **A fork bomb in a run.** Expected: it stops at 4,096 processes in the run's group; pmm-agent and the exporters can still fork.
- **Leftover run groups at start-up.** Expected: killed and removed before the first run starts; the `agent` group and pmm-agent itself untouched.
- **An exporter started after the move.** Expected: it is born in `agent`, never in a run's group, and survives every run's `cgroup.kill`.
- **A root pmm-agent under a unit that does not declare delegation** (a tarball install's own unit, an owner's replaced unit, a root container with a writable group). Expected: `contained: false`, although every group file could be written, and the log line says the variable is missing.
- **A host where groups cannot be used** (the Docker image, EL8, a unit without the settings). Expected: runs still work, `contained: false`, one log line at start-up says which check failed, and the start-up sweep by the mark runs (T18).
- **`run_as`.** Expected: on a pmm-agent that is not root, pmm-managed records `not_started` from the host facts, and pmm-agent refuses the run itself if one arrives; an unknown user ends `prepare_failed`; a known user runs with its uid, gid, supplementary groups and home directory, from a `TempDir` that pmm-agent first created with mode 0700.
- **`scripts.disabled` (T11).** Expected: every `StartJobRequest{run_script}` refused with the reason; `ListRunsResponse.disabled` true; no message from the server can change it.
- **An upgrade from a 3.11 package.** Expected: the new unit is in force after the package's own restart, and pmm-agent reports `contained: true`.

---

### Task 1: The unit settings

**Files:**
- Modify: `build/packages/config/pmm-agent.service` (today `[Service]` holds `Type=simple`, `ExecStart`, `Restart=always`, `RestartSec=2s`) [V]
- Read, not changed: `build/packages/rpm/client/pmm-client.spec` (installed at :129, listed as `%config` at :213, `daemon-reload` and start on upgrade at :163-166), `build/packages/deb/rules` (`dh_systemd_start --restart-after-upgrade` at :75-76), `build/scripts/build-client-packages:374` (the deb copy of the unit)

**Interfaces:**

```
[Service]
Delegate=memory pids
Environment=PMM_AGENT_RUN_GROUPS=1
OOMPolicy=continue
```

**Steps:**
- Add the three lines. systemd already reports `OOMPolicy=continue` once `Delegate=` is set (measured on Ubuntu 24.04, systemd 255) [V]; the unit states it so that nobody has to know that ([spec §6.5](../spec.md#65-containment)).
- `OOMPolicy=` needs systemd 243 or later, and `cgroup.kill` Linux 5.14 or later [I]. On a Feature Build, for each distribution the packages support (`documentation/docs/install-pmm/install-pmm-client/package_manager.md:25-28`: RHEL-compatible 8, 9, 10; Debian 12, 13; Ubuntu 22.04, 24.04, 26.04; Amazon Linux 2023), record in the expansion's PR: `systemctl show pmm-agent -p Delegate -p DelegateControllers -p OOMPolicy -p Environment`, `systemctl --version`, `uname -r`, `stat -fc %T /sys/fs/cgroup`, and whether `cgroup.kill` exists in pmm-agent's group.
- Expected [I, not measured]: RHEL-compatible 8 has systemd 239, a 4.18 kernel without `cgroup.kill`, and cgroup v1 by default. It gets the fallback (`contained: false`), and its systemd logs a warning for the unknown `OOMPolicy=` line and ignores it. The others are expected to be contained.
- Check that both packages put the new unit in force on upgrade: rpm runs `daemon-reload` and starts the unit in `%post` (:163-166), deb restarts it after upgrade. A host whose owner edited the packaged unit: rpm treats it as `%config` (without `noreplace`), so the package's unit replaces it and the edited copy is kept as `.rpmsave` [I, rpm behavior]. Write that in the upgrade notes (Task 7).
- Commit `PMM-15979 Delegate pmm-agent's control group`.

### Task 2: Detect a declared, usable group; set up `agent`; sweep at start-up

**Files:**
- Create: `agent/runner/scripts/cgroup_linux.go`, `agent/runner/scripts/cgroup_other.go` (`//go:build !linux`), test `agent/runner/scripts/cgroup_linux_test.go`
- Modify: `agent/commands/run.go` (once per process, before the loop at :65, so before the supervisor starts any exporter and before `scripts.New`); `agent/runner/scripts/manager.go` (`Config` gains the result)

**Interfaces:**

```go
// cgroups is pmm-agent's delegated group. A nil *cgroups means runs are not contained.
type cgroups struct {
	base string
}

// setupCgroups checks that delegation is declared and the host can use it, moves every process of
// pmm-agent's group into base/agent, enables memory and pids for the groups beside it, and kills
// and removes every other child group. When a check fails it returns nil and the reason, which
// pmm-agent logs once.
func setupCgroups(procSelfCgroup, cgroupRoot string, declared bool) (*cgroups, string, error)

// sweepMarked kills every process whose environment carries a PMM_RUN_ID entry. It is the start-up
// sweep where runs are not contained.
func sweepMarked(procRoot string) (int, error)
```

**Steps:**
- `declared` is `os.Getenv("PMM_AGENT_RUN_GROUPS") == "1"`. The checks, in order, each with its own reason text: the variable is set; `/proc/self/cgroup` has a single `0::<path>` line (cgroup v2); the file system at `cgroupRoot` (`/sys/fs/cgroup`) is `cgroup2`; `<cgroupRoot><path>` is writable by pmm-agent (`mkdir agent` succeeds or `agent` exists); its `cgroup.controllers` lists `memory` and `pids`; `agent/cgroup.kill` exists.
- Move each pid of `<base>/cgroup.procs` into `<base>/agent/cgroup.procs`, then write `+memory +pids` to `<base>/cgroup.subtree_control`. The order is forced: a group with processes of its own cannot enable controllers for its children [I, kernel cgroup v2 rules]. The spike did the same steps by hand, as the non-root `pmm-agent` user, with `Delegate=memory pids` in a drop-in (cgroup probe on Ubuntu 24.04, 2026-11-14) [V].
- If pmm-agent's own path already ends in `/agent` (pmm-agent started again inside the group it set up), `base` is its parent [I].
- The sweep where contained: every child of `base` other than `agent` is a run group of a previous life. Write `1` to its `cgroup.kill`, wait until its `cgroup.events` reads `populated 0`, `rmdir` it. When systemd restarts the unit, the unit's groups are already gone (seen in the spike when the unit restarted after a memory kill) [V]; the sweep covers the rest.
- The sweep where not contained: `sweepMarked` kills every process whose `/proc/<pid>/environ` carries a `PMM_RUN_ID=` entry, before the first run ([spec §6.5](../spec.md#65-containment)). A non-root pmm-agent can read only its own user's `environ`, so that is all it finds there.
- Tests:
  - on a delegated group given by an environment variable named in the expansion (skip otherwise): a pre-made child `old-run` with a `sleep` in it → killed and removed; `agent` holds the test process afterward;
  - `declared` false on the same writable group → nil, reason names the variable, and nothing in the group changed;
  - each other failed check gives its reason, using a fake `procSelfCgroup` file and a `cgroupRoot` on `tmpfs`;
  - `sweepMarked` on the test's own processes: a `sh -c 'exec sleep 300'` started with `PMM_RUN_ID=x` in its environment is gone; one without the mark is left alone.
- Commit `PMM-15979 Set up run groups at start-up`.

### Task 3: A group per run; the stop; the end of a run; `memory_max`

**Files:**
- Modify: `agent/runner/scripts/process_linux.go`, `agent/runner/scripts/manager.go`
- Test: `agent/runner/scripts/process_linux_test.go`, `agent/runner/scripts/cgroup_linux_test.go`

**Interfaces:**

```go
// runGroup is one run's control group.
type runGroup struct {
	path string
	fd   int
}

// newRunGroup creates base/run-<job_id> with pids.max and memory.oom.group set, and memory.max when
// memoryMax > 0.
func (g *cgroups) newRunGroup(jobID string, memoryMax int64) (*runGroup, error)

// kill writes 1 to cgroup.kill and waits for "populated 0" in cgroup.events.
func (r *runGroup) kill(ctx context.Context) error

// remove closes the directory descriptor and removes the group.
func (r *runGroup) remove() error

// oomKills reads oom_kill from memory.events.
func (r *runGroup) oomKills() (uint64, error)
```

**Steps:**
- The group is named `run-<job_id>`, so that no job id can be `agent`.
- The group's limits: `pids.max` = `RunScriptPidsMax` (4,096); `memory.oom.group` = 1, so that a memory kill takes the whole run, not one process of it; `memory.max` = `memory_max` when given.
- The process starts inside its group: `SysProcAttr.UseCgroupFD = true`, `CgroupFD = runGroup.fd` (clone into the group, Linux 5.7 or later [I]). It is never in `agent`, not even for an instant, so nothing it forks can be born outside the run's group. The spike moved a started process by writing `cgroup.procs` [V]; that leaves a window this avoids. `oom_score_adj` stays as plan 01 Task 4 sets it: its launcher is what starts in the group, and the program replaces it there.
- The stop of plan 01 becomes: SIGTERM to the process group, the grace period, then `cgroup.kill` on the run's group ([spec §6.5](../spec.md#65-containment)).
- **The end of a run, however it ends:** everything still in the run's group is killed with `cgroup.kill`, and the group is removed, before the output readers' last 2 s. A task that must leave a process running hands it to the service manager (Task 7 documents it).
- Shutdown (plan 01 Task 9) kills at once; on a contained host that kill is `cgroup.kill`.
- `memory_max` on a host that is not contained: `Start` refuses the run with `memory_max needs a host where runs are contained`, which pmm-managed records as `not_started` (it also checks first, from the host facts). Plan 01 refuses every `memory_max`; this task limits the refusal to hosts where Task 2 found no usable group.
- A run whose group counted an `oom_kill` and did not exit 0 gets the reason `killed for memory (memory_max)`, or `killed for memory` when no limit was set.
- The group is created by pmm-agent and keeps pmm-agent's ownership; it is never given to the run's user (Task 5), so a script running as another user cannot raise its own limits or leave its group.
- **Not contained:** no group; plan 01's stop, and at the end of each run a kill of every process whose environment carries the run's `PMM_RUN_ID`, as the prototype's `KillLeftovers` does (`agent/runner/jobs/run_script_job.go:347-373` on `PMM-15696-proto`) [V].
- Tests (delegated group):
  - a stop reaches `setsid sh -c 'exec env -i sleep 300' &`; so does the end of a run that exits 0 with that child still running;
  - a `sleep` in `agent` survives a run's `cgroup.kill`;
  - a loop that forks `sleep` without end stops at `pids.max`, and the run is then stopped cleanly;
  - a memory hog that forks a second hog, with `memory_max` 64 MiB → `failed`, the memory reason, both hogs gone, and a second run alongside still running; `memory.oom.group` reads 1;
  - the group is gone after every outcome;
  - on a host that is not contained (a fake `procSelfCgroup`), a run with `memory_max` is refused with the reason, and a run that leaves a marked child behind loses it at its end.
- Commit `PMM-15979 Run each script in its own group`.

### Task 4: Report what the host can do

**Files:**
- Modify: `agent/runner/scripts/manager.go` (`ListRuns`), `agent/commands/run.go` (passes the user and the result of Task 2)
- Test: `agent/runner/scripts/manager_linux_test.go`

**Interfaces:** `ListRunsResponse.user`, `contained`, `disabled`, `capacity`, `queue` from plan 01 Task 1; plan 01 leaves them at zero.

**Steps:**
- `user`: the name of pmm-agent's effective user (`os/user.LookupId(strconv.Itoa(os.Geteuid()))`), or the number when it has no name. pmm-managed decides from it whether a `run_as` run can be sent (`not_started` otherwise).
- `contained`: Task 2's result, fixed for the life of the process.
- `disabled`: Task 6.
- `capacity`, `queue`: the values in force, after plan 01's defaults. `ListHosts` returns them beside `user` and `contained` ([spec §6.8](../spec.md#68-the-host-list)).
- These travel in every answer to `ListRunsRequest`, which pmm-managed sends on every connect and repeats until answered ([spec §6.4](../spec.md#64-reconnect-and-lost-runs)); plan 02 stores them.
- Test: the five fields after `New` with a fake `cgroups`, with and without `Disabled`.
- Commit `PMM-15979 Report host facts in ListRunsResponse`.

### Task 5: `run_as`

**Files:**
- Create: `agent/runner/scripts/runas_linux.go`, test `agent/runner/scripts/runas_linux_test.go`
- Modify: `agent/runner/scripts/process_linux.go` (drops plan 01's `run_as is not supported by this pmm-agent`), `agent/runner/scripts/manager.go`

**Interfaces:**

```go
// runAsUser is a resolved run_as user.
type runAsUser struct {
	cred *syscall.Credential
	home string
}

// runAs resolves name to a credential with its supplementary groups, and its home directory.
func runAs(name string) (*runAsUser, error)
```

**Steps:**
- Empty `run_as`: pmm-agent's own user, as plan 01 ([ADR-07](../adr/ADR-07-run-as-user.md)).
- **Not root:** pmm-managed records such a run `not_started` from the host facts (Task 4), with `run_as needs a pmm-agent that runs as root`. pmm-agent checks again in `Start` and refuses with the same text (plan 01 Task 6 already does; it stays).
- **Root:** `user.Lookup`, then `GroupIds()` into `Credential.Groups`; an unknown user, or a group lookup failure, ends `prepare_failed` with the reason. Any user is accepted, `root` included (ADR-07). The prototype set no supplementary groups (`run_script_job.go:263-283` on `PMM-15696-proto`) [V]; this adds them.
- **The lookup reads the host's own user files.** Release builds use `-tags 'osusergo netgo static_build'` (`agent/Makefile:28,34`) [V], so `os/user` reads `/etc/passwd` and `/etc/group` only [I]. A user that exists only in a directory service (LDAP, SSSD) is not found, and the run ends `prepare_failed`. Task 7 documents it.
- `HOME` is the named user's home directory, from the lookup; the other fixed variables of plan 01 Task 4 are unchanged.
- **Where the run directory lives.** `<TempDir>/run-script/` is created by pmm-agent when it starts (plan 01 Task 6); on a root pmm-agent it is root's, mode 0711, so the user can reach its own run directory by name and list no other. Its parent must be traversable too: `TempDir` is created 0700 by today's code (`os.MkdirAll` in `agent/utils/templates/template.go:71`, default path `<paths_base>/tmp`, `agent/config/config.go:299-301`) [V]. A root pmm-agent therefore adds search for others to `TempDir` at start-up (0711), and nothing else: every directory inside it is made 0700 by its own code (`template.go:71`, `agent/connectionchecker/connection_checker.go:135`, `agent/client/client.go:912`) [V], so nothing in it becomes listable or readable. Before a `run_as` run, pmm-agent checks that the user can search every directory from `/` to the run directory; when one blocks it, the run ends `prepare_failed` with that directory named.
- Run directories are created relative to a descriptor of `run-script/` that pmm-agent opens once at start, so that no later change to a directory above can redirect them.
- Ownership: the run directory, `out/` and every file of the request are given to the user's uid and primary gid before the start, with modes unchanged (0700 and the files' own). The run's control group is not given to the user (Task 3).
- `ReadRunFile` is unchanged: no link is followed, and only a regular file with a link count of 1 is read (plan 01 Task 7).
- The packaged pmm-agent runs as root (its unit has no `User=`, `build/packages/config/pmm-agent.service`) [V]; in the Docker image it runs as uid 1002 (`build/docker/client/Dockerfile.el9:22-23,108`) [V], where every `run_as` run is `not_started`.
- Tests (root only; skip otherwise): with a `TempDir` the test first creates as 0700, a run as `nobody` succeeds; `id -u`, `id -G` and `$HOME` inside the script match the user, which also shows that the user can execute plan 01's launcher; the files are owned by the user; `no-such-user` → `prepare_failed`; an ancestor made 0700 by the test → `prepare_failed` naming it. Not root: `run_as` → refused with the text.
- Commit `PMM-15979 Run scripts as another user`.

### Task 6: The host switch

**Files:**
- Modify: `agent/config/config.go` (`Scripts` from plan 01 Task 2 gains `Disabled bool \`yaml:"disabled,omitempty"\``; flag next to `--scripts-capacity`), `agent/runner/scripts/manager.go`, `agent/commands/run.go`, `documentation/docs/use/commands/pmm-agent.md` (the options table from :45)
- Test: `agent/config/config_test.go`, `agent/runner/scripts/manager_linux_test.go`

**Interfaces:** `--scripts-disabled` / `PMM_AGENT_SCRIPTS_DISABLED` / `scripts.disabled`, a kingpin `Bool` without a default, so that `MergeFlags` keeps the file's value (`agent/config/config.go:403-425`) [V]. `scripts.Config` gains `Disabled bool`.

**Steps:**
- When set, `Start` refuses every run with `script runs are switched off on this host`, which pmm-managed records as `not_started` (T11). `ListRunsResponse.disabled` is true.
- The value is read when pmm-agent starts, like the two limits (plan 01 Task 9); a change applies after a restart.
- The start-up sweep of Task 2 still runs: leftovers of a life before the switch are cleared.
- No message from pmm-managed changes it: the protocol has no field that sets it (plan 01 Task 1), and pmm-agent reads it only from its flags, environment and `pmm-agent.yaml` ([spec §9.1](../spec.md#91-who-can-start-a-run)). The precedent is the allow-list of PMM-15567 ADR-08.
- Add the flag to the options table of `pmm-agent.md`.
- Tests: the flag, the variable and the file each set it; a `pmm-agent setup` run through `MergeFlags` without the flag keeps `disabled: true` from the file; a refused start leaves no directory behind.
- Commit `PMM-15979 Let a host switch script runs off`.

### Task 7: Packaging, upgrade notes and docs

**Files:**
- Modify: `documentation/docs/install-pmm/install-pmm-client/package_manager.md`, `documentation/docs/install-pmm/install-pmm-client/docker.md`, `documentation/docs/install-pmm/install-pmm-client/binary_package.md`, `documentation/docs/use/commands/pmm-agent.md`, `documentation/docs/release-notes/next.md`, `agent/AGENTS.md`

**Interfaces:** none.

**Steps:**
- **rpm and deb:** the unit gains three lines; both packages reload and restart the unit on upgrade (Task 1). Runs in flight at the upgrade end as lost (ADR-03). A host whose owner edited the unit: what rpm does with it (Task 1), and that a drop-in under `/etc/systemd/system/pmm-agent.service.d/` survives upgrades. RHEL-compatible 8 is not contained.
- **The binary tarball** (`build/scripts/install_tarball`) installs no unit [V]. The doc gives the three lines for a unit the owner writes, and says that without them runs are not contained.
- **The Docker image of PMM Client:** no systemd, pmm-agent as uid 1002 (`build/docker/client/Dockerfile.el9`) [V]. Runs work and are not contained; `run_as` and `memory_max` are refused; the host list says `contained: false` (T18). The doc states the limits of that fallback, the two findings of spec §6.5.
- **PMM Server's own pmm-agent** runs under supervisord (`managed/services/supervisord/pmm_config.go:180`) [V] and is not contained.
- **What a run may leave behind:** nothing. Everything left in a run's group, or carrying its mark, is killed when the run ends. A task that must leave a process running hands it to the service manager; a task that restarts pmm-agent or upgrades PMM Client ends itself with it.
- **What containment is:** it bounds accidents and ordinary children; a script running as pmm-agent's own user can leave its group (Task 3).
- **`run_as`:** the user must exist in the host's own `/etc/passwd`; a user from a directory service is not found (Task 5). It needs a root pmm-agent.
- **The host switch:** how to set `scripts.disabled` in `pmm-agent.yaml`, that a restart of pmm-agent applies it, and that PMM Server cannot change it.
- **The release note:** one bullet under `## 📈 Improvements` in `next.md`, opening with the linked ticket key, as `documentation/AGENTS.md:173-197` asks: the unit change, why, and that it touches every host.
- **`agent/AGENTS.md`:** the package table entry of `runner/scripts` (plan 01 Task 10) gains the control groups, `run_as` and the host switch.
- On a Feature Build, as PMM-15979's own check before the PR (the release runs are plan 06's): an upgrade from the 3.11 package → `contained: true`; T5, 16 takes per test host (8 with `memory_max` 300 MiB, 8 without), the unit's `MainPID` unchanged and the exporters and the database alive after each; T4 with a session-leaving child that clears its environment; T11 with `scripts.disabled: true`; T18 on the Docker image. Record the numbers in the PR.
- Commit `PMM-15979 Document script containment`. Then the PR `PMM-15979 Contain script runs` into the integration branch.
