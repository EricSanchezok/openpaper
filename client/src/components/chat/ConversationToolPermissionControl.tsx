"use client";

import {
	type Dispatch,
	type SetStateAction,
	useEffect,
	useMemo,
	useState,
} from "react";
import { Loader2 } from "lucide-react";

import { WorkspacePermissionPicker } from "@/components/permissions/WorkspacePermissionPicker";
import { Button } from "@/components/ui/button";
import { fetchFromApi } from "@/lib/api";
import type { ConversationDetail } from "@/lib/schema";
import {
	serializeWorkspacePermissions,
	type WorkspacePermission,
} from "@/lib/workspace-permissions";

interface ConversationToolPermissionsResponse {
	permissions: WorkspacePermission[];
}

interface ConversationToolPermissionControlProps {
	conversation: ConversationDetail;
	onConversationChange: Dispatch<SetStateAction<ConversationDetail | null>>;
	disabled?: boolean;
}

export function ConversationToolPermissionControl({
	conversation,
	onConversationChange,
	disabled = false,
}: ConversationToolPermissionControlProps) {
	const serverPermissions = useMemo(
		() => serializeWorkspacePermissions(conversation.tool_permissions),
		[conversation.tool_permissions],
	);
	const serverValueKey = serverPermissions.join(",");
	const [draft, setDraft] = useState<WorkspacePermission[]>(serverPermissions);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		setDraft(serverPermissions);
		setError(null);
	}, [conversation.id, serverPermissions, serverValueKey]);

	const isDirty = draft.join(",") !== serverValueKey;
	const isDisabled = disabled || isSaving;

	const apply = async () => {
		if (!isDirty || isDisabled) return;

		setIsSaving(true);
		setError(null);
		try {
			const response = await fetchFromApi<ConversationToolPermissionsResponse>(
				`/conversations/${encodeURIComponent(conversation.id)}/tool-permissions`,
				{
					method: "PUT",
					body: JSON.stringify({ permissions: draft }),
				},
			);
			const permissions = serializeWorkspacePermissions(response.permissions);
			setDraft(permissions);
			onConversationChange((current) =>
				current?.id === conversation.id
					? { ...current, tool_permissions: permissions }
					: current,
			);
		} catch (cause) {
			setDraft(serverPermissions);
			setError(
				cause instanceof Error
					? cause.message
					: "Failed to update agent tool permissions.",
			);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<div className="flex min-w-0 flex-col gap-1.5">
			<div className="flex flex-wrap items-center gap-x-3 gap-y-2">
				<span className="text-xs font-medium text-foreground">Agent tools</span>
				<WorkspacePermissionPicker
					value={draft}
					onChange={(next) => {
						setDraft(next);
						setError(null);
					}}
					disabled={isDisabled}
				/>
				{isDirty && (
					<Button
						type="button"
						variant="outline"
						size="sm"
						className="h-7 px-2 text-xs"
						disabled={isDisabled}
						onClick={() => void apply()}
					>
						{isSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
						Apply
					</Button>
				)}
			</div>
			{error && (
				<p className="text-xs text-destructive" role="alert">
					{error}
				</p>
			)}
		</div>
	);
}
