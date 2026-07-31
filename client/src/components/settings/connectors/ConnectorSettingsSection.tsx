"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
	connectConnector,
	disconnectConnector,
	listConnectors,
	updateConnector,
} from "@/lib/api";
import type { ConnectorProvider, ConnectorResponse } from "@/lib/schema";
import { Loader2, Plug, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

export function ConnectorSettingsSection() {
	const [connectors, setConnectors] = useState<ConnectorResponse[]>([]);
	const [keys, setKeys] = useState<Partial<Record<ConnectorProvider, string>>>({});
	const [busy, setBusy] = useState<ConnectorProvider | null>(null);
	const [loading, setLoading] = useState(true);

	const load = useCallback(async () => {
		setLoading(true);
		try {
			setConnectors((await listConnectors()).items);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to load connectors.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void load();
	}, [load]);

	const replace = (updated: ConnectorResponse) => {
		setConnectors((current) =>
			current.map((item) => item.provider === updated.provider ? updated : item),
		);
	};

	const handleConnect = async (connector: ConnectorResponse) => {
		const apiKey = keys[connector.provider]?.trim();
		if (!apiKey) return;
		setKeys((current) => ({ ...current, [connector.provider]: "" }));
		setBusy(connector.provider);
		try {
			replace(await connectConnector(connector.provider, apiKey));
			toast.success(`${connector.display_name} connected.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Connection failed.");
		} finally {
			setBusy(null);
		}
	};

	const handleToggle = async (connector: ConnectorResponse, enabled: boolean) => {
		setBusy(connector.provider);
		try {
			replace(await updateConnector(connector.provider, enabled));
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to update connector.");
		} finally {
			setBusy(null);
		}
	};

	const handleDisconnect = async (connector: ConnectorResponse) => {
		setBusy(connector.provider);
		try {
			await disconnectConnector(connector.provider);
			await load();
			toast.success(`${connector.display_name} disconnected.`);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to disconnect connector.");
		} finally {
			setBusy(null);
		}
	};

	return (
		<div className="space-y-4">
			<div className="space-y-1">
				<h3 className="font-medium">Research connectors</h3>
				<p className="text-sm text-muted-foreground">
					Give the research agent access to external search and retrieval services.
				</p>
			</div>
			{loading ? (
				<div className="flex items-center gap-2 text-sm text-muted-foreground">
					<Loader2 className="h-4 w-4 animate-spin" /> Loading connectors…
				</div>
			) : (
				<div className="space-y-3">
					{connectors.map((connector) => {
						const isBusy = busy === connector.provider;
						return (
							<div
								key={connector.provider}
								className="rounded-lg border p-4 space-y-3"
							>
								<div className="flex items-center justify-between gap-4">
									<div className="flex items-center gap-3">
										<Plug className="h-4 w-4 text-muted-foreground" />
										<div>
											<div className="flex items-center gap-2">
												<span className="font-medium">{connector.display_name}</span>
												{connector.built_in ? <Badge variant="secondary">Built-in</Badge> : null}
												{connector.connected ? <Badge variant="outline">Connected</Badge> : null}
											</div>
											<p className="text-xs text-muted-foreground">
												{connector.built_in
													? "Automatically authenticated with your Scholens account."
													: connector.enabled
														? "Available to the agent when Read tools are enabled."
														: connector.connected
															? "Connected, but currently disabled."
															: "Enter an API key to connect."}
											</p>
										</div>
									</div>
									{connector.built_in ? (
										<Badge>Always on</Badge>
									) : connector.connected ? (
										<Switch
											checked={connector.enabled}
											disabled={isBusy}
											aria-label={`Enable ${connector.display_name}`}
											onCheckedChange={(checked) => void handleToggle(connector, checked)}
										/>
									) : null}
								</div>

								{!connector.built_in ? (
									<div className="flex gap-2">
										<Input
											type="password"
											autoComplete="off"
											value={keys[connector.provider] ?? ""}
											disabled={isBusy}
											placeholder={connector.connected ? "Enter a replacement API key" : "API key"}
											onChange={(event) =>
												setKeys((current) => ({
													...current,
													[connector.provider]: event.target.value,
												}))
											}
										/>
										<Button
											type="button"
											disabled={isBusy || !(keys[connector.provider]?.trim())}
											onClick={() => void handleConnect(connector)}
										>
											{isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : connector.connected ? "Replace" : "Connect"}
										</Button>
										{connector.connected ? (
											<Button
												type="button"
												variant="outline"
												size="icon"
												disabled={isBusy}
												aria-label={`Disconnect ${connector.display_name}`}
												onClick={() => void handleDisconnect(connector)}
											>
												<Trash2 className="h-4 w-4" />
											</Button>
										) : null}
									</div>
								) : null}
							</div>
						);
					})}
				</div>
			)}
		</div>
	);
}
