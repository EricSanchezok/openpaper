"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { KeyRound, Loader2, Plus, RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { listAccessKeys, revokeAccessKey } from "@/lib/api";
import type { AccessKeyResponse } from "@/lib/schema";

import { AccessKeyRow } from "./AccessKeyRow";
import { CreateAccessKeyDialog } from "./CreateAccessKeyDialog";
import { EditAccessKeyDialog } from "./EditAccessKeyDialog";

const PAGE_SIZE = 20;

export function AccessKeySettingsSection() {
	const [accessKeys, setAccessKeys] = useState<AccessKeyResponse[]>([]);
	const [nextCursor, setNextCursor] = useState<string | null>(null);
	const [isInitialLoading, setIsInitialLoading] = useState(true);
	const [isRefreshing, setIsRefreshing] = useState(false);
	const [isLoadingMore, setIsLoadingMore] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [createOpen, setCreateOpen] = useState(false);
	const [editingAccessKey, setEditingAccessKey] =
		useState<AccessKeyResponse | null>(null);
	const requestSequence = useRef(0);

	const refresh = useCallback(async () => {
		const sequence = ++requestSequence.current;
		setIsRefreshing(true);
		setIsLoadingMore(false);
		setError(null);
		try {
			const response = await listAccessKeys({ limit: PAGE_SIZE });
			if (sequence !== requestSequence.current) {
				return;
			}
			setAccessKeys(response.items);
			setNextCursor(response.next_cursor);
		} catch (loadError) {
			if (sequence !== requestSequence.current) {
				return;
			}
			setError(
				loadError instanceof Error
					? loadError.message
					: "Could not load access keys.",
			);
		} finally {
			if (sequence === requestSequence.current) {
				setIsRefreshing(false);
				setIsInitialLoading(false);
			}
		}
	}, []);

	useEffect(() => {
		void refresh();
		return () => {
			requestSequence.current += 1;
		};
	}, [refresh]);

	const loadMore = async () => {
		if (!nextCursor || isLoadingMore) {
			return;
		}
		const sequence = ++requestSequence.current;
		setIsLoadingMore(true);
		setError(null);
		try {
			const response = await listAccessKeys({
				limit: PAGE_SIZE,
				cursor: nextCursor,
			});
			if (sequence !== requestSequence.current) {
				return;
			}
			setAccessKeys((current) => {
				const byId = new Map(current.map((accessKey) => [accessKey.id, accessKey]));
				for (const accessKey of response.items) {
					byId.set(accessKey.id, accessKey);
				}
				return Array.from(byId.values());
			});
			setNextCursor(response.next_cursor);
		} catch (loadError) {
			if (sequence !== requestSequence.current) {
				return;
			}
			setError(
				loadError instanceof Error
					? loadError.message
					: "Could not load more access keys.",
			);
		} finally {
			if (sequence === requestSequence.current) {
				setIsLoadingMore(false);
			}
		}
	};

	const handleRevoke = async (accessKey: AccessKeyResponse) => {
		await revokeAccessKey(accessKey.id);
		setAccessKeys((current) =>
			current.map((candidate) =>
				candidate.id === accessKey.id
					? { ...candidate, status: "revoked" }
					: candidate,
			),
		);
		if (editingAccessKey?.id === accessKey.id) {
			setEditingAccessKey(null);
		}
	};

	return (
		<section aria-labelledby="access-keys-heading" className="space-y-4">
			<div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
				<div className="space-y-1">
					<div className="flex items-center gap-2">
						<KeyRound className="size-4 text-muted-foreground" />
						<h2 id="access-keys-heading" className="text-lg font-medium">
							Access keys
						</h2>
					</div>
					<p className="text-sm text-muted-foreground">
						Connect external agents to Scholens through MCP.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Button
						type="button"
						variant="ghost"
						size="icon"
						aria-label="Refresh access keys"
						title="Refresh access keys"
						disabled={isRefreshing}
						onClick={() => void refresh()}
					>
						<RefreshCw className={isRefreshing ? "animate-spin" : undefined} />
					</Button>
					<Button type="button" onClick={() => setCreateOpen(true)}>
						<Plus />
						Create access key
					</Button>
				</div>
			</div>

			{error ? (
				<Alert variant="destructive">
					<AlertTitle>Access keys unavailable</AlertTitle>
					<AlertDescription className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
						<span>{error}</span>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => void refresh()}
						>
							Try again
						</Button>
					</AlertDescription>
				</Alert>
			) : null}

			{isInitialLoading ? (
				<div className="flex min-h-28 items-center justify-center rounded-lg border">
					<Loader2 className="size-5 animate-spin text-muted-foreground" />
					<span className="sr-only">Loading access keys</span>
				</div>
			) : accessKeys.length === 0 ? (
				<div className="rounded-lg border border-dashed px-6 py-8 text-center">
					<p className="text-sm font-medium">No access keys yet</p>
					<p className="mt-1 text-sm text-muted-foreground">
						Create a key when you are ready to connect an MCP client.
					</p>
				</div>
			) : (
				<div className="space-y-3">
					{accessKeys.map((accessKey) => (
						<AccessKeyRow
							key={accessKey.id}
							accessKey={accessKey}
							onEdit={setEditingAccessKey}
							onRevoke={handleRevoke}
						/>
					))}
				</div>
			)}

			{nextCursor ? (
				<div className="flex justify-center">
					<Button
						type="button"
						variant="outline"
						disabled={isLoadingMore}
						onClick={() => void loadMore()}
					>
						{isLoadingMore ? <Loader2 className="animate-spin" /> : null}
						Load more
					</Button>
				</div>
			) : null}

			<CreateAccessKeyDialog
				open={createOpen}
				onOpenChange={setCreateOpen}
				onCreated={() => void refresh()}
			/>
			<EditAccessKeyDialog
				accessKey={editingAccessKey}
				open={editingAccessKey !== null}
				onOpenChange={(open) => {
					if (!open) {
						setEditingAccessKey(null);
					}
				}}
				onUpdated={(updated) => {
					setAccessKeys((current) =>
						current.map((accessKey) =>
							accessKey.id === updated.id ? updated : accessKey,
						),
					);
					setEditingAccessKey(null);
				}}
			/>
		</section>
	);
}
