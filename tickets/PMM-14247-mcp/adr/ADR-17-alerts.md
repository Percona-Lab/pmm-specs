# ADR-17: Alerts

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26, 2026-11-02, 2026-11-03, 2026-11-04, 2026-11-06 and 2026-11-10 (the live check of plan 07 Task 1, [below](#live-check-plan-07-task-1))
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (plan 07)

## Context

PMM alerting is Grafana's alerting; PMM adds rule templates (`/v1/alerting`). Firing alerts are a common starting point for triage, and without them an AI client can't answer "what is wrong right now". Grafana's Prometheus-style rules API applies Grafana's folder permissions: it returns only the rules in folders the caller can read, each with its alert instances. Grafana's alert list endpoints are not folder-scoped. None of them applies an Access Role filter [V]. PMM's own alert page reads the rules API (`ui/apps/pmm/src/api/alerting.ts`) [V]. pmm-managed already calls Grafana's alerting API with the caller's headers (`managed/services/grafana/client.go:732`) [V].

## Options

1. MCP reads Grafana's alert API directly, with the caller's credentials, and narrows the result to the caller's service list (ADR-03).
2. The Grafana fork filters alerts by the caller's Access Roles. Rejected for this epic: a change and a release of the Grafana fork.
3. pmm-managed serves a read API that fetches alerts from Grafana and filters them with a PMM-wide matcher (ADR-16). Rejected for this epic: it needs ADR-16's PMM-wide plumbing, which is deferred.

## Decision

Option 1.
- **Source.** `pmm_alerts` reads the firing alerts from Grafana's rules API (`/graph/api/prometheus/grafana/api/v1/rules`) through nginx on loopback, with the caller's `Authorization` and `Cookie`, like every backing call (ADR-03). That API is folder-scoped, so `pmm_alerts` shows a Viewer what PMM's own alert page shows. The alert list endpoints (`/graph/api/alertmanager/grafana/api/v2/alerts`, `/graph/api/prometheus/grafana/api/v1/alerts`) are not folder-scoped, and never supply the list.
- **Silence state** comes from Grafana's Alertmanager (its alerts and silences) and is joined by rule UID and label set: an Alertmanager alert marks the alert of a rule the rules API returned when its `labels` equal that alert's `labels` plus `__alert_rule_uid__` set to the rule's `uid`, compared as whole maps. An Alertmanager alert that matches no such alert adds nothing. The rule UID alone isn't enough: one rule fires one alert per label set, and a silence can cover some of them (the [live check](#join-key) silenced one of a rule's two alerts). Labels never join without the rule UID. MCP reads the silence state from the Alertmanager alert (`status.silencedBy`) and never evaluates silence matchers itself.
- Plan 07 Task 1 checked both on a live server, with what a Viewer, an Editor and a Viewer service account get; the [live check](#live-check-plan-07-task-1) records the field mapping and the evidence. No pmm-managed API and no Grafana fork change.
- **Narrowing.** Against the caller's list (ADR-08), which holds services and nodes of every type:
  - A service or node label whose value is `[no value]` counts as absent. A rule made from a PMM template through `/v1/alerting/rules` carries `service_name` and `node_name` labels templated from its query's series (`managed/services/alerting/service.go:814-815`, PMM-14911), and Grafana writes `[no value]` when the series lacks the label [V]. Otherwise every node-level and server-level alert of such a rule would be dropped ([live check](#labels-of-template-rules)).
  - An alert that names a service is kept when every service label it carries is in the list (`service_id` against the list's service IDs, `service_name` against its service names), whatever node it names. PMM's `*_down` templates aggregate `pmm_managed_inventory_agents`, whose `node_name` is the node the exporter's pmm-agent runs on (`managed/services/inventory/inventory_metrics.go:155-161`), while the `up` series behind the list carry the service's own node (`managed/services/victoriametrics/prometheus.go:102-109`) [V]. RDS and Azure exporters always run on PMM Server's own pmm-agent (`managed/services/management/rds.go:293`, `azure_database.go:199`) [V], so those services' down alerts name PMM Server's node (`pmm-server`), which a restricted caller's list usually lacks.
  - An alert that names no service but names a node is kept when every node label it carries is in the list (`node_id` against its node IDs, `node_name` against its node names).
  - An alert with none of these labels, such as a server-level alert or one whose rule aggregates them away, is kept: Grafana's alert list shows it to the same caller.
  - So is every alert of PMM's own rules, whatever it names: the HA and PMM Server component rules PMM provisions (`managed/services/alerting/provisioning_catalog.go`), whose `node_id`, `node_name` and `service_name` name PMM Server replicas (`PMM_HA_NODE_ID`) and components (a scrape job such as `clickhouse`), not services or nodes in the list. A rule is PMM's own when the rules API returns it with `provenance` `file` and a `uid` from PMM's catalog (`catalogUIDs()`, `managed/services/alerting/provisioning_catalog.go:136`), both at once; the rules API carries both for each rule, to a Viewer too [V]. The UID alone isn't enough: a UID PMM doesn't provision on a deployment, such as the HA UIDs on a standalone server, can be taken by an Editor's rule, which then has no provenance [V]. Provenance alone isn't enough either: it marks any rule provisioned from a file, not only PMM's [I]. Never by a label, since a rule's author sets its labels, `pmm_provisioned` included ([live check](#pmms-own-rules)).
- **Look-back for alerts.** The list used to narrow alerts covers 7 days of `up` samples, not the 1 hour of the other tools (ADR-08). A service whose pmm-agent went silent sends no `up` samples, yet its alerts, the one saying it is down included, are what a triage needs; with the 7-day list they stay for 7 days.
- Narrowed, not filtered: not a security boundary (ADR-03). Filtering alerts by Access Role is PMM-wide work (ADR-16, deferred).
- **Tool.** `pmm_alerts` returns firing alerts, silenced or not, with name, severity, labels, summary and description, start time, whether it is silenced and until when, and a link to it in PMM. It filters by service, node and severity, and pages (ADR-11). The tool description and every result, an empty one included, say "Currently firing alerts only; resolved alerts are not shown."
- **Untrusted text.** Summaries and descriptions are written by rule authors and may name other services. They are returned as written, marked untrusted in the contract (ADR-11), and never used for narrowing.
- **Read only.** Silencing, acknowledging and editing rules stay out (ADR-05).

## Consequences

- An AI client sees the firing alerts of its services, and the server-level ones, with no new PMM API.
- A restricted caller still reads every alert of the folders it can read through Grafana's API and UI, as today. An alert of a rule in a folder it can't read doesn't reach it through MCP either.
- MCP doesn't drop server-level alerts.
- A service that sent no `up` sample for 7 days leaves the list used for alerts, so its alerts are dropped after 7 days of silence, including the one saying it is down. The 7-day list query reads more than the 1-hour one; plan 06 measures both.
- Alerts evaluated by VMAlert from PMM's rule files, visible only to Admins, are out of scope.
- Currently firing alerts only, and every result says so, so an empty list is never read as "nothing happened". Reading Grafana's alert state history for a time window, narrowed the same way, is a follow-up ticket outside this epic.
- Tests: a restricted caller, with a positive and with a negative filter, against alerts with the service's labels, another service's labels, node labels only, and none; and the `mysql_down` template, which aggregates `by (service_id, service_name, node_name)`, under a role on `environment`, a label the alert doesn't carry, for a service whose pmm-agent runs on another node (an RDS service, `node_name="pmm-server"`): kept, because the service it names is in the list; and, for a restricted caller, `pmm_ha_node_unreachable` (`node_id` = `PMM_HA_NODE_ID`) and `pmm_clickhouse_down` (`service_name="clickhouse"`) on HA, and `pmm_grafana_down` on a standalone server: kept, as alerts of PMM's own rules; a user's rule labelled `pmm_provisioned="1"` that names a service outside the list: dropped; an Editor's rule that takes a catalog UID PMM doesn't provision here, with no provenance: narrowed like any user rule; a node-level and a server-level alert of a rule made from a PMM template, whose `service_name`, and for the server-level one `node_name`, is `[no value]`: kept as a node-only alert when its node is in the list, and as an alert with no service or node label; two alerts of one rule with a silence on one of them: only that one is silenced, until the silence's end; and, for a Viewer, a rule in a folder without Viewer access, silenced or not: absent.
- An alert that starts firing between the read of the rules API and the read of the Alertmanager has no Alertmanager match yet, and is returned as not silenced until the next call [I].

## Live check (plan 07 Task 1)

Run on 2026-11-10. Everything in this section was observed on that server [V], except what is marked [I].

**Server.** `perconalab/pmm-server:3-dev-latest` (digest `sha256:cce7274c6874…`, built 2026-11-09; PMM 3.10.1, pmm-managed `7714ac6d0`), with Grafana 12.4.14, Open Source edition. The MCP branch doesn't change Grafana, so the development image stands in for a Feature Build. Two Percona Server 8.0.46 services (`mysql` type), each on its own container node with PMM Client 3.10.1, registered with pmm-framework. Every call went through nginx (`/graph/api/...`).

**Setup.**
- Folders: `mcp-alerts-visible` with Grafana's default permissions, and `mcp-alerts-hidden` without the Viewer role (Editor: Edit, Admin: Admin).
- Rules from PMM templates, through `POST /v1/alerting/rules`, evaluated every 10 seconds. The service alerts fire on a low threshold; no mysqld was stopped.
  - In `mcp-alerts-visible`: `pmm_mysql_too_many_connections` with threshold 0, one alert per service (two); `pmm_node_high_cpu_load` with threshold 0, one alert per node (three: `pmm-server` and the two service nodes); and a custom template on `vector(1)`, one alert whose query has no labels.
  - In `mcp-alerts-hidden`: the same connections rule (two alerts) and the same `vector(1)` rule.
- Silences, created by Admin: on the visible connections rule, matching `__alert_rule_uid__` and the first service's `service_name`; on the hidden connections rule, matching `__alert_rule_uid__` only.
- Callers: Admin; an Editor user; a Viewer user; a service account with the Viewer role, called with its token.

### Folder permissions per caller

Every call returned 200.

| Caller | Rules API, `/api/prometheus/grafana/api/v1/rules` | Alert list endpoints, `/api/alertmanager/grafana/api/v2/alerts` and `/api/prometheus/grafana/api/v1/alerts` | Silences, `/api/alertmanager/grafana/api/v2/silences` |
|---|---|---|---|
| Admin | 9 rules (the check's 5 and PMM's 4), 9 firing alerts | all 9 firing alerts | both |
| Editor user | the same as Admin | all 9 | both |
| Viewer user | 7 rules (the visible folder's 3 and PMM's 4), 6 firing alerts; nothing of `mcp-alerts-hidden` | all 9, the hidden folder's included | both, the hidden rule's included |
| Viewer service account | the same as the Viewer user, field for field | the same | the same |

The Viewer also gets 403 for the hidden folder (`/api/folders/mcp-alerts-hidden`) and for its rules in the ruler API. The rules API is folder-scoped; the alert list endpoints and the silences are not. `state=firing` returns only the rules with firing alerts, and only those alerts.

### Field mapping

`rule` is an element of `data.groups[].rules[]` in the rules API, `alert` one of `rule.alerts[]`, and `am` one of `/api/v2/alerts`.

| Our field | Rules API | Alertmanager | Notes |
|---|---|---|---|
| name | `rule.name`, the same as `alert.labels.alertname` | `am.labels.alertname` | The rule's title. |
| severity | `alert.labels.severity` | `am.labels.severity` | PMM templates set it; a rule without the label has none. |
| labels | `alert.labels` | `am.labels` | Without `includeInternalLabels=true`, the rules API leaves out `__alert_rule_uid__` and `__alert_rule_namespace_uid__`. The Alertmanager has `__alert_rule_uid__` and never `__alert_rule_namespace_uid__`. `grafana_folder`, the folder title, is on both. |
| summary, description | `alert.annotations.summary`, `alert.annotations.description` | `am.annotations` | Expanded for each alert; `rule.annotations` holds the unexpanded templates. The Alertmanager adds `__orgId__`, `__value_string__` and `__values__`. |
| start time | `alert.activeAt` | `am.startsAt` | Equal. |
| firing | `alert.state` is `Alerting`, with a reason in brackets after it in some states | The Alertmanager lists firing alerts only [I]; `am.status.state` is `active` or `suppressed`. | A silenced alert is still `Alerting` in the rules API. |
| silenced | none | `am.status.silencedBy` not empty | `suppressed` also covers inhibition (`inhibitedBy`), so read `silencedBy`. |
| silence end | none | `endsAt` of the silences named in `silencedBy`, from `/api/v2/silences` | `am.endsAt` is the alert's own resolve time, two minutes after its last evaluation here, not the silence's end. With several silences, the alert stays silenced until the last one ends [I]. |
| rule UID | `rule.uid` | `am.labels.__alert_rule_uid__` | |
| PMM's own rule | `rule.provenance` is `file` and `rule.uid` is in PMM's catalog | none | `provenance` is absent for a rule made through the ruler API, `/v1/alerting/rules` or the UI, and `api` for one made through the provisioning API. |
| folder | `group.folderUid`, `group.file` (the title) | `am.labels.grafana_folder` | |
| link in PMM | `/graph/alerting/grafana/<rule.uid>/view`, built | `am.generatorURL` has that path on Grafana's root URL, `https://localhost` on this server | Build the link from the rule UID. |
| fingerprint | none | `am.fingerprint` | A hash of `am.labels`; the join doesn't need it. |

### Join key

The visible connections rule (`uid` `ag3v0zhlw1zwgf`) fired one alert per service, and the silence covered the first service only. As the Viewer got them, with UUIDs shortened:

| | First service | Second service |
|---|---|---|
| Rules API `alert.labels` | `agent_id`, `agent_type` `mysqld_exporter`, `alertname` `MCP two services`, `cluster`, `environment`, `grafana_folder` `MCP live check, visible`, `instance`, `machine_id`, `node_id` `e25059af-…`, `node_name` `ps_pmm_8_0_1`, `node_type` `container`, `percona_alerting` `1`, `service_id` `7c4993d6-…`, `service_name` `ps_pmm_8_0_1_25708`, `service_type` `mysql`, `severity` `warning`, `template_name` `pmm_mysql_too_many_connections` | the same keys; `node_id` `fdbacb20-…`, `node_name` `ps_pmm_8_0_2`, `service_id` `662ce19c-…`, `service_name` `ps_pmm_8_0_2_25708` |
| Rules API `alert.state`, `alert.activeAt` | `Alerting`, `08:12:00Z` | `Alerting`, `08:12:00Z` |
| Alertmanager `am.labels` | the rules API's labels and `__alert_rule_uid__` `ag3v0zhlw1zwgf` | the rules API's labels and `__alert_rule_uid__` `ag3v0zhlw1zwgf` |
| Alertmanager `am.fingerprint` | `dc8e18df394ac87e` | `81ab936ff62a5495` |
| Alertmanager `am.status` | `suppressed`, `silencedBy` `["dbe85b6a-…"]`, `inhibitedBy` `[]` | `active`, `silencedBy` `[]`, `inhibitedBy` `[]` |
| Alertmanager `am.startsAt`, `am.endsAt` | `08:12:00Z`, `08:14:30Z` | `08:12:00Z`, `08:14:30Z` |

Silence `dbe85b6a-…`: matchers `__alert_rule_uid__="ag3v0zhlw1zwgf"` and `service_name="ps_pmm_8_0_1_25708"`, `endsAt` `2026-11-11T08:12:09Z`.

- A join on the rule UID alone would mark both alerts silenced; only the first is.
- The key that marks exactly the silenced alert is the rule UID with the label set: a rules-API alert's labels from the default call, plus `__alert_rule_uid__` set to `rule.uid`, equal the labels of exactly one Alertmanager alert. That held for every firing alert: 9 of 9 for Admin and Editor, 6 of 6 for the Viewer and its service account.
- No other label needs normalising. A rule with simplified routing (a contact point set on the rule) adds `__grafana_autogenerated__` and `__grafana_receiver__`, and both APIs carry them. With `includeInternalLabels=true`, drop `__alert_rule_namespace_uid__` instead of adding the UID.
- The evidence shows no better key: `am.fingerprint` is a hash of the same labels, and the rules API has none.
- PMM's alert page joins on the labels without their `__`-prefixed ones, and without the rule UID (`serializeVisibleLabels` in `ui/apps/pmm/src/pages/alerting/status/AlertsPage.utils.ts`).

### Labels of template rules

| Rule | `alert.labels.service_name` | `alert.labels.node_name` |
|---|---|---|
| Connections, one alert per service | the service | the service's node |
| Node CPU, one alert per node | `[no value]` | the node |
| `vector(1)` | `[no value]` | `[no value]` |
| PMM's component rules | absent | `pmm-server`, with `instance` `pmm-server` and `job` naming the component |

`/v1/alerting/rules` gives every rule it creates the labels `service_name` and `node_name`, each the template `{{ if $labels.X }}{{ $labels.X }}{{ else }}{{ $values.A.Labels.X }}{{ end }}` (`managed/services/alerting/service.go:814-815`, `buildRuleLabelTemplate`). Go writes `<no value>` for a missing label, and Grafana replaces it with `[no value]` (percona/grafana `pkg/services/ngalert/state/template/template.go:156`). Every alert carries `alertname`, `severity` and `grafana_folder`; none carries its rule UID as a label in the rules API's default call.

### PMM's own rules

A standalone server provisions the components bundle only; the HA rules aren't there. The rules API returns the same four rules to Admin, the Editor, the Viewer and the Viewer service account, because the folder grants the Viewer role View:

| `uid` | Name | `provenance` |
|---|---|---|
| `pmm-victoriametrics-down` | PMM VictoriaMetrics is down | `file` |
| `pmm-clickhouse-down` | PMM ClickHouse is down | `file` |
| `pmm-grafana-down` | PMM Grafana is down | `file` |
| `pmm-qan-api2-down` | PMM Query Analytics API is down | `file` |

They are in folder `PMM Server`, whose UID is generated on each server, and group `PMM Managed`, with the labels `percona_alerting`, `pmm_provisioned`, `severity` and `template_name`. They didn't fire during the check.

- The provisioning API refuses a rule with the UID of a rule PMM provisioned (`pmm-grafana-down`: 409, a unique-constraint conflict). A rule it creates gets `provenance` `api`, or none with `X-Disable-Provenance`.
- An Editor created a rule with the UID `pmm-ha-no-leader`, free on a standalone server, and the label `pmm_provisioned="1"`, through the ruler API. The rules API returned it to the Viewer with no provenance. The rule was deleted after the check.
- So the catalog UID needs `provenance` `file` with it, and neither the folder nor a label identifies PMM's rules.
