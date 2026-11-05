# Aurora monitoring, part 2: PMM dashboards and menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MySQL Amazon Aurora Details works when opened normally, a new Aurora overview groups instances by AWS cluster, and CPU Saturation shows data on RDS nodes.

**Architecture:** Dashboard JSON and one PMM UI menu entry, shipped with PMM Server. Task 1 needs nothing from plan 01; Tasks 2 and 3 need plan 01's series (`aws_rds_instance_info`, cluster `aws_rds_volume_bytes_used_average`) on the test server, from a pmm-client built with plan 01's branch.

**Tech Stack:** Grafana dashboard JSON (PromQL on VictoriaMetrics), TypeScript (PMM UI menu), MkDocs.

**Spec:** [../spec.md](../spec.md), Technical Plan sections 3, 4 and 5.

**Repository:** percona/pmm, branch `PMM-15868-aurora-dashboards`, one PR.

## Global Constraints

* Keep `MySQL_Amazon_Aurora_Details.json`'s uid `mysql-amazonaurora`, file path, variable names and panel ids 3, 21, 22, 24, 25, 26 with their titles (pmm-qa matches the titles).
* No dropdown and no up/down cell may depend on a metric this epic adds (`aws_rds_instance_info`, cluster storage).
* Cluster storage is read with `max by (region, aws_account_id, aws_cluster_id)`, never `sum`.
* Run `python3 dashboards/misc/cleanup-dash.py <file>` on every changed dashboard before committing.
* Commits: `PMM-15868 <summary>`, signed off.

## How to check a dashboard on the test server

Use a test PMM Server with the QA Aurora instances added through RDS discovery. To load a changed dashboard without rebuilding, copy the file to the server host and run there (file path relative to `dashboards/dashboards/`):

```bash
F=MySQL/MySQL_Amazon_Aurora_Details.json
D=/usr/share/percona-dashboards/panels/pmm-app/dist/dashboards
docker cp dash.json pmm-server:$D/$F
docker exec -u 0 pmm-server chown pmm:root $D/$F
curl -ksS -X POST -u admin:<admin password> https://127.0.0.1/graph/api/admin/provisioning/dashboards/reload
```

Then run the panel sweep, which exits 0 only when no panel is empty or partly empty:

```bash
PMM_URL=https://<test PMM Server> PMM_PASS=<admin password> \
  python3 tickets/PMM-15868-aurora-monitoring/tools/panelcheck.py <uid> service_name=<service>
```

## Before you start: spikes

Needs an Aurora MySQL 3 cluster with one reader, added to the test PMM Server.

1. On the reader, `mysql_global_variables_innodb_read_only` reads 1 (on the writer it reads 0). After `aws rds failover-db-cluster`, the values swap within 2 minutes.
2. `aws_rds_volume_bytes_used_average` (from plan 01) has no gaps over an hour. If it has, plan 01 Task 3 widens its window.
3. Read what PMM-T1295 asserts (plan 03) before adding rows to Details.

If (1) fails, Task 3's role column uses "unknown" for readers and the overview's writer count is dropped; record that in the spec.

## Review Focus

1. **Instance on an older pmm-client** (no `aws_rds_instance_info`): appears under "AWS cluster unknown", not missing. Checked in Task 3.
2. **Database exporter down** (no current `mysql_up` sample): the row shows down, not gone. Checked in Task 3.
3. **A cluster with three instances in PMM:** storage shows once, not tripled. Checked in Task 3.
4. **RDS node with `node_procs_running` = 0** (as on the QA Aurora writer): saturation is 0, not negative. Checked in Task 2.
5. **Details opened from search with no URL variables:** the first service's panels have data. Checked in Task 1.

---

### Task 1: Fix MySQL Amazon Aurora Details

**Files:**
- Modify: `dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json`

**Interfaces:**
- Produces: panel titles for plan 03: the six existing ones unchanged, plus new rows titled `Cache and local storage`, `Replication (needs a reader)`, `Write forwarding`, `Parallel query`, `Serverless capacity (Serverless only)`, collapsed by default except the first.

- [ ] **Step 1: Record the failing state**

