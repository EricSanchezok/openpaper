"use client";

import { useState } from "react";
import { KeyRound, Loader2, Pencil, Trash2 } from "lucide-react";

import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AccessKeyResponse, AccessKeyStatus } from "@/lib/schema";
import { WORKSPACE_PERMISSION_OPTIONS } from "@/lib/workspace-permissions";

interface AccessKeyRowProps {
	accessKey: AccessKeyResponse;
	onEdit: (accessKey: AccessKeyResponse) => void;
	onRevoke: (accessKey: AccessKeyResponse) => Promise<void>;
}

const STATUS_LABELS: Record<AccessKeyStatus, string> = {
	active: "Active",
	expired: "Expired",
	revoked: "Revoked",
};

function formatTimestamp(value: string | null): string {
	if (!value) {
		return "Never";
	}
	return new Intl.DateTimeFormat(undefined, {
		year: "numeric",
		month: "short",
		day: "numeric",
		hour: "numeric",
		minute: "2-digit",
	}).format(new Date(value));
}

export function AccessKeyRow({
	accessKey,
	onEdit,
	onRevoke,
}: AccessKeyRowProps) {
	const [confirmOpen, setConfirmOpen] = useState(false);
	const [isRevoking, setIsRevoking] = useState(false);
	const [revokeError, setRevokeError] = useState<string | null>(null);
	const isActive = accessKey.status === "active";

	const handleRevoke = async () => {
		setIsRevoking(true);
		setRevokeError(null);
		try {
			await onRevoke(accessKey);
			setConfirmOpen(false);
		} catch (error) {
			setRevokeError(
				error instanceof Error ? error.message : "Could not revoke this access key.",
			);
		} finally {
			setIsRevoking(false);
		}
	};

	return (
		<div className="rounded-lg border bg-card px-4 py-4">
			<div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
				<div className="min-w-0 space-y-3">
					<div className="flex min-w-0 items-center gap-2">
						<div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
							<KeyRound className="size-4" />
						</div>
						<div className="min-w-0">
							<div className="flex flex-wrap items-center gap-2">
								<p className="truncate text-sm font-medium">{accessKey.name}</p>
								<Badge
									variant={
										accessKey.status === "revoked"
											? "destructive"
											: accessKey.status === "active"
												? "secondary"
												: "outline"
									}
								>
									{STATUS_LABELS[accessKey.status]}
								</Badge>
							</div>
							<code className="text-xs text-muted-foreground">
								{accessKey.key_prefix}…
							</code>
						</div>
					</div>

					<div className="flex flex-wrap gap-1.5">
						{accessKey.permissions.map((permission) => {
							const option = WORKSPACE_PERMISSION_OPTIONS.find(
								(candidate) => candidate.value === permission,
							);
							return (
								<Badge key={permission} variant="outline" className="font-normal">
									{option?.label ?? permission}
								</Badge>
							);
						})}
					</div>

					<dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
						<div>
							<dt className="text-muted-foreground">Created</dt>
							<dd>
								<time dateTime={accessKey.created_at}>
									{formatTimestamp(accessKey.created_at)}
								</time>
							</dd>
						</div>
						<div>
							<dt className="text-muted-foreground">Expires</dt>
							<dd>
								{accessKey.expires_at ? (
									<time dateTime={accessKey.expires_at}>
										{formatTimestamp(accessKey.expires_at)}
									</time>
								) : (
									"Never"
								)}
							</dd>
						</div>
						<div>
							<dt className="text-muted-foreground">Last used</dt>
							<dd>
								{accessKey.last_used_at ? (
									<time dateTime={accessKey.last_used_at}>
										{formatTimestamp(accessKey.last_used_at)}
									</time>
								) : (
									"Never"
								)}
							</dd>
						</div>
					</dl>
				</div>

				{isActive ? (
					<div className="flex shrink-0 items-center gap-2">
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => onEdit(accessKey)}
						>
							<Pencil />
							Edit
						</Button>
						<Button
							type="button"
							variant="ghost"
							size="sm"
							className="text-destructive hover:bg-destructive/10 hover:text-destructive"
							onClick={() => {
								setRevokeError(null);
								setConfirmOpen(true);
							}}
						>
							<Trash2 />
							Revoke
						</Button>
					</div>
				) : (
					<p className="shrink-0 text-xs text-muted-foreground">Read only</p>
				)}
			</div>

			<AlertDialog
				open={confirmOpen}
				onOpenChange={(open) => {
					if (!isRevoking) {
						setConfirmOpen(open);
						if (!open) {
							setRevokeError(null);
						}
					}
				}}
			>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>Revoke “{accessKey.name}”?</AlertDialogTitle>
						<AlertDialogDescription>
							Any MCP client using this key will lose access immediately. Revoked
							keys cannot be restored.
						</AlertDialogDescription>
					</AlertDialogHeader>
					{revokeError ? (
						<p role="alert" className="text-sm text-destructive">
							{revokeError}
						</p>
					) : null}
					<AlertDialogFooter>
						<AlertDialogCancel disabled={isRevoking}>Cancel</AlertDialogCancel>
						<AlertDialogAction
							disabled={isRevoking}
							className="bg-destructive text-white hover:bg-destructive/90"
							onClick={(event) => {
								event.preventDefault();
								void handleRevoke();
							}}
						>
							{isRevoking ? <Loader2 className="animate-spin" /> : null}
							Revoke access key
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</div>
	);
}
