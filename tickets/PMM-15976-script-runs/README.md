# Script runs in pmm-agent, and the removal of Nomad

- **Epic:** [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976). It follows the spike [PMM-15696](https://perconadev.atlassian.net/browse/PMM-15696), and belongs with [PMM-15254](https://perconadev.atlassian.net/browse/PMM-15254), "PMM Extensions (GA)".
- **Status:** design in review. ADR-01 is accepted: pmm-agent replaces Nomad as the way PMM Extensions runs tasks on PMM Client hosts. ADR-02 to ADR-14 are proposed. Nothing is implemented.
- **Target:** PMM 3.12.0 for script runs, with Nomad deprecated; the release after it for the removal of Nomad.
- **Prototype:** branch `PMM-15696-proto` in percona/pmm ([percona/pmm#6414](https://github.com/percona/pmm/pull/6414)). A reference only; it is not merged.
- **Repos touched:** percona/pmm (pmm-agent, pmm-managed, the API, packaging, documentation), percona/pmm-extensions, percona/pmm-qa.

| Plan | Ticket | Pull requests |
|---|---|---|
| 01 The `run_script` job in pmm-agent | PMM-15977 | — |
| 02 Run records and the API in pmm-managed | PMM-15978 | — |
| 03 Containment and host-side controls | PMM-15979 | — |
| 04 The executor in PMM Extensions | PMM-15980 | — |
| 05 Switch-over and deprecation | PMM-15981 | — |
| 06 Verification and release gate | PMM-15982 | — |
| 07 Remove Nomad | PMM-15983 | — |
| Follow-up of 07, in 3.14.0: delete the flags and settings that 3.13.0 still accepts | PMM-15984 | — |

| Path | Content |
|---|---|
| [spec.md](spec.md) | Analysis and design: why Nomad goes, what a replacement needs, what the spike measured for each option, the design in pmm-agent, pmm-managed and PMM Extensions, access and HA, the removal of Nomad, tests T1 to T26, decisions, open questions |
| [adr/](adr/README.md) | ADR-01 records the choice of pmm-agent. ADR-02 to ADR-14 are the design decisions that follow |
| [plans/](plans/00-roadmap.md) | Roadmap, the shared contract and the release gate; plans 01 and 02 in full, plans 03 to 07 at task level |
