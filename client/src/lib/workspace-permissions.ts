export const WORKSPACE_PERMISSION_OPTIONS = [
	{
		value: "read",
		label: "Read",
		description: "Search and inspect papers, projects, highlights, and jobs.",
	},
	{
		value: "write",
		label: "Write",
		description: "Create and update workspace content.",
	},
	{
		value: "delete",
		label: "Delete",
		description: "Remove workspace content and associations.",
	},
] as const;

export type WorkspacePermission =
	(typeof WORKSPACE_PERMISSION_OPTIONS)[number]["value"];

export function serializeWorkspacePermissions(
	values: Iterable<WorkspacePermission>,
): WorkspacePermission[] {
	const selected = new Set(values);
	return WORKSPACE_PERMISSION_OPTIONS
		.map(({ value }) => value)
		.filter((permission) => selected.has(permission));
}

export const DEFAULT_CONVERSATION_TOOL_PERMISSIONS: readonly WorkspacePermission[] =
	Object.freeze(serializeWorkspacePermissions(["read", "write"]));
