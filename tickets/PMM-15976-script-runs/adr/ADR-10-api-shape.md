# ADR-10: A beta gRPC service behind grpc-gateway

- Status: Proposed
- Date: 2026-11-18
- Tickets: [PMM-15976](https://perconadev.atlassian.net/browse/PMM-15976)
- Planned in: [plan 02](../plans/02-managed-runs-api.md)

## Context

PMM's API is defined in `.proto` files, served by pmm-managed over gRPC, and offered as REST through grpc-gateway. Validation, the OpenAPI document, the generated clients and the API tests all come from the definition. `v1` packages take additions only; `v1beta1` packages may change (`api/AGENTS.md`) [V]. Access control is in `v1beta1` today and is served under `/v1/accesscontrol`.

The prototype's API is a tree of plain HTTP handlers on pmm-managed's second port, with JSON written by hand, no validation and no definition [V].

No public RPC streams from the server. Logs of backups are read by offset: `GET /v1/backups/{artifact_id}/logs` with `offset` and `limit`, returning chunks and an `end` flag (`api/backup/v1/backup.proto:156-165`) [V].

The API has one caller, PMM Extensions ([ADR-09](ADR-09-who-may-start-a-run.md)), and it will change as that caller's needs become clear.

## Options

1. **Plain HTTP handlers** (the prototype). Rejected: nothing of PMM's API tooling applies, and a raw download and hand-written errors are two more things to maintain.
2. **A `v1` gRPC service.** Rejected for now: `v1` cannot change, and this API has not met its first real caller.
3. **A `v1beta1` gRPC service behind grpc-gateway.**
4. **Server-streaming RPCs for logs and files.** Rejected: nothing in PMM's public API streams, the gateway's support for it is limited, and reads by offset already serve the live log view of backups.

## Decision

Option 3: package `scripts.v1beta1`, service `ScriptsService`, REST under `/v1/scripts`.

| RPC | REST |
|---|---|
| `StartRun` | `POST /v1/scripts/runs` |
| `GetRun` | `GET /v1/scripts/runs/{run_id}` |
| `ListRuns` | `GET /v1/scripts/runs` |
| `GetRunLogs` | `GET /v1/scripts/runs/{run_id}/logs` |
| `StopRun` | `POST /v1/scripts/runs/{run_id}:stop` |
| `ListRunFiles` | `GET /v1/scripts/runs/{run_id}/files` |
| `ReadRunFile` | `GET /v1/scripts/runs/{run_id}/files/{name}` |
| `ListHosts` | `GET /v1/scripts/hosts` |

- `StartRun` names the host by its pmm-agent id, takes the run's id from the caller, and returns the record. A second call with the same id returns the first's record and starts nothing. A run that cannot start is a record in `not_started` with its reason, not an error; only an unknown pmm-agent is an error, because a record needs a host.
- `GetRun` takes an optional `wait` of at most 30 s. The call returns when the run reaches a final state or the wait ends.
- `ListRuns` takes `final_after` and `wait`. It returns the runs that reached a final state after that point: at once if there are any, otherwise when one does or the wait ends. One open call tells a caller of every run's end. Every answer carries a cursor, and a caller can ask for the current cursor alone. A cursor can miss a run whose record is written late; the caller's own periodic check of its open runs covers that.
- `GetRunLogs` reads by chunk offset, in the shape of the backup logs.
- `ReadRunFile` reads by offset and length, at most 2 MiB a call. The bytes are relayed from the host and never stored.
- `StopRun` returns at once and says whether the stop was sent or is held. On a run that is already final it returns the record unchanged.
- Requests are validated: in the definition where its rules can express a limit, and in code for the rest.

## Consequences

- The API gets validation, an OpenAPI document, a generated client and API tests for the cost of a definition.
- It can change until it moves to `v1`. PMM Extensions ships in the same release as PMM Server, so the two change together.
- A caller polls for logs. With the two calls that wait, it does not poll for results. The spike measured 1.0 s for a call through PMM Extensions, and 0.3 s with a check on each run, which is another mechanism than this one [V].
- A file is read in pieces by the caller. A task that produces a directory packs it itself.
- No public API reference is published for it: a beta package is generated into the development OpenAPI document only. That fits an API with one internal caller.
