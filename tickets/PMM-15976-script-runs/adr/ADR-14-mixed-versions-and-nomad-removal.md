# ADR-14: Mixed versions, and the removal of Nomad in two releases

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976), [PMM-15696](https://perconadev.atlassian.net/browse/PMM-15696)
- Planned in: [plans 05](../plans/05-switch-over.md) and [07](../plans/07-remove-nomad.md)

## Context

Nomad is in PMM since 3.2.0, and is named in 146 files of percona/pmm [V]. What is public about it:
- The environment variables `PMM_ENABLE_NOMAD` and five `PMM_NOMAD_GC_*`.
- The `/nomad/` endpoint, for admins, and RPC port 4647, which operators publish themselves.
- The agent type `AGENT_TYPE_NOMAD_AGENT`, the message `NomadAgent`, and their fields in the inventory API's list, get and change calls.
- A page of the documentation, which says that "Nomad will remain within PMM to provide infrastructure for upcoming enhancements" (`documentation/docs/reference/nomad.md:121`).

How PMM has retired things before [V]:
- Two features were removed with two minor releases of notice: VMware deployments, announced in 3.4.0 for 3.6.0, and upgrades from the UI, announced in 3.7.0 for 3.9.0.
- API fields are marked deprecated, or removed and their numbers reserved. No agent type has been retired in this repository's history, and `v1` packages take additions only.
- No general deprecation policy is written down.

What the code does at the edges [V]:
- PMM creates a `nomad-agent` row for every pmm-agent from 3.2.0 on, with no upper version.
- A server that stops sending the Nomad client's config makes an old pmm-agent stop its Nomad client. This is the path taken today when Nomad is disabled.
- An agent row of an unknown type makes the conversion to the API panic (`managed/services/converters.go:628-629`).
- The server's own pmm-agent is started with `--paths-nomad-data-dir`.
- Nothing deletes `/srv/nomad`, which holds Nomad's state and certificate material, or the data directory on each host.

Clients older than the release that ships the `run_script` job can run tasks only through Nomad.

## Options

1. **Remove Nomad in the release that ships script runs.** Rejected: no fallback for the first release of a new executor; no notice for the people the documentation told that Nomad stays; and every client would have to be upgraded at once.
2. **Keep both for good**, and let each install choose. Rejected: the license stays, and so does every cost of Nomad.
3. **Per host: Nomad for old clients, pmm-agent for new ones, in one install.** Rejected: two executors live at once in PMM Extensions, with two host lists to merge, for a state that lasts one release.
4. **Two releases: deprecate with a fallback for the whole install, then remove.**

Also looked at, for PMM Extensions alone: **keeping the Nomad executor as an optional add-on** that is not installed by default. Not taken in this epic. From the removal on PMM ships no Nomad, and PMM Extensions is supported only as part of PMM, so no supported install could run the add-on and no test set-up would cover it. The license is not the reason: the executor is PMM Extensions' own code, and its client library is MIT.

## Decision

Option 4.

**The release that ships script runs (3.12.0):**
- The PMM bundle makes the pmm-agent executor PMM Extensions' default.
- Nomad still ships, and still starts where `PMM_ENABLE_NOMAD` is set. Falling back takes two settings: PMM Extensions' default backend, and Nomad enabled on PMM Server.
- A run is followed to its end by the executor that started it, so a task that was running under Nomad at the upgrade finishes there.
- pmm-managed logs at start-up that Nomad is deprecated, where `PMM_ENABLE_NOMAD` is set.
- The release notes announce that Nomad is deprecated and will be removed in the next release. The reference page is rewritten.
- A host whose client is below the version gate cannot run tasks through pmm-agent, and the host list says why.

**The next release:**
- Nomad is removed from PMM Server, from PMM Client and from PMM Extensions, with the fallback setting.
- pmm-managed deletes the `nomad-agent` rows at every start, and the conversion to the API skips the type instead of panicking. One migration is not enough: in a rolling HA upgrade a replica still on the old version creates the rows again.
- In PMM Extensions `nomad` stays as a retired backend value: stored tasks that name it still load, list and delete, and running one is refused with a message. No row is rewritten.
- `AGENT_TYPE_NOMAD_AGENT`, `NomadAgent` and their fields stay in the API, marked deprecated, and are never returned.
- `PMM_ENABLE_NOMAD` and `PMM_NOMAD_GC_*` are read and ignored, with a warning at start-up.
- pmm-agent keeps a stub for the Nomad agent type: asked to start one, it reports it as done and logs why, so that a server older than the client does not make it retry.
- `/srv/nomad` is deleted by pmm-managed at start-up, and each host's Nomad data directory by the package scripts and the tarball installer.
- pmm-agent's two Nomad flags stay accepted, hidden and ignored, and are deleted one release later. So the two places that pass them need not change in the same step.

## Consequences

- One release of notice, where PMM's two precedents gave two. The reasons: Nomad is off by default, the people affected get the replacement in the same release as the notice, and the license is the reason to move. Open question [O4](../spec.md#13-risks-and-open-questions) of the spec.
- One release in which a problem with the new executor can be answered by a setting.
- For that release PMM ships both, and both have to be tested.
- After the removal, a task needs a client at or above the gate. An install that upgraded its server and not its clients loses tasks on those hosts, and sees the reason.
- People who script against `/nomad/` lose it, with one release of notice.
- The inventory API keeps an agent type that no longer exists. That is the price of an API that only takes additions.
- If the first release shows that one release of overlap is not enough, the removal moves, and this record is superseded. Open question [O4](../spec.md#13-risks-and-open-questions) of the spec.
