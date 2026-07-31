"use client"

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { AccessKeySettingsSection } from "@/components/settings/access-keys/AccessKeySettingsSection";
import { ConnectorSettingsSection } from "@/components/settings/connectors/ConnectorSettingsSection";
import { ZoteroIntegrationCard } from "@/components/zotero";
import { useAuth } from "@/lib/auth";
import { Loader2 } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { toast } from "sonner";

function SettingsContent() {
	const { user, loading, updateProfile } = useAuth();
	const [name, setName] = useState("");
	const [isSaving, setIsSaving] = useState(false);

	useEffect(() => {
		if (user?.display_name) {
			setName(user.display_name);
		}
	}, [user?.display_name]);

	// Content renders after the user loads, so the browser's native hash scroll
	// fires too early — re-run it once the anchor target exists.
	useEffect(() => {
		if (!loading && user && window.location.hash === "#zotero") {
			document.getElementById("zotero")?.scrollIntoView({ block: "start" });
		}
	}, [loading, user]);

	const handleSave = async (e: React.FormEvent) => {
		e.preventDefault();
		const trimmed = name.trim();
		if (!trimmed) {
			toast.error("Name cannot be empty.");
			return;
		}

		setIsSaving(true);
		try {
			await updateProfile(trimmed);
			toast.success("Profile updated.");
		} catch (error) {
			toast.error(error instanceof Error ? error.message : "Failed to update profile.");
		} finally {
			setIsSaving(false);
		}
	};

	if (loading || !user) {
		return (
			<div className="flex items-center justify-center h-full">
				<Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
			</div>
		);
	}

	return (
		<div className="max-w-2xl p-6 space-y-6">
			<h1 className="text-2xl font-bold">Settings</h1>

			<div className="space-y-1">
				<h2 className="text-lg font-medium">Profile</h2>
				<p className="text-sm text-muted-foreground">Manage your account details.</p>
			</div>
			<form onSubmit={handleSave} className="space-y-4">
				<div className="space-y-2">
					<Label htmlFor="name">Name</Label>
					<Input
						id="name"
						value={name}
						onChange={(e) => setName(e.target.value)}
						placeholder="Your name"
						disabled={isSaving}
					/>
				</div>
				<div className="space-y-2">
					<Label htmlFor="email">Email</Label>
					<Input
						id="email"
						value={user.email}
						disabled
						title={user.email}
						className="bg-muted truncate"
					/>
				</div>
				<Button type="submit" disabled={isSaving || !name.trim()}>
					{isSaving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
					Save
				</Button>
			</form>

			<Separator />

			<AccessKeySettingsSection />

			<Separator />

			<div id="zotero" className="space-y-4 scroll-mt-6">
				<div className="space-y-1">
					<h2 className="text-lg font-medium">Integrations</h2>
					<p className="text-sm text-muted-foreground">
						Connect external services to your account.
					</p>
				</div>

				<ZoteroIntegrationCard />

				<ConnectorSettingsSection />
			</div>
		</div>
	);
}

export default function SettingsPage() {
	return (
		<Suspense
			fallback={
				<div className="flex items-center justify-center h-full">
					<Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
				</div>
			}
		>
			<SettingsContent />
		</Suspense>
	);
}
