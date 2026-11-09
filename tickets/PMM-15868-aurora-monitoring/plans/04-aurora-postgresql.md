# Aurora PostgreSQL Details (Release 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PostgreSQL Amazon Aurora Details dashboard fed by two Aurora-only postgres_exporter queries, a smaller CloudWatch request list for PostgreSQL in rds_exporter, and the Amazon RDS page linking to the dashboard.

**Architecture:** Two YAML blocks in postgres_exporter's shipped `queries-hr.yml` (no Go); one field and one filter function in rds_exporter; one new dashboard JSON, a link change on the Amazon RDS page and docs in percona/pmm; one Playwright case in pmm-qa. One Feature Build carries all four branches.

**Tech Stack:** Go (postgres_exporter, rds_exporter), Grafana dashboard JSON, React/TypeScript with Vitest (PMM UI), MkDocs, Playwright (pmm-qa).

**Spec:** [../spec.md, section 7](../spec.md#7-release-2-aurora-postgresql-details), with decisions 12–14, Alternatives P and Q, Files Changed "Release 2" and acceptance criteria 16–22.

## Global Constraints

- Branch `PMM-15868-aurora-postgres-details` in every repo: cut from `origin/main` in percona/postgres_exporter, from `origin/PMM-15868-aurora-cluster-info` in percona/rds_exporter, from `origin/PMM-15868-rds-overview-page` in percona/pmm, from `origin/PMM-15868-aurora-tests` in percona/pmm-qa. Push with `git push -u origin HEAD`.
- Commits: `PMM-15868 <summary>` (≤50 characters), `git commit -s`, one `git add` call and one `git commit` call each (a hook blocks both in one command), `git -C` with a literal absolute path.
- No Docker, PMM, databases or frontend builds on the runner host: UI lint and tests, docs preview and Playwright run on CHAOS VMs (chaos-docker-provisioning skill). Go builds, tests and lint run on the host.
- Metric and label names, verbatim: `pg_custom_aurora_replica_status_replica_lag_seconds{server_id, role}` with `role` `writer` or `reader`; `pg_custom_aurora_dml_activity_{select,insert,update,delete}_{count,latency_seconds}{datname}`.
- Dashboard: file `dashboards/dashboards/PostgreSQL/PostgreSQL_Amazon_Aurora_Details.json`, title `PostgreSQL Amazon Aurora Details`, uid `postgresql-amazonaurora`, tags `Percona`, `PostgreSQL`.
- No new AWS permission, no new CloudWatch metric, no change to WAL panels (decisions 12, 13).

## Review Focus

1. A non-Aurora PostgreSQL server reading the new blocks must get the namespace *present* with an empty query; a missing key makes postgres_exporter run `SELECT * FROM <namespace>` and log an error every scrape. Pinned in Task 1's test.
2. rds_exporter with an unknown engine (AWS lookup failed or not yet run) must request all 47 metrics, as today. Pinned by the `""` row in Task 2's test.
3. The legacy `aurora` engine (Aurora MySQL 5.6) must keep the MySQL-only metrics. Pinned by the `aurora` row in Task 2's test.
4. Statement Latency for a statement type the instance didn't run must show 0, not gaps (the PMM-6655 behaviour on the MySQL dashboard). Pinned by the expression in Task 3 and checked live in Task 7.
5. The dashboard's service dropdown must not list PMM Server's own PostgreSQL. Pinned in Task 6's test (`not.toContain('pmm-server-postgresql')`).

---

### Task 1: postgres_exporter Aurora-only queries

Repo `/srv/runner/7/percona/postgres_exporter`.

**Files:**
- Modify: `queries-hr.yml` (append two blocks)
- Test: `cmd/postgres_exporter/queries_test.go`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: the series named in Global Constraints, consumed by Task 3's dashboard.

- [ ] **Step 1: Write the failing test** `TestShippedQueriesHrAuroraBlocks` in `cmd/postgres_exporter/queries_test.go`:

```go
func TestShippedQueriesHrAuroraBlocks(t *testing.T) {
	content, err := os.ReadFile("../../queries-hr.yml")
	require.NoError(t, err)
	namespaces := []string{"pg_custom_aurora_replica_status", "pg_custom_aurora_dml_activity"}

	_, standard, err := parseUserQueries(content, distribution.Standard)
	require.NoError(t, err)
	for _, ns := range namespaces {
		query, found := standard[ns]
		require.True(t, found, ns)
		require.Empty(t, query, ns)
	}

	_, aurora, err := parseUserQueries(content, distribution.Aurora)
	require.NoError(t, err)
	require.Contains(t, aurora["pg_custom_aurora_replica_status"], "aurora_replica_status()")
	require.Contains(t, aurora["pg_custom_aurora_dml_activity"], "aurora_stat_dml_activity(d.oid)")
	require.Contains(t, aurora["pg_custom_aurora_dml_activity"], "'rdsadmin'")
}
```

- [ ] **Step 2: Run it to see it fail**

Run: `go test ./cmd/postgres_exporter/ -run TestShippedQueriesHrAuroraBlocks -v`
Expected: FAIL, `pg_custom_aurora_replica_status` not found.

- [ ] **Step 3: Append the two blocks to `queries-hr.yml`.** The SQL is the version checked live (spec section 7); each block has `master: true`, only `query_aurora`, and a one-line `description` per metric in the file's style.

```yaml
pg_custom_aurora_replica_status:
  master: true
  # Aurora only: no plain query, so other PostgreSQL servers skip it
  query_aurora: |
    SELECT server_id,
      CASE WHEN session_id = 'MASTER_SESSION_ID' THEN 'writer' ELSE 'reader' END AS role,
      COALESCE(replica_lag_in_msec, 0) / 1000.0 AS replica_lag_seconds
    FROM aurora_replica_status();
  metrics: server_id LABEL, role LABEL, replica_lag_seconds GAUGE

pg_custom_aurora_dml_activity:
  master: true
  query_aurora: |
    SELECT d.datname,
      a.select_count, a.select_latency_microsecs / 1e6 AS select_latency_seconds,
      a.insert_count, a.insert_latency_microsecs / 1e6 AS insert_latency_seconds,
      a.update_count, a.update_latency_microsecs / 1e6 AS update_latency_seconds,
      a.delete_count, a.delete_latency_microsecs / 1e6 AS delete_latency_seconds
    FROM pg_database d, LATERAL aurora_stat_dml_activity(d.oid) a
    WHERE d.datallowconn AND NOT d.datistemplate AND d.datname <> 'rdsadmin';
  metrics: datname LABEL, the four *_count and four *_latency_seconds COUNTER
```

(`metrics:` above is shorthand; write the full `- name: {usage, description}` list like the existing blocks.)

- [ ] **Step 4: Run the test, then the package suite and vet**

Run: `go test ./cmd/postgres_exporter/ -run TestShippedQueriesHrAuroraBlocks -v`, then `go test ./...` and `go vet ./...`
Expected: PASS, no vet findings.

- [ ] **Step 5: CHANGELOG** under `## [Unreleased]`: `* [ENHANCEMENT] Add Aurora PostgreSQL replica lag and DML activity queries to queries-hr.yml`

- [ ] **Step 6: Commit and push** `PMM-15868 Add Aurora PostgreSQL queries`

### Task 2: rds_exporter skips MySQL-only metrics for PostgreSQL

Repo `/srv/runner/7/percona/rds_exporter`.

**Files:**
- Modify: `basic/metrics.go` (field on `Metric`, set on 19 entries)
- Modify: `basic/scraper.go` (`metricsFor`, used by `Scrape`)
- Test: `basic/scraper_test.go`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `func metricsFor(engine string, metrics []Metric) []Metric` (package `basic`).

- [ ] **Step 1: Write the failing table test** `TestMetricsFor` in `basic/scraper_test.go`: for `postgres` and `aurora-postgresql`, `len(metricsFor(engine, Metrics)) == 28` and no returned metric has `mysqlOnly`; for `aurora-mysql`, `mysql`, `mariadb`, `aurora` and `""`, the result equals `Metrics` (47). Also assert exactly 19 entries of `Metrics` have `mysqlOnly`.

- [ ] **Step 2: Run it to see it fail**

Run: `go test ./basic/ -run TestMetricsFor -v`
Expected: build failure, `metricsFor` and `mysqlOnly` undefined.

- [ ] **Step 3: Implement.** Add `mysqlOnly bool` to `Metric` and set it on: ActiveTransactions, AuroraBinlogReplicaLag, BinLogDiskUsage, BlockedTransactions, DDLLatency, DDLThroughput, DMLLatency, DMLThroughput, DeleteLatency, DeleteThroughput, InsertLatency, InsertThroughput, LoginFailures, Queries, ResultSetCacheHitRatio, SelectLatency, SelectThroughput, UpdateLatency, UpdateThroughput. `metricsFor` drops `mysqlOnly` metrics when `engine` is `postgres` or `aurora-postgresql` and returns the input otherwise. In `Scrape`, take the engine from `s.resolved` (`""` when nil) and loop over `metricsFor(engine, s.collector.metrics)`, with `wg.Add` sized to the filtered list.

- [ ] **Step 4: Run the tests and lint**

Run: `go test ./basic/ -run 'TestMetricsFor|TestClusterVolume' -v`, `go vet ./...`, `make check`
Expected: PASS and clean. `TestCollector` needs AWS credentials and is not run here; its golden file `basic/testdata/all.txt` needs no change, because AWS returns no data for these 19 metrics on the PostgreSQL instances in `config.tests.yml`.

- [ ] **Step 5: CHANGELOG** under `## [Unreleased]`, `### Changed`: `- CloudWatch metrics AWS publishes only for MySQL engines are no longer requested for PostgreSQL and Aurora PostgreSQL instances (19 fewer calls per scrape).`

- [ ] **Step 6: Commit and push** `PMM-15868 Skip MySQL-only metrics for PostgreSQL`

### Task 3: PostgreSQL Amazon Aurora Details dashboard

Repo `/srv/runner/7/percona/pmm`.

**Files:**
- Create: `dashboards/dashboards/PostgreSQL/PostgreSQL_Amazon_Aurora_Details.json`

**Interfaces:**
- Consumes: Task 1's series; existing `pg_stat_database_*`, `pg_database_wraparound_age_datfrozenxid_seconds`, `pg_settings_aurora_compute_plan_id`, `aws_rds_*`.
- Produces: uid `postgresql-amazonaurora`, URL slug `postgresql-amazon-aurora-details`, and the panel titles below, used by Tasks 4, 5 and 6.

- [ ] **Step 1: Copy** `dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json`, then set title, uid and tags (Global Constraints), drop `id` and `version` as the other files do, and keep `interval`, the time range and the Amazon RDS Overview link.

- [ ] **Step 2: Variables.** `service_name`: `label_values({__name__=~"pg_custom_aurora_replica_status_replica_lag_seconds|pg_settings_aurora_compute_plan_id"}, service_name)`. `node_name` (hidden): `label_values({__name__=~"pg_custom_aurora_replica_status_replica_lag_seconds|pg_settings_aurora_compute_plan_id",service_name=~"$service_name"}, node_name)`.

- [ ] **Step 3: Replace the six top panels** (same grid positions, `timeseries`). `S` stands for `{service_name=~"$service_name"}`, `N` for `{node_name=~"$node_name"}`, `D` for `pg_custom_aurora_dml_activity`.

| Title | Unit | Queries (legend) |
|---|---|---|
| Transaction Commits | ops | `sum by (service_name) (rate(pg_stat_database_xact_commit S[$interval]))` (Commits); same with `xact_rollback` (Rollbacks) |
| Commit Latency | ms | `avg by (node_name) (aws_rds_commit_latency_average N)` (Commit latency) |
| Statement Throughput | ops | per type T in select, insert, update, delete: `sum by (service_name) (rate(D_T_count S[$interval]))` (T) |
| Statement Latency | s | per type: `sum by (service_name) (rate(D_T_latency_seconds S[$interval])) / sum by (service_name) (rate(D_T_count S[$interval])) or (sum by (service_name) (rate(D_T_count S[$interval])) == 0) * 0` (T) |
| Problems | ops | `sum by (service_name) (rate(pg_stat_database_deadlocks S[$interval]))` (Deadlocks); same with `pg_stat_database_conflicts` (Conflicts) |
| Oldest Transaction ID Age | short | `max by (service_name) (pg_database_wraparound_age_datfrozenxid_seconds S)` (Oldest XID age); description: transaction ID age of the oldest database; Aurora turns read-only near 2.1 billion |

- [ ] **Step 4: Rows.** Keep "Cache and local storage" and "Instance resources (CloudWatch)" unchanged. Keep "Replication (needs a reader)" collapsed with two panels: **Replica Lag** (unit s, `max by (server_id) (pg_custom_aurora_replica_status_replica_lag_seconds{service_name=~"$service_name",role="reader"})`, legend `{{server_id}}`) and **Aurora Replica Lag (CloudWatch)** (unit ms, `avg by (node_name) (aws_rds_aurora_replica_lag_average N)` and `avg by (node_name) (aws_rds_aurora_replica_lag_maximum_average N)`, legends `Replica lag` and `Maximum replica lag`). Delete the Write forwarding, Parallel query and Serverless rows. Every panel id stays unique.

- [ ] **Step 5: Check**

Run: `python3 dashboards/misc/cleanup-dash.py --check-only dashboards/dashboards/PostgreSQL/PostgreSQL_Amazon_Aurora_Details.json`, then `python3 -c "import json,sys; json.load(open(sys.argv[1]))" <file>`
Expected: no changes reported, valid JSON. Panel data is checked live in Task 7.

- [ ] **Step 6: Commit and push** `PMM-15868 Add PostgreSQL Amazon Aurora Details`

### Task 4: Amazon RDS page opens the new dashboard

Repo `/srv/runner/7/percona/pmm`, directory `ui/apps/pmm/src/pages/amazon-rds/`.

**Files:**
- Modify: `AmazonRds.constants.ts`, `AmazonRds.messages.ts`, `AmazonRds.utils.ts`
- Test: `AmazonRds.utils.test.ts`, `AmazonRdsPage.test.tsx`

**Interfaces:**
- Consumes: Task 3's uid and slug.
- Produces: `DASHBOARD_URLS.auroraPostgresqlDetails`, `Messages.links.postgresql` (`'PostgreSQL'`), `Messages.links.postgresqlDetails(serviceName)` (`` `PostgreSQL Amazon Aurora Details for ${serviceName}` ``).

- [ ] **Step 1: Update the tests.** In `AmazonRds.utils.test.ts`, add `links an Aurora PostgreSQL instance to its details, with PostgreSQL and OS links`, mirroring the Aurora MySQL case: service `{label: 'db-1', title: 'PostgreSQL Amazon Aurora Details for db-1', url: '/graph/d/postgresql-amazonaurora/postgresql-amazon-aurora-details?var-service_name=db-1'}`, dashboards `PostgreSQL` (`PostgreSQL Instance Summary for db-1`, `/graph/d/postgresql-instance-summary/postgresql-instance-summary?var-service_name=db-1`) then `OS`. Reduce the existing `it.each` PostgreSQL case to `postgres` only. In `AmazonRdsPage.test.tsx`, the `database-4-instance-1` link expects the new dashboard URL, and the "Node Summary for" count stays 12.

- [ ] **Step 2: Run the tests on the development VM to see them fail**

Run: `cd ui && make test` (inside the dev VM after `sync`)
Expected: the new and changed cases fail.

- [ ] **Step 3: Implement.** Add the constant (`${PMM_NEW_NAV_GRAFANA_PATH}/d/postgresql-amazonaurora/postgresql-amazon-aurora-details`) and the two messages; in `getInstanceLinks`, an `engine === 'aurora-postgresql'` branch before the PostgreSQL family branch returns the details link and `[postgresqlSummary, os]`.

- [ ] **Step 4: Run lint, format check and tests**

Run: `cd ui && make lint && make format-check && make test`
Expected: all pass.

- [ ] **Step 5: Commit and push** `PMM-15868 Link Aurora PostgreSQL to its dashboard`

### Task 5: Docs

Repo `/srv/runner/7/percona/pmm`, directory `documentation/`.

**Files:**
- Create: `docs/reference/dashboards/dashboard-postgresql-amazon-aurora-details.md`
- Modify: `mkdocs-base.yml`, `docs/use/dashboards-panels/index.md`, `docs/use/amazon-rds-overview.md`, `docs/release-notes/next.md`

- [ ] **Step 1: The dashboard page**, laid out like `dashboard-mysql-amazon-aurora-details.md`: the image line `![!image](../../images/PMM_PostgreSQL_Amazon_Aurora_Details.png)` (the file comes in Task 7), a short intro that names the `rds_superuser` grant from the PostgreSQL connection page, one `##` section per top panel and per row with Task 3's titles, and a note that the Replication row needs a reader.

- [ ] **Step 2: Links.** Nav entry before `reference/dashboards/dashboard-postgresql-instance-summary.md` in `mkdocs-base.yml`; a row and a link reference in `use/dashboards-panels/index.md` next to PostgreSQL Instance Summary; the Service row of `use/amazon-rds-overview.md` names the new dashboard for Aurora PostgreSQL; one `PMM-15868` entry in `release-notes/next.md` covering the dashboard, the new postgres_exporter series and the smaller CloudWatch request list for PostgreSQL.

- [ ] **Step 3: Preview** on the development VM.

Run: `make doc-build-preview` and open the new page and the changed ones.
Expected: they render; every new link resolves.

- [ ] **Step 4: Commit and push** `PMM-15868 Document Aurora PostgreSQL Details`

### Task 6: pmm-qa Playwright case

Repo `/srv/runner/7/percona/pmm-qa`, directory `e2e_tests/`.

**Files:**
- Create: `pages/dashboards/postgresql/postgresqlAmazonAuroraDetails.ts`
- Modify: `pages/dashboards/postgresql/index.ts`, `testdata/remoteInstances.ts`, `tests/inventory/remoteInstances.test.ts`, `helpers/versionGates.ts`

**Interfaces:**
- Consumes: Task 3's URL and panel titles.

- [ ] **Step 1: Zephyr.** Publish one case with the zephyr skill: "Verify PostgreSQL Amazon Aurora Details lists Aurora PostgreSQL services and shows data", RDS folder, linked to PMM-15868, status Automated once the test passes in CI. Use its key `PMM-T<N>` below.

- [ ] **Step 2: Page object** `PostgresqlAmazonAuroraDetails` like `MysqlAmazonAuroraDetails`: `url = 'graph/d/postgresql-amazonaurora/postgresql-amazon-aurora-details'`, `metrics` = every Task 3 panel title, `noDataMetrics = ['Replica Lag', 'Aurora Replica Lag (CloudWatch)']` (the CI cluster has no reader); register it in `index.ts` as `postgresqlAmazonAuroraDetails`.

- [ ] **Step 3: Test data.** `auroraPostgresqlInstanceId = 'pmm-qa-rds-aurora-15-instance-1'` and an `auroraPostgresql: AddRemoteInstance` like `auroraMysql`, with `engine: 'DISCOVER_RDS_ENGINE_POSTGRESQL'`, `address`, `username` and `password` from `PMM_QA_RDS_AURORA_PGSQL15_HOST`, `_USER` and `_PASSWORD`, `cluster: 'postgres15aws_aurora'`, port and the PostgreSQL QAN option as in the CodeceptJS `postgres15aurora` add.

- [ ] **Step 4: The test** `PMM-T<N> - Verify PostgreSQL Amazon Aurora Details lists Aurora PostgreSQL services and shows data @instances`: add the instance when missing (as PMM-T2504 does) and add its id to `remoteNodeNames`; open the dashboard with `from: 'now-5m'`; `Service Name` values contain `auroraPostgresqlInstanceId` and not `'pmm-server-postgresql'`; select it; `verifyMetricsPresent` and `verifyAllPanelsHaveData(noDataMetrics, Timeouts.TWO_MINUTES)`. Gate `'PMM-T<N>'` to the version in pmm-submodules' `VERSION` on `v3` at implementation time (`3.10.1` when this plan was written).

- [ ] **Step 5: Lint and prove it**

Run: `support_scripts/lint/lint-changed.sh <changed files>` now; once Task 7 Step 2 has a VM, run the test against it per the test-implementer skill, and check the Feature Build's pmm-qa run.
Expected: lint clean; the test passes there and in the Feature Build run, and is not skipped for missing secrets.

- [ ] **Step 6: Commit and push** `PMM-15868 Test Aurora PostgreSQL Details`

### Task 7: Feature Build and live verification

- [ ] **Step 1: Feature Build.** With the pmm-feature-build skill, open a draft pmm-submodules PR from branch `PMM-15868-aurora-postgres-details` whose `ci.yml` lists `pmm`, `rds_exporter`, `postgres_exporter` and `pmm-qa` on `PMM-15868-aurora-postgres-details`. Wait for the server and client images.

- [ ] **Step 2: Test VM.** A new CHAOS VM from those images (chaos-docker-provisioning). Add an Aurora MySQL cluster through RDS discovery first and note `rds_exporter_requests_total`'s increase per basic scrape; then add the Aurora PostgreSQL 15 cluster and the writer-and-reader Aurora PostgreSQL 17 cluster, with the same AWS key. If the 17 cluster can't be added from the available secrets, ask the user to add it.

- [ ] **Step 3: Check criteria 16–21** and keep the evidence (query results, screenshots):
  - 16, 17: dropdown lists only Aurora PostgreSQL services; `tools/panelcheck.py` (this spec folder) finds no empty panel on either 17 instance, and only the Replication row empty on the 15 writer; Statement Latency shows 0, not gaps, for idle statement types.
  - 18: Replica Lag and Aurora Replica Lag (CloudWatch) show the reader on both 17 instances.
  - 19: no `pg_custom_aurora` error in `/srv/logs/pmm-agent.log` for `pmm-server-postgresql`, and no `aurora_` line in PMM Server's PostgreSQL log.
  - 20: each added Aurora PostgreSQL instance raises `rds_exporter_requests_total` by 29 calls per basic scrape (48 on Release 1); the Aurora MySQL node's `aws_rds_*` series count is the same as on Release 1.
  - 21: on the Amazon RDS page, the 17 writer opens the new dashboard.

- [ ] **Step 4: Screenshot** the dashboard on the 17 writer with the ui-evidence skill, save it as `documentation/docs/images/PMM_PostgreSQL_Amazon_Aurora_Details.png` on the pmm branch, commit `PMM-15868 Add the Aurora PostgreSQL screenshot`, push.

- [ ] **Step 5: Fix and repeat.** A failed criterion goes back to the task that owns the code, as a new commit, and Steps 3–4 run again on a rebuilt Feature Build.

### Task 8: Pull requests and spec update

- [ ] **Step 1: Draft PRs** (pmm-pr skill for percona/pmm; each repo's template elsewhere), each based on the branch it was cut from: percona/postgres_exporter → `main`, percona/rds_exporter → `PMM-15868-aurora-cluster-info`, percona/pmm → `PMM-15868-rds-overview-page`, percona/pmm-qa → `PMM-15868-aurora-tests`. Each body links the others and the Feature Build, and says it moves to the default branch once Release 1 merges.

- [ ] **Step 2: Spec as built.** In `spec.md`, set criteria 16–22 to Met or pending with their evidence, record any design change in the decision log, and add the PR links to the folder README; commit `PMM-15868 Update Release 2 to as built`, push.
