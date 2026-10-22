# PMM specs: guide for AI agents

Specs, implementation plans and architecture decision records (ADRs) for [Percona Monitoring and Management](https://github.com/percona/pmm). Code stays in the component repos; the design behind it lives here.

## Layout

One folder per piece of work under `tickets/`, named `<JIRA-KEY>-<short-name>`. Use the epic's key when the work spans several tickets, otherwise the ticket's own key.

```
tickets/PMM-15567-otel/
├── README.md        status, related tickets, PRs
├── spec.md          what and why: the design
├── plans/           how: implementation plans, numbered in execution order (00-roadmap.md, 01-….md)
└── adr/             decisions: README.md index + ADR-NN-short-title.md
```

Create only the parts the work needs; a small change may need just `spec.md`. Add each new folder to the index in [README.md](README.md).

## Rules

- **Before starting work on a ticket**, look for its folder (or its epic's) and follow the spec and plans there. Record decisions made along the way back into them.
- **Review before code.** A spec or plan lands here through a PR, reviewed before implementation starts.
- **ADRs:** number them within the folder. Never rewrite an accepted ADR to change its decision; add a new one that supersedes it.
- **No dates in file names**; git keeps the history.
- **This repo is public.** No customer names, credentials, internal hostnames, or details of unfixed security issues (see [SECURITY.md](https://github.com/percona/pmm/blob/main/SECURITY.md)).
