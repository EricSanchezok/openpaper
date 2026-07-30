"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { WorkspacePermissionPicker } from "@/components/permissions/WorkspacePermissionPicker";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { updateAccessKey } from "@/lib/api";
import type { AccessKeyResponse } from "@/lib/schema";
import {
	serializeWorkspacePermissions,
	type WorkspacePermission,
} from "@/lib/workspace-permissions";

interface EditAccessKeyDialogProps {
	accessKey: AccessKeyResponse | null;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onUpdated: (accessKey: AccessKeyResponse) => void;
}

export function EditAccessKeyDialog({
	accessKey,
	open,
	onOpenChange,
	onUpdated,
}: EditAccessKeyDialogProps) {
	const [name, setName] = useState("");
	const [permissions, setPermissions] = useState<WorkspacePermission[]>([]);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (open && accessKey) {
			setName(accessKey.name);
			setPermissions(serializeWorkspacePermissions(accessKey.permissions));
			setError(null);
		}
	}, [accessKey, open]);

	const handleOpenChange = (nextOpen: boolean) => {
		if (!nextOpen && isSubmitting) {
			return;
		}
		onOpenChange(nextOpen);
		if (!nextOpen) {
			setError(null);
		}
	};

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
		if (!accessKey || accessKey.status !== "active") {
			setError("Only active access keys can be edited.");
			return;
		}
		const trimmedName = name.trim();
		if (!trimmedName) {
			setError("Enter a name for this access key.");
			return;
		}
		const normalizedPermissions = serializeWorkspacePermissions(permissions);
		if (normalizedPermissions.length === 0) {
			setError("Select at least one permission.");
			return;
		}

		setIsSubmitting(true);
		setError(null);
		try {
			const updated = await updateAccessKey(accessKey.id, {
				name: trimmedName,
				permissions: normalizedPermissions,
			});
			onUpdated(updated);
			setError(null);
			onOpenChange(false);
		} catch (submitError) {
			setError(
				submitError instanceof Error
					? submitError.message
					: "Could not update this access key.",
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	const initialPermissions = accessKey
		? serializeWorkspacePermissions(accessKey.permissions)
		: [];
	const hasChanges =
		accessKey !== null &&
		(name.trim() !== accessKey.name ||
			permissions.join(",") !== initialPermissions.join(","));

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogContent
				hideCloseButton={isSubmitting}
				onInteractOutside={(event) => {
					if (isSubmitting) {
						event.preventDefault();
					}
				}}
				onEscapeKeyDown={(event) => {
					if (isSubmitting) {
						event.preventDefault();
					}
				}}
			>
				<form onSubmit={handleSubmit} className="space-y-5">
					<DialogHeader>
						<DialogTitle>Edit access key</DialogTitle>
						<DialogDescription>
							Permission changes apply to the next MCP request made with this key.
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-2">
						<Label htmlFor="edit-access-key-name">Name</Label>
						<Input
							id="edit-access-key-name"
							value={name}
							maxLength={80}
							autoComplete="off"
							disabled={isSubmitting}
							onChange={(event) => setName(event.target.value)}
						/>
					</div>

					<div className="space-y-2">
						<Label>Permissions</Label>
						<WorkspacePermissionPicker
							value={permissions}
							onChange={setPermissions}
							disabled={isSubmitting}
							className="rounded-md border p-3"
						/>
					</div>

					{error ? (
						<Alert variant="destructive">
							<AlertTitle>Access key not updated</AlertTitle>
							<AlertDescription>{error}</AlertDescription>
						</Alert>
					) : null}

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							disabled={isSubmitting}
							onClick={() => handleOpenChange(false)}
						>
							Cancel
						</Button>
						<Button
							type="submit"
							disabled={
								isSubmitting ||
								!hasChanges ||
								!name.trim() ||
								permissions.length === 0
							}
						>
							{isSubmitting ? <Loader2 className="animate-spin" /> : null}
							Save changes
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
