# Aurora monitoring, part 1: rds_exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rds_exporter publishes each instance's AWS cluster ID, engine and account, collects Aurora cluster storage, and reports filesystem series that PMM's Disk Space panels accept.

**Architecture:** The start-up `DescribeDBInstances` call already returns everything needed; keep three more fields per instance and serve them as one info series per instance on `/enhanced`. The `/basic` CloudWatch scraper adds one `VolumeBytesUsed` call per Aurora instance with the cluster dimension, and drops the three per-instance `Volume*` calls that never return data. Filesystem series get an empty `fstype`.

**Tech Stack:** Go, aws-sdk-go-v2 (`rds`, `cloudwatch`), prometheus/client_golang v1.14, testify.

**Spec:** [../spec.md](../spec.md), Technical Plan sections 1, 2 and 5.

**Repository:** percona/rds_exporter, branch `PMM-15868-aurora-cluster-info`, one PR.

## Global Constraints

* No new AWS permission: use only `DescribeDBInstances` and `GetMetricStatistics`, as today.
* Label names are exactly `aws_cluster_id`, `aws_engine`, `aws_account_id`; set them after the PMM labels from the config so a config label can't overwrite them.
* The info series is `aws_rds_instance_info`, value 1, served on `/enhanced` only.
* The cluster storage series is `aws_rds_volume_bytes_used_average`, only for engines starting with `aurora-`.
* CloudWatch calls per scrape: 48 per Aurora instance, 47 per plain RDS instance (today 50).
* Commits: `PMM-15868 <summary>`, signed off (`git commit -s`).

## Review Focus

