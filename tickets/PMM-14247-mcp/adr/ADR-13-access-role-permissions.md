# ADR-13: Access-Role permissions

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15531, PMM-15744, PMM-15791
- Implemented: not yet; PMM-15791, after the MCP release
- Replaces: `dev/docs/managed/mcp-access-roles-proposal.md` on `PMM-MCP-GA`

## Context

Grafana OSS has three organization roles and PMM doesn't fork that part, so there is no fourth Grafana role to give. PMM Access Roles carry only a label filter, so they can't say "may use `/mcp`". An admin who uses Access Control to separate teams has no way to decide who may point an AI client at PMM.

This is governance, not data scoping. MCP can't return more than the caller's own API access (ADR-03); ADR-12 and ADR-16 make Access Roles scope what MCP returns. A permission decides whether a caller may use MCP at all.

The proposal on `PMM-MCP-GA` suggested `permissions` on Access Roles that **grant** access when the Grafana-role check fails. `/mcp` already passes for every Viewer, so a grant would change nothing for anyone at Viewer or above.

## Options

1. Defer permissions.
2. Permissions as grants (the proposal as written). They would only affect principals with Grafana's "No basic role".
3. Permissions as requirements while Access Control is on.

## Decision

Option 3, delivered on PMM-15791 after the MCP release. It touches a migration, the proto, the auth path and the role editor, which is PMM-wide work the MCP release doesn't need.
- **Vocabulary:** `mcp:use`. Reads such as the inventory, alerts and Advisor results need no permission of their own: Access Roles already scope them (ADR-16).
- **Model:** `permissions text[]` on `roles` (forward-only migration); additive `repeated string permissions` on the role messages in `api/accesscontrol/v1beta1`.
- **Rule:** with Access Control on, a caller who is not Admin needs `mcp:use` for `/mcp`; without it, 403. Admins always pass.
- **Union, not per role:** a user's permissions are the union over their roles, independent of the roles' filters. A user with role A (`mcp:use`, filter `environment="prod"`) and role B (no permission, filter `environment="staging"`) can use MCP, and MCP returns prod and staging data, the same as their dashboards show. Permissions decide whether, never what.
- **After the migration** no role carries `mcp:use`, so with Access Control on, MCP is closed to non-admins until an admin grants it. The release notes say so.
- **Access Control off:** no effect; the Grafana role and `PMM_ENABLE_MCP` decide.
- **No built-in role.** A role with an empty filter gives full visibility whatever the user's other roles say, so a built-in "MCP User" role without a filter would widen a restricted user's access. Admins add the permission to roles users already hold, or to the default role for everyone.
- **UI:** a Permissions checkbox group in the Access Roles editor. The editor is in the Grafana fork today; PMM-15744 moves role management to the PMM UI, and the checkbox goes wherever the editor is when this ships.

## Consequences

- The MCP release doesn't wait for a migration, proto, auth and role-editor change.
- Until this ships, with Access Control on, every Viewer and above can use MCP once an admin enables it; what each gets is scoped by their Access Roles.
- Nothing in the MCP code changes when it ships.
- When it ships: a migration, proto and generated code, the auth path, the role editor, docs. An editor still in the Grafana fork needs a matching fork release.
- Service-account tokens need ADR-12 for their permissions to be evaluated.