Run the panel sweep for `mysql-amazonaurora` with no variables, then with `service_name=pmm-qa-aurora3-mysql-instance-1`.
Expected today: all 6 EMPTY without variables; with the variable, 3 OK and 3 PARTIAL (#22, #24, #26).

- [ ] **Step 2: Variables**

`service_name` query: `label_values({__name__=~"mysql_global_status_auroradb_(commits|thread_deadlocks)"}, service_name)`.
`node_name` query: the same selector with `{service_name=~"$service_name"}` added, label `node_name`.
Remove the variables no panel uses: `environment`, `cluster`, `replication_set`, `database`, `node_type`, `service_type`, `username`, `schema`. Keep `interval`, `service_name` and `node_name`; the dashboard has no links that pass variables on, and the new CloudWatch targets filter on `node_name`.

- [ ] **Step 3: Panels**

Convert panels 3, 21, 22, 24, 25, 26 from `graph` to `timeseries`, keeping ids, titles and grid positions. Then:
* **#24 Statement Latency:** each line is `rate(<stmt>_duration) / rate(<matching commands>)`; remove the `+ rate(mysql_global_status_qcache_hits…)` term from SELECT, put the whole denominator in parentheses, and append `or (rate(<matching commands>) == 0) * 0` to each line so idle types read 0 (PMM-6655).
* **#26 Problems:** keep the `aurora_reserved_mem_exceeded_incidents` target; replace the two dropped counters with `avg by (node_name) (aws_rds_deadlocks_average{node_name=~"$node_name"})` and `avg by (node_name) (aws_rds_blocked_transactions_average{node_name=~"$node_name"})`, legends `Deadlocks (CloudWatch)` and `Blocked transactions (CloudWatch)`.
* **#22 Memory Used:** replace the `aurora_dict_sys_mem_size` target with `aurora_temptable_ram_allocation`, legend `Temp table RAM`.
* **#25 Special Command Counters:** `sum by (service_name, command) (rate(…[$interval]))`, legend `{{command}}`.

- [ ] **Step 4: New rows**

Below the six panels, add these rows (instant series per `$service_name` or `$node_name`, `timeseries` panels):
* `Cache and local storage` (expanded): `aws_rds_buffer_cache_hit_ratio_average`, `aws_rds_free_local_storage_average` (bytes).
* `Replication (needs a reader)`: `aws_rds_aurora_replica_lag_average` (ms), `aws_rds_aurora_binlog_replica_lag_average` (s).
* `Write forwarding`: `rate()` of `mysql_global_status_aurora_fwd_writer_dml_stmt_count`, `…_select_stmt_count`, and `mysql_global_status_aurora_fwd_writer_open_sessions`.
* `Parallel query`: `rate()` of `mysql_global_status_aurora_pq_request_attempted`, `…_executed`, `…_not_chosen`.
* `Serverless capacity (Serverless only)`: `mysql_global_status_aurora_serverless_current_acu`, `…_min_acu`, `…_max_acu`.

- [ ] **Step 5: Verify**

Run `python3 dashboards/misc/cleanup-dash.py dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json` and `python3 -m unittest discover -s dashboards/misc -p 'test_*.py'` → PASS.
Load it on the test server, run the sweep with no variables and again with each Aurora service.
Expected: no EMPTY or PARTIAL panel outside the collapsed rows; screenshot the dashboard opened with no URL variables.

- [ ] **Step 6: Commit**

`git commit -s -m "PMM-15868 Fix MySQL Amazon Aurora Details on Aurora 3"`

### Task 2: CPU Saturation on RDS nodes; InnoDB I/O panels on Aurora

**Files:**
- Modify (CPU Saturation and Max Core Usage panel): `dashboards/dashboards/MySQL/` `MySQL_Instance_Summary.json`, `MySQL_InnoDB_Details.json`, `MySQL_InnoDB_Compression_Details.json`, `MySQL_MyISAM_Aria_Details.json`, `MySQL_MyRocks_Details.json`, `MySQL_Performance_Schema_Details.json`, `MySQL_Query_Response_Time_Details.json`, `MySQL_Table_Details.json`, `MySQL_User_Details.json`, `MySQL_Wait_Event_Analyses_Details.json`; `dashboards/dashboards/PostgreSQL/PostgreSQL_Instance_Summary.json`; `dashboards/dashboards/OS/Node_Summary.json`
- Modify: `dashboards/dashboards/MySQL/MySQL_Instances_Overview.json`

**Interfaces:** none.

- [ ] **Step 1: Record the failing state**

Sweep `mysql-instance-summary` and `node-instance-summary` with `node_name=pmm-qa-aurora3-mysql-instance-1`: CPU Saturation is EMPTY.

- [ ] **Step 2: Add the RDS branch to each copy**

The panel exists in four versions; keep each version's own grouping (`by ()` or `by (node_name)`, shown here as `<by>`).
* Target B, `Normalized CPU Load`: append
  `or avg <by> (clamp_min(avg_over_time(node_procs_running{node_name=~"$node_name",node_type="remote_rds"}[$interval]), 0) / on (node_name) group_left max by (node_name) (rdsosmetrics_General_numVCPUs{node_name=~"$node_name"}))`
  (no `-1`: on RDS the count doesn't include a collector process, and it reads 0 on the QA writer).
* New target C, legend `CPU Utilization (all cores, RDS)`:
  `avg <by> (node_cpu_average{node_name=~"$node_name",node_type="remote_rds",cpu="All",mode="total"}) / 100`
  (RDS reports whole-instance CPU in percent, not per core; target A stays empty there).

- [ ] **Step 3: InnoDB I/O panels**

In `MySQL_Instances_Overview.json`, set the no-data text of panels 437–443 and 455–457 to `No data. InnoDB data file I/O is not reported on Amazon Aurora.`

- [ ] **Step 4: Verify**

Run `cleanup-dash.py` on every changed file and the `dashboards/misc` unit tests → PASS.
Load `MySQL_Instance_Summary.json` and `Node_Summary.json` on the test server and sweep them for the Aurora node: CPU Saturation is OK, and its saturation line never goes below 0 over the last hour.
Sweep `node-instance-summary` for the PMM server's own node: unchanged from before.

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Show CPU saturation on RDS nodes"`

### Task 3: Aurora overview dashboard and menu entry

**Files:**
- Create: `dashboards/dashboards/MySQL/Amazon_Aurora_Overview.json` (uid `aurora-overview`, title `Amazon Aurora Overview`)
- Modify: `dashboards/pmm-app/src/plugin.json` (add it to `includes` next to "MySQL Amazon Aurora Details")
- Modify: `ui/apps/pmm/src/contexts/navigation/navigation.constants.ts` (`NAV_MYSQL.children`)

**Interfaces:**
- Consumes: `aws_rds_instance_info{aws_cluster_id, aws_engine, aws_account_id}` and cluster `aws_rds_volume_bytes_used_average` from plan 01.
- Produces: uid `aurora-overview` and the panel titles `Aurora clusters` and `Aurora instances`, for plan 03.

- [ ] **Step 1: Write the cluster key once**

Every panel joins on this key `K` (value 1 per service, labels `node_id, region, aws_account_id, aws_cluster_id`):

```text
K = max by (node_id, region, aws_account_id, aws_cluster_id) (aws_rds_instance_info{aws_engine="aurora-mysql"})
    or
    label_replace(
      max by (node_id, region) (mysql_global_status_auroradb_commits) unless on (node_id) aws_rds_instance_info,
      "aws_cluster_id", "AWS cluster unknown", "", "")
U = max by (node_id, service_name) (mysql_up) or max by (node_id, service_name) (last_over_time(mysql_up[1h])) * 0
```

`U` keeps a service whose exporter stopped reporting, as 0, for an hour.

> **As built (final review):** the unknown branch is `group by (node_id, region) (last_over_time(mysql_global_status_auroradb_commits[1h])) unless on (node_id) aws_rds_instance_info` — `max by` of the counter returned the counter value instead of 1 — and every selector also carries `region=~"$region"`. The committed dashboard is the reference.

- [ ] **Step 2: Build the dashboard**

Variable: `region`, `label_values(mysql_up, region)`, include All. No other variable.
`Aurora clusters` table (instant queries merged by `region, aws_account_id, aws_cluster_id`), each column's description saying its source and lag:
* Monitored instances: `count by (region, aws_account_id, aws_cluster_id) (U * on (node_id) group_left(region, aws_account_id, aws_cluster_id) K)`
* Exporters connected: the same with `sum`, shown as `N of M` next to the count.
* Writers: `count by (region, aws_account_id, aws_cluster_id) ((max by (node_id) (mysql_global_variables_innodb_read_only) == 0) * on (node_id) group_left(region, aws_account_id, aws_cluster_id) K)`; value mapping `1` → `1 writer`, anything else → `changing`.
* Queries/s: `sum by (region, aws_account_id, aws_cluster_id) (rate(mysql_global_status_queries[$__rate_interval]) * on (node_id) group_left(region, aws_account_id, aws_cluster_id) K)`
* Storage used (about 10 minutes behind): `max by (region, aws_account_id, aws_cluster_id) (aws_rds_volume_bytes_used_average)`, bytes.

`Aurora instances` table: one row per `service_name` with cluster, role (`mysql_global_variables_innodb_read_only`: 0 writer, 1 reader, missing unknown), up (`U`), queries/s, and a data link to `/graph/d/mysql-amazonaurora/mysql-amazon-aurora-details?var-service_name=${__data.fields.service_name}`.
Dashboard links: Alerting and Advisors pages. Copy the table styling from `dashboards/dashboards/PMM Health/Environments_Overview.json`.

- [ ] **Step 3: Register and link it**

Add `{"type": "dashboard", "name": "Amazon Aurora Overview", "path": "dashboards/MySQL/Amazon_Aurora_Overview.json"}` to `plugin.json` `includes`, in the same form as the Aurora Details entry.
Add to `NAV_MYSQL.children`, after `mysql-summary`: `{ id: 'mysql-aurora', icon: DashboardOutlined, text: 'Amazon Aurora', url: `${PMM_NEW_NAV_GRAFANA_PATH}/d/aurora-overview/amazon-aurora-overview` }` (`DashboardOutlined` is already imported).

- [ ] **Step 4: Verify**

Run `cleanup-dash.py` on the new file and `cd ui && make lint && make format-check && make test` → PASS.
On the test server, with plan 01's pmm-client: load the dashboard and sweep `aurora-overview`; both tables have rows for every QA Aurora MySQL instance, and the storage column has data.
Then check the review-focus cases:
* With an older pmm-client on one instance, it appears under `AWS cluster unknown`.
* With that instance's mysqld_exporter stopped, its row shows down for up to an hour.
* With all three instances of the reader cluster added, storage equals the single CloudWatch value.
* After `aws rds failover-db-cluster`, within 2 minutes the cluster shows `1 writer` again and the instance table shows the new writer.

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Add Amazon Aurora overview and menu entry"`

### Task 4: User documentation

**Files:**
- Modify: `documentation/docs/reference/dashboards/dashboard-mysql-amazon-aurora-details.md`
- Create: `documentation/docs/reference/dashboards/dashboard-amazon-aurora-overview.md`
- Modify: `documentation/mkdocs-base.yml` (add the new page next to line 556)
- Modify: `documentation/docs/install-pmm/install-pmm-client/connect-database/aws.md`

- [ ] **Step 1:** Read `documentation/AGENTS.md`, then describe each panel and row, what `AWS cluster unknown` means and that storage is about 10 minutes behind. In `aws.md`, add one paragraph: Aurora instances are grouped by AWS cluster automatically after upgrading pmm-client; no permission change is needed.
- [ ] **Step 2:** `make doc-build-preview` and read both pages; expected: they render and link from the dashboards reference.
- [ ] **Step 3:** `git commit -s -m "PMM-15868 Document the Aurora dashboards"`; push, open the PR `PMM-15868 Aurora dashboards and overview` (follow the `pmm-dev:pmm-pr` skill), with the sweep output and screenshots.
