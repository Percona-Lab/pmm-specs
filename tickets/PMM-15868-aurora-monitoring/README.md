# PMM-15868 Aurora monitoring

*   **Status:** design proposed, awaiting review.
*   **PR:** [Percona-Lab/pmm-specs#7](https://github.com/Percona-Lab/pmm-specs/pull/7) (design review).
*   **Epic:** [PMM-15868](https://perconadev.atlassian.net/browse/PMM-15868).
*   **Related:** [PMM-6655](https://perconadev.atlassian.net/browse/PMM-6655), [PMM-1795](https://perconadev.atlassian.net/browse/PMM-1795), [PMM-3050](https://perconadev.atlassian.net/browse/PMM-3050), [PMM-13610](https://perconadev.atlassian.net/browse/PMM-13610) (children of the epic); [PMM-9191](https://perconadev.atlassian.net/browse/PMM-9191), [PMM-14527](https://perconadev.atlassian.net/browse/PMM-14527), [PMM-2288](https://perconadev.atlassian.net/browse/PMM-2288) (related).

| File | What it is |
|---|---|
| [spec.md](spec.md) | The design: what and why, technical plan, alternatives, files to change, verification |
| [concepts_brief.md](concepts_brief.md) | Brainstorm brief after two independent review rounds |
| [research.md](research.md) | Findings from a live check on Aurora instances and from reading rds_exporter |
| [plans/01-rds-exporter.md](plans/01-rds-exporter.md) | Release 1 plan, percona/rds_exporter: info series, cluster storage, empty `fstype` |
| [plans/02-pmm-dashboards.md](plans/02-pmm-dashboards.md) | Release 1 plan, percona/pmm: Aurora Details fixes, CPU Saturation, Aurora overview, menu, docs |
| [plans/03-pmm-qa.md](plans/03-pmm-qa.md) | Release 1 plan, percona/pmm-qa: PMM-T1295 and an overview test |
| [tools/panelcheck.py](tools/panelcheck.py) | Panel sweep: runs every panel query of a dashboard against a live PMM and reports empty panels |
