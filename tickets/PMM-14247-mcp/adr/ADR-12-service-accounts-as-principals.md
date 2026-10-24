# ADR-12: Service-account tokens are principals

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15531, PMM-15534
- Implemented: not yet (phase 4)

## Context

The MCP documentation tells users to connect with a service-account token. PMM Access Roles, which carry LBAC filters, are assigned to user IDs. Today a service token resolves to user ID 0 (`getAuthUser` in `managed/services/grafana/client.go`), so no Access Role applies to it and its data is unfiltered (PMM-15534). For a token to be governed by Access Roles, the auth path has to know which account it belongs to.

## Options

1. Resolve the account ID from the response pmm-managed already fetches when it authenticates a token.
2. Look the account up by name with `GET /api/serviceaccounts/search`.
3. Introduce a separate machine principal for MCP.

## Decision

Option 1. pmm-managed already calls `GET /api/auth/serviceaccount` for every service token. Percona's Grafana fork answers with `ServiceAccountProfileDTO`, whose `id` is the account's user ID. The auth path uses that ID for Access Roles exactly as it uses an interactive user's ID. A principal seen for the first time gets the default role, as interactive users do. Roles are assigned to an account with the existing `POST /v1/accesscontrol/roles:assign`.

Out of scope: a role picker on Grafana's service-account page; a machine principal for unattended runs; propagating caller identity to upstreams with a header (MCP authorizes nothing itself, ADR-03).

## Consequences

- Access Roles govern every token-based integration, not only MCP.
- No Grafana fork change and no extra call per request.
- A token is governed by the default role from its first request. Since tokens get no filter today, this can only narrow what a token sees. Admins who restricted the default role should check their tokens before upgrading; the release notes say so.
- This is a release prerequisite: without it, a token's MCP results are not scoped by Access Roles.
- `mcp.md` and the access-control docs describe role assignment for service accounts, in the same change.
