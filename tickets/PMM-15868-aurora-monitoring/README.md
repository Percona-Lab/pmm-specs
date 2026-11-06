# PMM-15868 Aurora monitoring

*   **Status:** Release 1 implemented, in code review; live checks of plain RDS and an Aurora PostgreSQL reader pending. Release 2 (Aurora PostgreSQL details) not started.
*   **PR:** [Percona-Lab/pmm-specs#7](https://github.com/Percona-Lab/pmm-specs/pull/7) (design review).
*   **Code:** [percona/rds_exporter#127](https://github.com/percona/rds_exporter/pull/127), [percona/pmm#6287](https://github.com/percona/pmm/pull/6287), [percona/pmm-qa#1741](https://github.com/percona/pmm-qa/pull/1741); Feature Build [Percona-Lab/pmm-submodules#4685](https://github.com/Percona-Lab/pmm-submodules/pull/4685).
*   **Epic:** [PMM-15868](https://perconadev.atlassian.net/browse/PMM-15868).
*   **Related:** [PMM-6655](https://perconadev.atlassian.net/browse/PMM-6655), [PMM-1795](https://perconadev.atlassian.net/browse/PMM-1795), [PMM-3050](https://perconadev.atlassian.net/browse/PMM-3050), [PMM-13610](https://perconadev.atlassian.net/browse/PMM-13610) (children of the epic); [PMM-9191](https://perconadev.atlassian.net/browse/PMM-9191), [PMM-14527](https://perconadev.atlassian.net/browse/PMM-14527), [PMM-2288](https://perconadev.atlassian.net/browse/PMM-2288) (related).

| File | What it is |
|---|---|
| [spec.md](spec.md) | The design as built: what and why, decision log, technical plan, alternatives, files changed, acceptance criteria |
| [concepts_brief.md](concepts_brief.md) | Brainstorm brief after two independent review rounds; history, superseded by spec.md |
| [research.md](research.md) | Findings from a live check on Aurora instances and from reading rds_exporter, before this epic |
| [plans/01-rds-exporter.md](plans/01-rds-exporter.md) | Release 1 plan, percona/rds_exporter: info series, cluster storage, empty `fstype` |
| [plans/02-pmm-dashboards.md](plans/02-pmm-dashboards.md) | Release 1 plan, percona/pmm: Aurora Details fixes, CPU Saturation, docs; its overview task was replaced by the native Amazon RDS page |
| [plans/03-pmm-qa.md](plans/03-pmm-qa.md) | Release 1 plan, percona/pmm-qa; replaced by Playwright tests PMM-T2504 and PMM-T2505 |
| [tools/panelcheck.py](tools/panelcheck.py) | Panel sweep: runs every panel query of a dashboard against a live PMM and reports empty panels |
