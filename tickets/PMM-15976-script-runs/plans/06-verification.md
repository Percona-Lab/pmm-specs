# Plan 06: Verification and release gate (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans). This plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts.

**Goal:** Every case T1 to T26 of [spec §11](../spec.md#11-tests) passes on a Feature Build, against the spec's bar, posted before the run; the cases that can be automated stay as tests; the implementation security review has no open finding; and the roadmap's release gate is checked.

**Architecture:** No product code. Two kinds of evidence:
- **Automated tests** that keep running after the release: API tests in percona/pmm `api-tests/`, extending plan 02's, and end-to-end tests in percona/pmm-qa.
- **Measured runs**: a result per case and per test host, with the build, the date, the bar, the raw readings and the verdict, posted on PMM-15982. A measured run is repeated in full whenever a PR into the integration branch changes the code it covers.

**Tech Stack:** Go API tests with the generated Swagger clients (`api-tests/AGENTS.md`); percona/pmm-qa's end-to-end suites and Jenkins jobs; Feature Builds ([00](00-roadmap.md#terms)); `/proc/<pid>/smaps_rollup` for memory; the host's firewall for network cuts; PMM HA on Kubernetes for T8.

**Spec:** [spec §11](../spec.md#11-tests), [§4](../spec.md#4-what-the-spike-measured), [§4.5](../spec.md#45-what-the-spike-left-open-for-the-pmm-agent-job), [§9.2](../spec.md#92-high-availability), [§10.3](../spec.md#103-old-and-new-together), [ADR-03](../adr/ADR-03-at-most-once.md), [ADR-06](../adr/ADR-06-stop-and-containment.md), [ADR-09](../adr/ADR-09-who-may-start-a-run.md), [ADR-13](../adr/ADR-13-high-availability.md), [ADR-14](../adr/ADR-14-mixed-versions-and-nomad-removal.md). Ticket PMM-15982.

## Global Constraints

- **Needs:** plans 01 to 05 merged into the integration branch `PMM-15976-script-runs`, and ADR-13 Accepted (00).
- **One build under test.** Every measured run names the Feature Build it used (PMM Server image, PMM Client packages and image, PMM Extensions image). A later PR into the integration branch that touches the code a case covers voids that case's result until it is run again.
- **The bar is the spec's, as written** (Task 1). It is posted on PMM-15982 before the case's first run and never changed after a run. A bar found wrong changes spec §11 through a pmm-specs PR first, and the case runs again. Where this plan adds a number that the spec does not give (how long a cut lasts, how many runs are queued), Task 1 marks it as chosen here and says why.
- **Two test hosts, for every case** unless the case says otherwise: one installed from the rpm, with SELinux enforcing, and one installed from the deb, each with the Feature Build's `pmm-client` package under systemd. Below they are the rpm host and the deb host.
- **The spike's method, unchanged**, so that figures compare ([spec §4](../spec.md#4-what-the-spike-measured)):
  - Memory: the sum, over the processes of the thing measured on that machine, of `Pss` plus `SwapPss`, read 30 minutes after a restart unless the case says otherwise. PMM Extensions' own processes are left out.
  - Timing: 20 calls one after another, from a fresh client process on another machine, to a script on the rpm host, with nothing else running. The median is the measure; the slowest is recorded beside it.
  - Timed and compared-memory runs use machines with dedicated CPUs and nothing else running. Other cases may use machines of the same shapes on shared CPUs, and say so.
- **Machine shapes** as in the spike's final round [V, spec §2]: PMM Server on a 4-CPU machine; the rpm host with 2 CPUs and 7.5 GiB; the deb host with 1 CPU and 1.9 GiB; each database host runs Percona Server 8.4 under write load. Results never name a provider, a host name or an address.
- **Who starts a run.** PMM Extensions is the caller, except in the cases that need a field PMM Extensions does not send (`memory_max`, `stdin`, `run_as`) or that test the API itself: T5, T8, T12, T13, T18 and T21 call `/v1/scripts` directly, with an Admin credential and the second token. The tester obtains the token through plan 02's test helper, which derives it on the test server and passes it to the tests as `-pmm.scripts-token` (plan 02 Task 11).
- **Public results.** The rules of pmm-specs `AGENTS.md:25` apply: a finding that is a security weakness goes to the security review's channel (Task 9), not into a public result.

## Review Focus

- **A bar paraphrased instead of copied.** Expected: Task 1's "Bar" column is spec §11's text, word for word, and every added number sits in its own column, marked as chosen here (Task 1).
- **T2 needs a script still running at the hour.** The spike's 75-minute cut ended with no script running at the hour [V, spec §4.3]. Expected: one script is still printing when the cut passes 60 minutes (Task 3).
- **T5's takes include repeats within one pmm-agent lifetime.** In the spike every repeat stopped the unit (5 of 5) [V]. Expected: of each host's 16 takes, at least 4 with a limit and 4 without are repeats without a pmm-agent restart (Task 4).
- **T8 with a demoted leader that is still alive** keeps its agents ([spec §9.2](../spec.md#92-high-availability)). Expected: the case runs with the leader killed and with the leader demoted, and the second records where each stop went (Task 7).
- **The memory gate measures what script runs add, not noise.** Expected: three readings per footing; the gate uses their medians (Task 6).
- **A green automated suite that ran no case.** Expected: each automated case has a test ID, and the job's report lists it as run (Task 2).

---

### Task 1: Cases, bars and how each is driven

**Files:** none in a code repository. The table below, the environments and the cut method are posted on PMM-15982 before any run.

**Interfaces:** none.

**Steps:**
- Post one entry per case and per test host, with the spec's bar, how the case is driven, where it lives, the task that runs it, and any number chosen here:

  | # | Bar, as written in spec §11 | Driven by | Where | Chosen here, and why |
  |---|---|---|---|---|
  | T1 | Each ran once; every line stored; the record states the true outcome | PMM Extensions | measured, Task 3 | Scripts of 900 and 2,400 lines, one ending inside the 20-minute cut and one after it: the spike's scripts, so that the result compares [V] |
  | T2 | The same | PMM Extensions | measured, Task 3 | A cut of at least 75 minutes, with one script still printing at minute 60: the case the spike did not reach |
  | T3 | Every record is final and says lost; nothing ran twice; no process is left | PMM Extensions | measured, Task 3 | none |
  | T4 | No process of the run is alive 10 s after pmm-agent is back | PMM Extensions | measured, Task 4 | none |
  | T5 | Only that run is killed: not the database, not pmm-agent. The unit, the exporters and the other runs go on. 16 takes on each test host, 8 with a limit and 8 without | `/v1/scripts` | measured, Task 4 | `memory_max` of 300 MiB for the takes with a limit: the group size of the spike's probe [V, spec §6.5] |
  | T6 | The run ends stopped after the reconnect | PMM Extensions | measured, Task 3 | A cut of at least 5 minutes: the spike's cuts lasted about 9 and 12 s [V], too short to cross a pmm-managed restart and a reconnect |
  | T7 | The script is stopped after the reconnect; new work starts | PMM Extensions | measured, Task 3 | none |
  | T8 | No run is lost or repeated; output is complete; a new run starts within 60 s of the change | `/v1/scripts`, with `PMM_EXTENSIONS_TOKEN` set to one value on every replica | percona/pmm-qa HA suite if it can be scripted there, else measured; Task 7 | Runs that print for at least 15 minutes, plus 40 queued: long enough to cross the change and the reconnect |
  | T9 | The same | PMM Extensions | measured, Task 5 | none |
  | T10 | The host list says too old; a run for it is `not_started` | PMM Extensions | percona/pmm-qa, Tasks 2 and 8 | PMM Client 3.11.0: the release before the gate |
  | T11 | The same, with its reason | PMM Extensions | percona/pmm-qa, Task 2 | none |
  | T12 | 403 | `/v1/scripts` | `api-tests/scripts/` (plan 02), Task 2 | none |
  | T13 | Not found in the record, the logs of either side, the process list, or PostgreSQL | `/v1/scripts` | percona/pmm-qa, Task 2 | none |
  | T14 | pmm-agent's memory grows by no more than the run's 4 MiB bound and 8 MiB beside it; the record says how much was dropped, and holds the start and the end of the output | PMM Extensions | measured, Task 3 | A 20-minute cut, as T1 |
  | T15 | 500 runs: no more than the prototype's 0.010 MiB a run on the host. 1,700 runs: no more than its 0.023 MiB a run on each host, and pmm-managed grows by no more than the prototype's 15.2 MiB over them. Its level 30 minutes after the last run is recorded; the prototype was not read idle | PMM Extensions | measured, Task 6 | pmm-managed's level before and after both read 30 minutes after the last run, as the method's idle reading |
  | T16 | Succeeds, with the history, the steps and the files as under Nomad. The two Python kinds need Python's `venv` module on the host; on a host without it the run reads as not launchable, with the reason | PMM Extensions | percona/pmm-qa, Task 2 | none |
  | T17 | At most 0.5 s median. The prototype measured 1.0 s, and 0.3 s with a check on each run, which is another mechanism than the calls that wait | PMM Extensions, with its open `ListRuns` call | measured, Task 6 | A fetched script, sent inline, on the rpm host: the spike's 1.0 s case [V] |
  | T18 | Runs work; the host list says `contained: false` | `/v1/scripts` | percona/pmm-qa, Task 4 | none |
  | T19 | No process of the run is alive 10 s after the stop | PMM Extensions | measured, Task 4 | none |
  | T20 | PMM Extensions' history shows the 40 lines | PMM Extensions | percona/pmm-qa, Task 3 | none |
  | T21 | The first has that user's uid, gid and groups; the second is `not_started`, with the reason | `/v1/scripts` | percona/pmm-qa, Task 2 | see the note below |
  | T22 | The host list says not answering within 30 s | system action | measured, Task 3 | none |
  | T23 | A finished run and its output are gone 7 days after its end, and not before | system action | measured, Task 2 | see Task 2 |
  | T24 | The unit has the three lines; the exporters keep running; monitoring has no gap longer than the restart | system action | measured, Task 5 | none |
  | T25 | With the two settings tasks run through Nomad; the run in flight reaches a final state under the Nomad executor | PMM Extensions | measured, Tasks 5 and 8 | none |
  | T26 | It runs on an install that has fallen back to Nomad, and is refused with the documented error on any other | PMM Extensions | percona/pmm-qa, Task 8 | fallen back: `TASKS.DEFAULT_BACKEND` is `nomad` (plan 05) |

- T21's second half: on a pmm-agent that is not root, a run with `run_as` is `not_started`, decided by pmm-managed from the host facts, with the reason "run_as needs a pmm-agent that runs as root"; a user that does not exist on a root pmm-agent is `prepare_failed` ([00](00-roadmap.md#pmm-managed-plan-02), reasons for `not_started`). The case records all three.
- Environments:
  - **Single-node:** the machine shapes of the Global Constraints, PMM Server and PMM Extensions from the Feature Build images.
  - **HA:** PMM HA with three replicas on Kubernetes from the Feature Build, `PMM_EXTENSIONS_TOKEN` set to one value on every replica ([spec §9.2](../spec.md#92-high-availability)), the two database hosts outside the cluster connecting through its load balancer.
  - **Container hosts:** 15 containers of PMM's own PMM Client image from the Feature Build, for the 1,700-run half of T15 and for T18. The spike's 15 hosts were a derived image [V]; the result says which was used.
- **Network cut:** traffic between the host and PMM Server dropped at the host's firewall, in both directions, for the case's length; the exact commands are part of each result.

### Task 2: Automated tests

**Files:**
- Modify: `api-tests/scripts/scripts_test.go`, `api-tests/scripts/helpers_test.go` (created by plan 02 Task 11)
- Modify: `api-tests/AGENTS.md` (the test organization table, `:26-36`: a `scripts/` row)
- Create: a script-runs suite in percona/pmm-qa's end-to-end tests; its path, tag and job follow that repository's layout and are fixed in the expansion [I: percona/pmm-qa is not part of this plan's code base]

**Interfaces:**
- Consumes: plan 02's `scriptsClient`, `waitFinal` and the `-pmm.scripts-token` flag [`PMM_SCRIPTS_TOKEN`] (plan 02 Task 11).

**Steps:**
- **In `api-tests/scripts/`**, add only what plan 02's tests lack. Plan 02 already covers T12 (`TestScriptsTokenRequired`), the request limits (`TestRunValidation`, `TestRunFileModes`), `not_started` for a pmm-agent that is not connected (`TestRunNotConnected`), a stop on a final run (`TestStopRun`) and the absence of the API without `PMM_ENABLE_EXTENSIONS`. Add:
  - `TestRunStdinTooLarge`: `stdin` of 1 MiB plus one byte → 400, and no new record;
  - `TestRunStartWithinDefault`: a request without `start_within` reads back 1 h;
  - `TestRunUnreadableSecret`: on a server started with `PMM_ENABLE_EXTENSIONS` whose secret file cannot be read, every `/v1/scripts` route answers as an unknown path does, and pmm-managed's log has the error. The test skips unless a flag names such a server.
  - Read the result from `go test` or `make api-test`, not `make test`, which exits 0 on failure (`api-tests/AGENTS.md:66`) [V].
- **In percona/pmm-qa**, against a Feature Build with real database hosts:
  - **T10:** a host with PMM Client 3.11.0.
  - **T11:** `scripts.disabled: true` in a host's `pmm-agent.yaml`; then switched off again, a run succeeds.
  - **T13:** a secret on `stdin` and in a file marked sensitive; the record, both sides' logs, the process list during the run, and a dump of `script_runs` and `script_run_logs` are searched for it.
  - **T16:** each of the four kinds on both hosts; on a host without Python's `venv` module the two Python kinds read as not launchable, with the reason, until the module is installed, and then succeed.
  - **T18:** on PMM's PMM Client image: a run succeeds; `contained: false`; a run with `memory_max` is `not_started`, with the reason "memory_max needs a host where runs are contained".
  - **T20:** a stop of a run that has written 40 lines; the history shows 40.
  - **T21:** the three cases of Task 1's note.
  - **T26:** a stored task that is a Nomad job, on an install with the bundle's default and on one that has fallen back.
- **T23, measured:** on a Feature Build, move the final time of one finished run back by 7 days plus one hour and of another by 7 days minus one hour, in PostgreSQL; after the next cleaner pass the first run and its output are gone and the second is kept. The cleaner's own rule is plan 02's unit test.
- Run each automated case once as part of the measured campaign too, and post its result with the others.

### Task 3: Delivery, at most once, and the host list (T1, T2, T3, T6, T7, T14, T20, T22)

**Files:** none; results on PMM-15982.

**Interfaces:** none.

**Steps:**
- Run **T1**, then **T2**, on both hosts at once, with Task 1's scripts.
- Run **T3**: `systemctl restart pmm-agent` with 16 running and 40 queued. Record each record's final state and reason ("pmm-agent was stopped"), a process list at 10 s, a count of executions per run from the scripts' own marks, and how long the stop took: pmm-agent kills every run at once and waits at most 5 s for acknowledgments ([00](00-roadmap.md#limits)). During the spike its shutdown blocked for about 90 s with a run in flight [V, spec §4.5].
- Run T3 on PMM Server's own pmm-agent: `supervisorctl restart pmm-agent` with runs in flight on the server's node ends inside supervisord's `stopwaitsecs = 10` (`managed/services/supervisord/pmm_config.go:188`) [V], with no SIGKILL in `/srv/logs/pmm-agent.log`.
- Record, beside T3: a reload of pmm-agent's configuration with runs in flight ends none of them.
- Run **T6**: stop a run while its host is cut off; restart pmm-managed during the cut; end the cut.
- Run **T7**: snapshot PMM Server, start a run, restore the snapshot while the run is in flight; after the reconnect, start a new run and record that it succeeds. The spike did not try new work after a restore [V].
- Run **T14**: a script prints 1 GiB during a 20-minute cut. Read pmm-agent's memory every 30 s through the cut, and the record's dropped bytes and the first and last lines kept.
- Run **T20** as a measured run as well as in percona/pmm-qa: in the spike the product kept 0 of the 40 lines written before a stop ([spec §3.3](../spec.md#33-what-today-gets-wrong)) [V].
- Run **T22**: drop the host's traffic silently (no reset) and read the host list every 5 s.

### Task 4: Containment (T4, T5, T18, T19)

**Files:** none; results on PMM-15982.

**Interfaces:** none.

**Steps:**
- Check per host first: the host list says `contained: true` for the packaged unit with plan 03's settings. A host that says `false` is a failure of plan 03, not a skip.
- Run **T4**: `kill -9` of pmm-agent while a run's child has left its session and cleared its environment. Process list at 10 s after pmm-agent is back.
- Run **T5**: 16 takes per test host, 8 with `memory_max` and 8 without, through `/v1/scripts`. Per take record: which processes the kernel killed; the run's `oom_score_adj` (1000, [00](00-roadmap.md#limits)); whether the unit stayed active; whether the database and the exporters kept answering; the state and reason of every other run in flight. The spike's containment figure was taken on one host only, a deb-based one, with pmm-agent not root, and with a group limit set [V, spec §4.3, §6.5]; the rpm host with SELinux enforcing, the root pmm-agent and the takes without a limit are new evidence.
- Run **T18** as in Task 2, plus a stop of a run whose child left its session, recorded as the fallback's known limit ([spec §6.5](../spec.md#65-containment)), and pmm-agent's start-up sweep of processes that carry a `PMM_RUN_ID`.
- Run **T19**: stop a run whose child left its session and cleared its environment, on a contained host. Process list at 10 s after the stop.

### Task 5: Upgrades (T9, T24, T25)

**Files:** none; results on PMM-15982.

**Interfaces:** none.

**Steps:**
- Run **T9**: PMM Server upgraded from one Feature Build of the integration branch to a later one that adds a database migration, with a run in flight on each host. The spike tested a restart and a kill of pmm-managed, never an upgrade with a schema migration [V, spec §4.5].
- Run **T24**: upgrade the `pmm-client` package on the rpm host and on the deb host from 3.11.0 to the Feature Build, with exporters running. Read the unit's settings (`systemctl show pmm-agent`), the exporters' state, and the gap in each exporter's series in VictoriaMetrics.
- Run **T25**'s upgrade half: PMM Server 3.11.0 with PMM Extensions and Nomad as documented today, a task in flight through Nomad, then the upgrade to the Feature Build with Nomad left enabled. The Nomad executor follows the run to a final state; the next run of the same task goes through pmm-agent. Its fallback half is in Task 8.

### Task 6: Memory and timing against the spike (T15, T17, the memory gate)

**Files:** none; results on PMM-15982.

**Interfaces:** none.

**Steps:**
- Compare against the spike's figures, all from its final round [V, spec §4]:

  | Measure | Spike figure for the pmm-agent job | Its footing |
  |---|---|---|
  | pmm-agent at rest, Rocky / Ubuntu | about 42 / 39 MiB | 30 minutes after a restart |
  | Each run in flight, Rocky / Ubuntu | 0.69 / 0.47 MiB | 5 runs at once on Rocky, 3 on Ubuntu; the run's shell and script counted; pmm-agent not root |
  | Growth over 500 runs on one host | 0.010 MiB a run: pmm-agent 41.0 → 46.0, 46.1 after 40 minutes; 500 of 500 in 125 s | the package's non-root user, 4 callers |
  | 1,700-run backlog over 15 container hosts | container hosts +0.023 MiB a run; pmm-managed 115.8 before, 131.0 at the end (+15.2 over 1,695 runs), not read idle afterward | 2 callers through PMM Extensions |
  | 12 hours, one script that never ends | pmm-agent 38.4 to 38.6 MiB on the idle host, 36.7 to 36.9 on the run host; pmm-managed 72.5 to 74.1 | shared CPUs |
  | One call through PMM Extensions | 1,004 ms median, 1,193 ms slowest | a fetched script; PMM Extensions checking once a second |
  | The same, with a check on each run | 316 ms median (182 to 460 ms) | a mechanism of about 25 lines that helps only a task sent in the API request itself; not the calls that wait |
- Run **T15**: 500 runs on one host, then the 1,700-run backlog. Read pmm-managed idle before the backlog and 30 minutes after its last run.
- Run **T17** with the method of the Global Constraints: PMM Extensions as the caller, its one open `ListRuns` call (`final_after` and `wait`) in place, which syncs each run it returns and replaces the 1 s probe for this backend (plan 04). The measure is the median of 20; the bar is 0.5 s. Time the command kind beside it, as a recorded result: the spike's build did not carry it [V].
- Run the **memory gate** ([00](00-roadmap.md#release-gate)): pmm-agent on each database host, no run in flight, 30 minutes after a restart, with `scripts.disabled: false` and with `true`, on the same build and host. Three readings each; the medians differ by at most 2 MiB.
- Record **pmm-managed at rest** as a result, not a gate: the Feature Build and the `main` it was cut from, on one footing. The spike has no such pair ([spec §4.1](../spec.md#41-memory)) [V].
- Record **12 hours**: a script that prints a line a second for 12 hours on the deb host, with its daily automatic upgrade left on. Memory every 10 minutes and the run's outcome; a pmm-agent restart by the upgrade ends the run `lost`, with the output to that point kept.

### Task 7: HA leader change (T8)

**Files:** a test in percona/pmm-qa's HA suite if the case can be scripted there; otherwise none, and the result on PMM-15982.

**Interfaces:** none.

**Steps:**
- Use Task 1's HA environment; drive every call through `/v1/scripts` with the second token derived from the shared `PMM_EXTENSIONS_TOKEN`. Start runs on both hosts that print for at least 15 minutes, plus 40 queued.
- Run it with the **leader killed**: delete the leader pod. Record how long the hosts took to reconnect, that the check of [spec §6.4](../spec.md#64-reconnect-and-lost-runs) ran on the new leader, and the time from the change to a new run that starts.
- Run it with the **leader demoted, still alive**: force a leader change without killing the pod. Agents may stay on the demoted replica (`managed/cmd/pmm-managed/main.go:1024-1029`, commented out) [V]. Record each call's answer while the agents are on the follower, and that a stop sent then is held and delivered later ([spec §9.2](../spec.md#92-high-availability)).
- Check that retention ran on one replica only: after the case, the leader's cleaner log shows a pass and the followers' show none.

### Task 8: Mixed versions, the fallback, and stored Nomad tasks (T10, T25, T26)

**Files:** the T10 and T26 tests of Task 2; otherwise results on PMM-15982.

**Interfaces:** none.

**Steps:**
- Run the 3.12.0 rows of [spec §10.3](../spec.md#103-old-and-new-together); the spike tested no mix of versions ([spec §4.5](../spec.md#45-what-the-spike-left-open-for-the-pmm-agent-job)) [V]:

  | Server | Hosts | Expected |
  |---|---|---|
  | Feature Build, the bundle's default | one host on the Feature Build, one on PMM Client 3.11.0 | The new host runs tasks; the old one is "too old" in the host list and its runs are `not_started` (T10) |
  | Feature Build with the fallback: `TASKS__DEFAULT_BACKEND=nomad`, `PMM_ENABLE_NOMAD=1`, a public address, port 4647 published | the same two | Both hosts run tasks through Nomad (T25) |
  | Feature Build, the fallback removed again | the same two | The 3.11.0 host's Nomad client stops (`agent/agents/supervisor/supervisor.go:574-611`) [V]; monitoring on both hosts is unaffected |
  | PMM Server 3.11.0 | one host on the Feature Build | Monitoring works; with Nomad enabled on the server the Feature Build's pmm-agent runs the Nomad client as before, since it still carries Nomad in 3.12.0 |
- PMM's upgrade order is server first [I, spec §10.3]; the last row is the case where it was not followed.
- Run **T26**: a stored task that is a Nomad job, on the bundle's default (refused: 400 on the execute route, a FAILED history with the message on a periodic run) and with the fallback (runs through Nomad).

### Task 9: Implementation security review

**Files:** none in a code repository; findings through the review's own channel, with a closed or accepted state recorded on PMM-15982 by reference only.

**Interfaces:** none.

**Steps:**
- Run it on the integration branch after plan 05 is merged into it, so it covers the side-car wiring and the defaults.
- Cover at least the design review's list in [00](00-roadmap.md#plans-and-order), now against the code:
  - who can start a run: nginx's `auth_request` rule for `/v1/scripts`, and the rule for `/scripts.v1beta1.` that nginx does not expose; the second token, its derivation from the internal token, its constant-time compare, the 403; the API with no internal token (ADR-09);
  - which user a run gets: `run_as` and the root-only rule, the lookup in the host's own user files, the run directory under a root-owned parent (ADR-07);
  - what a run may be told to do: the command list, the refused environment names (`PMM_RUN_*`, `LD_*`, `PATH`), file modes (owner bits only), and the limits and where each is enforced ([spec §6.2](../spec.md#62-what-a-run-is), [00](00-roadmap.md#limits));
  - where secrets travel and rest: `stdin`, `env` values and `files` content through pmm-managed's memory, sensitive files, the run directory's mode, log redaction on both sides with whole messages logged at debug level, and what `script_runs` stores ([spec §6.6](../spec.md#66-records-and-retention));
  - file reads and the listing: opened without following links, then checked on the open file to be a regular file with a link count of 1, in `out/` only, with and without `run_as` ([spec §6.7](../spec.md#67-the-api));
  - acceptance of a message only from the pmm-agent a run was sent to ([spec §6.3](../spec.md#63-delivery-of-output-and-results));
  - containment and its fallback: the unit's settings and its declared delegation, the per-run groups and their limits, `oom_score_adj`, the end-of-run kill, the start-up sweep, and the documented limits where a run is not contained (ADR-06);
  - the host switch `scripts.disabled`, which the server cannot change ([spec §9.1](../spec.md#91-who-can-start-a-run));
  - the side-car: where the service-account token and the internal token come from, and that neither reaches a supervised program's environment (plan 05 Task 2).
- Close or accept every finding in writing before Task 10. A code finding is fixed on its own branch from the integration branch, with a PR into it, and re-checked by the reviewer; a design finding first changes the spec or an ADR through a pmm-specs PR.

### Task 10: Release gate

**Files:** none; the gate's record on PMM-15982.

**Interfaces:** none.

**Steps:**
- Check each line of the roadmap's [release gate](00-roadmap.md#release-gate), with a link to its evidence:
  - T1 to T26 pass on the current Feature Build (Tasks 2 to 8). A result older than the last PR that touched its code does not count.
  - The implementation security review has no open finding (Task 9).
  - T8 and T9 pass (Tasks 7 and 5).
  - Memory on a database host with no run in flight is within 2 MiB of the same build with script runs disabled (Task 6).
  - The deprecation of Nomad is in `documentation/docs/release-notes/next.md`, and `documentation/docs/reference/nomad.md` no longer says that Nomad will remain (plan 05 Tasks 6 and 7).
- Post every recorded result that is not a gate (pmm-managed at rest, the command kind's time, the 12-hour run, the reload), each with a sentence on what it means for the release.
- When every line is checked, tell the owner of plan 05 Task 9 that the merge may go ahead.
