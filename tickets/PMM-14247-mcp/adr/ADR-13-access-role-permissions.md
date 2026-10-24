# ADR-13: Access-Role permissions

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15531
- Implemented: not yet (phase 4)
- Replaces: `dev/docs/managed/mcp-access-roles-proposal.md` on `PMM-MCP-GA`

## Context

Grafana OSS has three organization roles and PMM doesn't fork that part, so there is no fourth Grafana role to give. PMM Access Roles carry only a label filter, so they can't say "may use `/mcp`" or "may read the inventory". An admin who uses Access Control to separate teams has no way to decide who may point an AI client at PMM.

The proposal on `PMM-MCP-GA` suggested `permissions` on Access Roles that **grant** access when the Grafana-role check fails. With ADR-08 in place, `/mcp` and the inventory reads already pass for every Viewer, so a grant would change nothing for anyone at Viewer or above.

## Options

1. Defer permissions.
2. Permissions as grants, keeping ADR-08 (the proposal as written). They would only affect principals with Grafana's "No basic role".
3. Permissions as grants, replacing ADR-08 with Admin-only inventory reads. MCP would then need Access Control for any non-admin to use `pmm_inventory`.
4. Permissions as requirements while Access Control is on.

## Decision

Option 4.
- **Vocabulary:** `mcp:use`, `inventory:read`.
- **Model:** `permissions text[]` on `roles` (forward-only migration); additive `repeated string permissions` on the role messages in `api/accesscontrol/v1beta1`.
- **Rule:** with Access Control on, a caller who is not Admin needs `mcp:use` for `/mcp`, and `inventory:read` for `GET /v1/inventory/services` and `GET /v1/inventory/nodes`. A user's permissions are the union over their roles. Missing permission: 403.
- **Access Control off:** no effect; ADR-08 applies.
- **No built-in role.** A role with an empty filter gives full visibility whatever the user's other roles say, so a built-in "MCP User" role without a filter would widen a restricted user's access. Admins add the permissions to roles users already hold, or to the default role for everyone. Permissions never change what a user can see.
- **UI:** a Permissions checkbox group in the Access Roles editor, in the Grafana fork.

## Consequences

- Admins using Access Control decide who may use MCP; for them MCP is closed until they grant it.
- Servers without Access Control behave as before.
- Nothing in the MCP code changes: `auth_request` re-authorizes every backing call, so a missing permission surfaces as `unauthorized` on the tool that needs it.
- Phase 4 grows: a migration, proto and generated code, the auth path, the Grafana fork's editor, docs. The fork needs a matching release.
- Service-account tokens need ADR-12 for their permissions to be evaluated.