1. **A config label named `aws_engine` or `aws_cluster_id`** (a user's custom node label): the AWS value must still win. Test in Task 2.
2. **An instance with both basic and enhanced metrics disabled:** it must still get its info series. Test in Task 2.
3. **An ARN that doesn't parse:** the instance still resolves, with an empty account. Test in Task 1.
4. **An Aurora instance with an empty cluster ID** (seen during creation): no cluster call. Test in Task 3.
5. **Plain RDS:** no cluster call, info series with an empty cluster ID. Tests in Tasks 2 and 3.

---

### Task 1: Keep cluster ID, engine and account from the start-up lookup

**Files:**
- Modify: `sessions/sessions.go` (`InstanceState`, `Instance`, `InstanceStates`, `New`)
- Test: `sessions/resolver_test.go`

**Interfaces:**
- Produces: `InstanceState` and `Instance` gain `ClusterID string`, `Engine string`, `AccountID string`.
- Produces: `func accountFromARN(arn string) string` in package `sessions`.

- [ ] **Step 1: Write the failing tests**

In `resolver_test.go`, using the existing `fakeRDSClient` and `describePage`:
* `TestAccountFromARN`: `"arn:aws:rds:us-east-2:123456789012:db:a3"` → `"123456789012"`; `"arn:aws-us-gov:rds:us-gov-west-1:111122223333:db:x"` → `"111122223333"`; `""` → `""`; `"not-an-arn"` → `""`.
* `TestInstanceStatesAuroraFields`: one page with an instance whose `DBClusterIdentifier` is `"cluster-a"`, `Engine` `"aurora-mysql"`, `DBInstanceArn` `"arn:aws:rds:us-east-2:123456789012:db:a3"`, and a second plain instance with `Engine` `"mysql"` and no cluster. Assert `states["a3"]` has `ClusterID "cluster-a"`, `Engine "aurora-mysql"`, `AccountID "123456789012"`, and the plain one has `ClusterID ""`, `Engine "mysql"`.

- [ ] **Step 2: Run them to see them fail**

Run: `go test ./sessions -run 'TestAccountFromARN|TestInstanceStatesAuroraFields'`
Expected: FAIL, compile error on the missing fields and function.

- [ ] **Step 3: Implement**

`accountFromARN` returns the fifth `:`-separated field when the string has at least six fields and starts with `arn:`, otherwise `""`.
`InstanceStates` fills the three fields with `aws.ToString` on `DBClusterIdentifier`, `Engine`, and `accountFromARN(aws.ToString(DBInstanceArn))`.
`New` copies them into each resolved `Instance` next to `ResourceID`.

- [ ] **Step 4: Run the package tests**

Run: `go test ./sessions -run 'TestAccountFromARN|TestInstanceStates'`
Expected: PASS (`TestSession` reads real AWS and is not part of this run).

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Keep cluster ID, engine and account per instance"`

### Task 2: Info series on `/enhanced`

**Files:**
- Create: `info/collector.go`, `info/collector_test.go`
- Modify: `main.go` (the enhanced registry block)

**Interfaces:**
- Consumes: `sessions.Instance` fields from Task 1, plus the existing `Region`, `Instance`, `Labels`, `DisableBasicMetrics`, `DisableEnhancedMetrics`.
- Produces: `type InstanceSource interface { AllSessions() map[string][]sessions.Instance }`, `func NewCollector(src InstanceSource) *Collector` (a `prometheus.Collector`). `*sessions.Sessions` satisfies `InstanceSource`.

- [ ] **Step 1: Write the failing test**

`TestCollector` with a fake `InstanceSource` holding:
* `a3`: region `us-east-2`, `Engine "aurora-mysql"`, `ClusterID "cluster-a"`, `AccountID "123456789012"`, `Labels {"node_name": "a3", "aws_engine": "spoof"}`, both disable switches `true`;
* `m84`: region `us-east-2`, `Engine "mysql"`, empty cluster and account, `Labels {"node_name": "m84"}`.

Register the collector on a new registry, `Gather()`, and assert there are exactly two `aws_rds_instance_info` series, each with value 1, whose labels (an absent label and an empty one count as the same) are:
* `{region: us-east-2, instance: a3, node_name: a3, aws_engine: aurora-mysql, aws_cluster_id: cluster-a, aws_account_id: 123456789012}`;
* `{region: us-east-2, instance: m84, node_name: m84, aws_engine: mysql, aws_cluster_id: "", aws_account_id: ""}`.

- [ ] **Step 2: Run it to see it fail**

Run: `go test ./info`
Expected: FAIL, package `info` has no `NewCollector`.

- [ ] **Step 3: Implement `NewCollector` and its `Describe`/`Collect`**

`Collect` loops over `AllSessions()`, builds the label map from `region`, `instance`, then `Labels`, then the three `aws_*` labels (in that order, later keys win), and sends a `prometheus.MustNewConstMetric` gauge of 1 with a per-instance `NewDesc`, as `basic/scraper.go` does. `Describe` sends nothing (an unchecked collector, like `basic.Collector`).
In `main.go`, add `registry.MustRegister(info.NewCollector(sess))` next to `enhanced.NewCollector`.

- [ ] **Step 4: Run it to see it pass**

Run: `go test ./info ./sessions`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Publish aws_rds_instance_info on /enhanced"`

### Task 3: Aurora cluster storage; drop per-instance `Volume*`

**Files:**
- Modify: `basic/metrics.go` (remove the `VolumeBytesUsed`, `VolumeReadIOPs`, `VolumeWriteIOPs` entries by hand; the `go:generate` target doesn't exist)
- Modify: `basic/scraper.go`
- Create: `basic/scraper_test.go`
- Modify, only if `TestCollector`'s AWS account has an Aurora instance: `basic/testdata/all.txt`

**Interfaces:**
- Consumes: `sessions.Instance` (`Engine`, `ClusterID`, `AccountID`) from Task 1; `GetConfig` already returns it.
- Produces: `func clusterVolumeParams(instance *sessions.Instance, end time.Time) *cloudwatch.GetMetricStatisticsInput`, returning nil unless `strings.HasPrefix(instance.Engine, "aurora-")` and `instance.ClusterID != ""`.

- [ ] **Step 1: Write the failing test**

`TestClusterVolumeParams`, with `end := time.Date(2026, 11, 4, 12, 0, 0, 0, time.UTC)`:
* `aurora-mysql`, cluster `cluster-a` → non-nil, `MetricName "VolumeBytesUsed"`, `Namespace "AWS/RDS"`, one dimension `DBClusterIdentifier=cluster-a`, `Statistics [Average]`, `Period 60`, `EndTime end`, `StartTime end.Add(-Range)`;
* `aurora-postgresql`, empty cluster → nil;
* `mysql`, cluster `x` → nil.

- [ ] **Step 2: Run it to see it fail**

Run: `go test ./basic -run TestClusterVolumeParams`
Expected: FAIL, undefined `clusterVolumeParams`.

- [ ] **Step 3: Implement**

`NewScraper` keeps the `*sessions.Instance` returned by `GetConfig`.
`Scrape` builds `clusterVolumeParams(inst, time.Now().Add(-Delay))`; when non-nil, it runs that one call alongside the per-metric goroutines and emits `aws_rds_volume_bytes_used_average` with the scraper's `constLabels` plus `aws_cluster_id` and `aws_account_id`, using the same latest-datapoint rule as `scrapeMetric`.
Keep the window as for every other metric; widen it only if the spike in plan 02 shows AWS publishes `VolumeBytesUsed` less often than every 10 minutes.

- [ ] **Step 4: Run the unit test, then the whole package**

Run: `go test ./basic -run TestClusterVolumeParams` → PASS.
Run: `go test ./basic` → `TestCollector` reads real CloudWatch through `config.tests.yml`; with AWS credentials it passes, or with `-golden-txt` it rewrites `all.txt` when an Aurora instance adds the new series. Without credentials, note it in the PR as not run.

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Collect Aurora cluster storage by cluster ID"`

### Task 4: Empty `fstype` on filesystem series

**Files:**
- Modify: `enhanced/metrics.go` (`makeNodeFilesystemMetrics`)
- Modify: `enhanced/testdata/*.txt` (four golden files; inputs are recorded JSON, no AWS needed)

**Interfaces:** none.

- [ ] **Step 1: Change the expected output first**

Run: `go test ./enhanced -run TestParse` → PASS (baseline). Then in `makeNodeFilesystemMetrics` set the label values to `{s.Name, "", s.MountPoint}` and delete the comment that explains copying the name into `fstype`.

- [ ] **Step 2: See the golden test fail**

Run: `go test ./enhanced -run TestParse`
Expected: FAIL, `fstype` differs in all four instances.

- [ ] **Step 3: Regenerate and inspect**

Run: `go test ./enhanced -run TestParse -golden-txt`, then `git diff enhanced/testdata`.
Expected: only `fstype` values change on `node_filesystem_*` lines; `grep -c 'fstype="oscar' enhanced/testdata/*.txt` prints 0 for every file.

- [ ] **Step 4: Run the package**

Run: `go test ./enhanced` → PASS.

- [ ] **Step 5: Commit**

`git commit -s -m "PMM-15868 Leave fstype empty on RDS filesystem series"`

### Task 5: Release notes, full check, PR

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1:** Add to `CHANGELOG.md` and the metrics part of `README.md`: new `aws_rds_instance_info` (labels as above), cluster-level `aws_rds_volume_bytes_used_average` for Aurora, removal of the per-instance `Volume*` metrics, empty `fstype` on `node_filesystem_*`.
- [ ] **Step 2:** Run `make test` (expect PASS apart from the AWS-backed tests noted in Task 3). Build the linter as CI does, `go build -modfile=tools/go.mod -o bin/golangci-lint github.com/golangci/golangci-lint/v2/cmd/golangci-lint`, then `make check` (expect no findings).
- [ ] **Step 3: Check on the test PMM Server**

Build with `make release`, copy the binary over `/usr/local/percona/pmm/exporters/rds_exporter` in the `pmm-server` container, and restart its pmm-agent (`docker exec pmm-server supervisorctl restart pmm-agent`). The test server needs the QA Aurora instances and one plain RDS MySQL instance. After 15 minutes:
* `aws_rds_instance_info` exists for every RDS instance: Aurora ones with `aws_cluster_id`, `aws_engine` and `aws_account_id`, the plain one with an empty cluster ID.
* `aws_rds_volume_bytes_used_average` exists for each Aurora instance, with `aws_cluster_id`.
* `node_filesystem_size_bytes` on RDS nodes has no `fstype`, and the panel sweep of `mysql-instance-summary` shows Disk Space as OK for the Aurora and the plain RDS node.
* `sum(rate(rds_exporter_requests_total[30m])) * 60` is no higher than before the change (about 51 per instance per minute was measured on 2026-11-04).

- [ ] **Step 4:** `git commit -s -m "PMM-15868 Document the Aurora series"`; `git fetch origin main`, rebase if needed, `git push -u origin HEAD`; open the PR titled `PMM-15868 Publish Aurora cluster info and storage`, linking the spec.
