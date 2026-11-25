# ADR-09: Who may start a run, and the default state

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 02](../plans/02-managed-runs-api.md); [plan 03](../plans/03-containment.md) for the host switch; [plan 04](../plans/04-extensions-executor.md) for PMM Extensions

## Context

Starting a run executes a program on a database host, as root where pmm-agent is root ([ADR-07](ADR-07-run-as-user.md)). Who may do that is the most sensitive decision in this epic.

What PMM offers [V]:
- Authorization is by Grafana role, by URL prefix and for some paths by HTTP method, in two tables (`managed/services/grafana/auth_server.go:54-149`, `:153-177`). A path with no rule needs the Grafana server admin.
- There is no permission for a single feature. Access Roles filter what a user can see by label; they do not grant actions.
- PMM Extensions calls PMM with a service-account token.
- On a single PMM Server with the built-in PostgreSQL, pmm-managed and the PMM Extensions side-car share the side-car's `SECRET_KEY`. pmm-managed derives from it the internal token it presents when it calls PMM Extensions as itself (`managed/services/om/extensions_connection.go:33-81`).
- In PMM HA, and with an external PostgreSQL, that secret is not shared (`build/ansible/roles/extensions/files/extensions-secrets:146-149`). The internal token then comes from `PMM_EXTENSIONS_TOKEN`.
- PMM Extensions is enabled by `PMM_ENABLE_EXTENSIONS`, which is read at start-up and is not a stored setting.
- No feature of pmm-agent can be switched off on the host in a way the server cannot override. The closest precedent is the allow-list of [PMM-15567 ADR-08](../../PMM-15567-otel/adr/ADR-08-file-read-trust.md), which lives in `pmm-agent.yaml`.

PMM Extensions decides which person may run which task, and does so today.

The prototype's rule is `/v1/scripts`: Admin, and nothing else.

## Options

1. **The Admin role alone.** Rejected: a role is not an identity. Running programs on database hosts should need proof of which service is calling, and not only a role.
2. **A new permission in PMM**, such as an Access Role that grants "may run scripts". Rejected for now: PMM has no permission model to add it to. [PMM-15791](https://perconadev.atlassian.net/browse/PMM-15791) plans one for another feature; this decision can move onto it when it exists.
3. **An endpoint that is not reachable from outside PMM Server**: its own port, outside nginx. Rejected: PMM Extensions runs in its own container and may run on another host, so the port would have to be reachable anyway, with its own TLS and its own credential.
4. **The Admin role, and proof that the caller is PMM Extensions.**

## Decision

Option 4.

**On the server:**
- `/v1/scripts` needs the Admin role at nginx's `auth_request`. The service's gRPC name is not reachable through nginx; it gets the same rule as a safeguard.
- Every call must also carry a second token in a header. It is derived under a label of its own from the internal token the two already share: the one pmm-managed presents when it calls PMM Extensions as itself. pmm-managed gets that token from the side-car's `SECRET_KEY`, or from `PMM_EXTENSIONS_TOKEN` where PMM Extensions runs elsewhere; PMM Extensions knows it as `EXTENSIONS_INTERNAL_TOKEN`. pmm-managed compares the header in constant time and answers 403 without it.
- Where pmm-managed has no internal token (PMM Extensions is not enabled, its secret cannot be read, or its address is configured without a token), the API answers an authenticated caller as an unknown path does. An empty token never becomes a key.
- There is no other switch. Script runs are **off** on an install without PMM Extensions and **on** with it.
- Which person may run which task stays in PMM Extensions.

**On the host:**
- `pmm-agent.yaml` gains `scripts.disabled`, with a flag and an environment variable. When it is set, pmm-agent refuses every run and reports it; the host list shows the reason. The server cannot change it.

**In the protocol:**
- pmm-managed sends a run only to an agent at or above the version gate, and accepts a run's messages only from that agent ([ADR-04](ADR-04-acknowledged-delivery.md)).

## Consequences

- The Admin role alone cannot start a run.
- Whoever holds the internal token can. It travels on every call pmm-managed makes to PMM Extensions, so that connection has to be private or encrypted. The trust is the one PMM Extensions already has: it holds the tasks, their inputs and the credentials they use.
- In PMM HA the same `PMM_EXTENSIONS_TOKEN` has to be set on every replica.
- This decision does not change PMM's agent authentication or PMM Extensions' own access control.
- No public address, extra port or second switch is needed for tasks, which removes one of the costs of Nomad ([spec §3.1](../spec.md#31-nomad-in-pmm-today)).
- An operator who wants script runs off turns PMM Extensions off, or sets `scripts.disabled` on the hosts that must never run one.
- The API is PMM Extensions' only. A person with the Admin role cannot call it with `curl`, by design. A user interface or a public API for running scripts would need its own decision.
- The second token changes when the secret does. Both sides derive it at start-up, so a rotation needs a restart of both.
- The token travels on PMM Extensions' connection to PMM, which can verify PMM Server's certificate through a setting; open question [O5](../spec.md#13-risks-and-open-questions) of the spec.
- This decision waits for the security design review before [plan 02](../plans/02-managed-runs-api.md) builds it ([roadmap](../plans/00-roadmap.md#plans-and-order)).
