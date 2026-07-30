"use client";

import { useMemo, useState } from "react";
import { Check, Copy, KeyRound, Loader2 } from "lucide-react";

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
import { createAccessKey } from "@/lib/api";
import {
	serializeWorkspacePermissions,
	type WorkspacePermission,
} from "@/lib/workspace-permissions";

interface CreateAccessKeyDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onCreated: () => void;
}

function minimumExpiration(): string {
	const minimum = new Date(Date.now() + 60_000);
	const local = new Date(
		minimum.getTime() - minimum.getTimezoneOffset() * 60_000,
	);
	return local.toISOString().slice(0, 16);
}

export function CreateAccessKeyDialog({
	open,
	onOpenChange,
	onCreated,
}: CreateAccessKeyDialogProps) {
	const [name, setName] = useState("");
	const [expiration, setExpiration] = useState("");
	const [permissions, setPermissions] = useState<WorkspacePermission[]>(["read"]);
	const [secret, setSecret] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [isCopied, setIsCopied] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const minExpiration = useMemo(() => minimumExpiration(), [open]);

	const reset = () => {
		setName("");
		setExpiration("");
		setPermissions(["read"]);
		setSecret(null);
		setIsCopied(false);
		setError(null);
	};

	const handleOpenChange = (nextOpen: boolean) => {
		if (!nextOpen && isSubmitting) {
			return;
		}
		if (!nextOpen) {
			reset();
		}
		onOpenChange(nextOpen);
	};

	const handleSubmit = async (event: React.FormEvent) => {
		event.preventDefault();
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

		let expiresAt: string | undefined;
		if (expiration) {
			const expirationDate = new Date(expiration);
			if (
				Number.isNaN(expirationDate.getTime()) ||
				expirationDate.getTime() <= Date.now()
			) {
				setError("Choose an expiration time in the future.");
				return;
			}
			expiresAt = expirationDate.toISOString();
		}

		setIsSubmitting(true);
		setError(null);
		try {
			const response = await createAccessKey({
				name: trimmedName,
				permissions: normalizedPermissions,
				...(expiresAt ? { expires_at: expiresAt } : {}),
			});
			setSecret(response.secret);
			onCreated();
		} catch (submitError) {
			setError(
				submitError instanceof Error
					? submitError.message
					: "Could not create this access key.",
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	const handleCopy = async () => {
		if (!secret) {
			return;
		}
		try {
			await navigator.clipboard.writeText(secret);
			setIsCopied(true);
			setError(null);
		} catch {
			setIsCopied(false);
			setError("Could not copy the access key. Select and copy it manually.");
		}
	};

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogContent
				hideCloseButton={isSubmitting || secret !== null}
				onInteractOutside={(event) => {
					if (isSubmitting || secret !== null) {
						event.preventDefault();
					}
				}}
				onEscapeKeyDown={(event) => {
					if (isSubmitting || secret !== null) {
						event.preventDefault();
					}
				}}
			>
				{secret ? (
					<div className="space-y-5" data-ph-no-capture>
						<DialogHeader>
							<div className="flex size-10 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
								<KeyRound className="size-5" />
							</div>
							<DialogTitle>Access key created</DialogTitle>
							<DialogDescription>
								Copy this key now. For your security, Scholens will not show it
								again.
							</DialogDescription>
						</DialogHeader>

						<div className="ph-no-capture flex items-center gap-2" data-ph-no-capture>
							<Input
								readOnly
								value={secret}
								autoComplete="off"
								spellCheck={false}
								aria-label="New access key"
								className="ph-no-capture font-mono text-xs"
								data-ph-no-capture
							/>
							<Button type="button" variant="outline" onClick={() => void handleCopy()}>
								{isCopied ? <Check /> : <Copy />}
								{isCopied ? "Copied" : "Copy"}
							</Button>
						</div>

						{error ? (
							<p role="alert" className="text-sm text-destructive">
								{error}
							</p>
						) : null}

						<DialogFooter>
							<Button type="button" onClick={() => handleOpenChange(false)}>
								Done, I saved it
							</Button>
						</DialogFooter>
					</div>
				) : (
					<form onSubmit={handleSubmit} className="space-y-5">
						<DialogHeader>
							<DialogTitle>Create access key</DialogTitle>
							<DialogDescription>
								Create a Scholens key for an external MCP client. You can revoke
								it at any time.
							</DialogDescription>
						</DialogHeader>

						<div className="space-y-2">
							<Label htmlFor="access-key-name">Name</Label>
							<Input
								id="access-key-name"
								value={name}
								maxLength={80}
								placeholder="Claude Desktop"
								autoComplete="off"
								disabled={isSubmitting}
								onChange={(event) => setName(event.target.value)}
							/>
							<p className="text-xs text-muted-foreground">
								Use a name that identifies the app or device.
							</p>
						</div>

						<div className="space-y-2">
							<Label htmlFor="access-key-expiration">Expiration</Label>
							<Input
								id="access-key-expiration"
								type="datetime-local"
								value={expiration}
								min={minExpiration}
								disabled={isSubmitting}
								onChange={(event) => setExpiration(event.target.value)}
							/>
							<p className="text-xs text-muted-foreground">
								Leave empty for a key that does not expire.
							</p>
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
								<AlertTitle>Access key not created</AlertTitle>
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
									!name.trim() ||
									permissions.length === 0
								}
							>
								{isSubmitting ? <Loader2 className="animate-spin" /> : null}
								Create access key
							</Button>
						</DialogFooter>
					</form>
				)}
			</DialogContent>
		</Dialog>
	);
}
