"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Mail, X } from "lucide-react";
import { toast } from "sonner";
import { fetchFromApi } from "@/lib/api";
import { ProjectInvitation, ProjectPermissions } from "@/lib/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";

const PERMISSION_LABELS: Array<[keyof ProjectPermissions, string]> = [
    ["edit_project", "Edit details"],
    ["manage_papers", "Manage papers"],
    ["manage_collaborators", "Manage collaborators"],
];

interface ProjectInvitationsProps {
    onInvitationAccepted?: () => void;
    defaultOpen?: boolean;
}

export function ProjectInvitations({
    onInvitationAccepted,
    defaultOpen = false,
}: ProjectInvitationsProps) {
    const [open, setOpen] = useState(defaultOpen);
    const [invitations, setInvitations] = useState<ProjectInvitation[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());

    const fetchInvitations = useCallback(async () => {
        setIsLoading(true);
        try {
            const response = await fetchFromApi("/api/project-invitations") as ProjectInvitation[];
            setInvitations(response);
        } catch (error) {
            console.error("Failed to fetch project invitations", error);
            toast.error("Failed to load project invitations.");
            setInvitations([]);
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        void fetchInvitations();
    }, [fetchInvitations]);

    const runInvitationAction = async (
        invitationId: string,
        action: "accept" | "decline",
    ) => {
        setProcessingIds((current) => new Set(current).add(invitationId));
        try {
            await fetchFromApi(
                action === "accept"
                    ? `/api/project-invitations/${invitationId}/accept`
                    : `/api/project-invitations/${invitationId}`,
                { method: action === "accept" ? "POST" : "DELETE" },
            );
            setInvitations((current) =>
                current.filter((invitation) => invitation.id !== invitationId),
            );
            toast.success(
                action === "accept"
                    ? "Project invitation accepted."
                    : "Project invitation declined.",
            );
            if (action === "accept") {
                onInvitationAccepted?.();
            }
        } catch (error) {
            console.error(`Failed to ${action} project invitation`, error);
            toast.error(
                error instanceof Error
                    ? error.message
                    : `Failed to ${action} invitation.`,
            );
        } finally {
            setProcessingIds((current) => {
                const next = new Set(current);
                next.delete(invitationId);
                return next;
            });
        }
    };

    if (!isLoading && invitations.length === 0) {
        return null;
    }

    return (
        <>
            <Button
                variant="outline"
                className="relative"
                onClick={() => setOpen(true)}
                aria-label="Project invitations"
            >
                <Mail className="h-4 w-4" />
                {invitations.length > 0 && (
                    <Badge className="absolute -right-2 -top-2 flex h-5 min-w-5 items-center justify-center rounded-full border-2 border-background bg-green-500 p-0 text-xs text-white">
                        {invitations.length}
                    </Badge>
                )}
            </Button>

            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Project invitations</DialogTitle>
                        <DialogDescription>
                            Invitations grant access to a shared paper collection.
                            They do not count toward your owned-project quota.
                        </DialogDescription>
                    </DialogHeader>

                    {isLoading ? (
                        <div className="flex justify-center py-8">
                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {invitations.map((invitation) => {
                                const isProcessing = processingIds.has(invitation.id);
                                const grantedPermissions = PERMISSION_LABELS.filter(
                                    ([permission]) => invitation.permissions[permission],
                                );
                                return (
                                    <div
                                        key={invitation.id}
                                        className="flex items-center justify-between gap-4 rounded-lg border p-4"
                                    >
                                        <div className="min-w-0">
                                            <h3 className="truncate font-semibold">
                                                {invitation.project_name}
                                            </h3>
                                            <p className="text-sm text-muted-foreground">
                                                Invited by {invitation.invited_by}
                                            </p>
                                            <div className="mt-2 flex flex-wrap gap-1">
                                                <Badge variant="secondary">Read and contribute</Badge>
                                                {grantedPermissions.map(([permission, label]) => (
                                                    <Badge key={permission} variant="outline">
                                                        {label}
                                                    </Badge>
                                                ))}
                                            </div>
                                            <p className="mt-2 text-xs text-muted-foreground">
                                                Expires {new Date(invitation.expires_at).toLocaleDateString()}
                                            </p>
                                        </div>
                                        <div className="flex shrink-0 gap-2">
                                            <Button
                                                variant="outline"
                                                size="icon"
                                                disabled={isProcessing}
                                                onClick={() =>
                                                    void runInvitationAction(
                                                        invitation.id,
                                                        "decline",
                                                    )
                                                }
                                                aria-label="Decline invitation"
                                            >
                                                <X className="h-4 w-4" />
                                            </Button>
                                            <Button
                                                size="icon"
                                                disabled={isProcessing}
                                                onClick={() =>
                                                    void runInvitationAction(
                                                        invitation.id,
                                                        "accept",
                                                    )
                                                }
                                                aria-label="Accept invitation"
                                            >
                                                {isProcessing ? (
                                                    <Loader2 className="h-4 w-4 animate-spin" />
                                                ) : (
                                                    <Check className="h-4 w-4" />
                                                )}
                                            </Button>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </>
    );
}
