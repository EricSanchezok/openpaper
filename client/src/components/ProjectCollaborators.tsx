"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Users, X } from "lucide-react";
import { toast } from "sonner";
import { fetchFromApi } from "@/lib/api";
import {
    Collaborator,
    Project,
    ProjectInvitation,
    ProjectPermissions,
} from "@/lib/schema";
import { getAlphaHashToBackgroundColor, getInitials } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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

const NO_PERMISSIONS: ProjectPermissions = {
    edit_project: false,
    manage_papers: false,
    manage_collaborators: false,
};

const PERMISSION_LABELS: Array<[keyof ProjectPermissions, string]> = [
    ["edit_project", "Edit project details"],
    ["manage_papers", "Manage paper collection"],
    ["manage_collaborators", "Manage collaborators"],
];

interface ProjectCollaboratorsProps {
    project: Project;
    setHasCollaborators?: (hasCollaborators: boolean) => void;
    onProjectChanged?: () => Promise<void>;
}

export function ProjectCollaborators({
    project,
    setHasCollaborators,
    onProjectChanged,
}: ProjectCollaboratorsProps) {
    const [collaborators, setCollaborators] = useState<Collaborator[]>([]);
    const [invitations, setInvitations] = useState<ProjectInvitation[]>([]);
    const [open, setOpen] = useState(false);
    const [email, setEmail] = useState("");
    const [invitePermissions, setInvitePermissions] =
        useState<ProjectPermissions>(NO_PERMISSIONS);
    const [saving, setSaving] = useState(false);
    const [transferTarget, setTransferTarget] = useState<Collaborator | null>(null);

    const canManage = project.capabilities.manage_collaborators;
    const actorPermissions = project.membership.permissions;

    const actorContains = (permissions: ProjectPermissions) =>
        project.membership.kind === "owner" ||
        ((!permissions.edit_project || actorPermissions.edit_project) &&
            (!permissions.manage_papers || actorPermissions.manage_papers) &&
            (!permissions.manage_collaborators ||
                actorPermissions.manage_collaborators));

    const canManageMember = (member: Collaborator) =>
        canManage && !member.is_owner && actorContains(member.permissions);

    const load = useCallback(async () => {
        try {
            const loadedCollaborators = await fetchFromApi(
                `/api/projects/${project.id}/members`,
            ) as Collaborator[];
            setCollaborators(loadedCollaborators);
            setHasCollaborators?.(loadedCollaborators.length > 1);
            if (canManage) {
                const loadedInvitations = await fetchFromApi(
                    `/api/projects/${project.id}/invitations`,
                ) as ProjectInvitation[];
                setInvitations(loadedInvitations);
            } else {
                setInvitations([]);
            }
        } catch (error) {
            console.error("Failed to load project collaborators", error);
            toast.error("Failed to load project collaborators.");
        }
    }, [canManage, project.id, setHasCollaborators]);

    useEffect(() => {
        void load();
    }, [load]);

    const updateMemberPermission = async (
        member: Collaborator,
        permission: keyof ProjectPermissions,
        enabled: boolean,
    ) => {
        const permissions = {
            ...member.permissions,
            [permission]: enabled,
        };
        try {
            const updated = await fetchFromApi(
                `/api/projects/${project.id}/members/${member.user_id}`,
                {
                    method: "PATCH",
                    body: JSON.stringify(permissions),
                },
            ) as Collaborator;
            setCollaborators((current) =>
                current.map((item) =>
                    item.user_id === updated.user_id ? updated : item,
                ),
            );
        } catch (error) {
            console.error("Failed to update collaborator permissions", error);
            toast.error(
                error instanceof Error
                    ? error.message
                    : "Failed to update permissions.",
            );
        }
    };

    const removeMember = async (member: Collaborator) => {
        try {
            await fetchFromApi(
                `/api/projects/${project.id}/members/${member.user_id}`,
                { method: "DELETE" },
            );
            setCollaborators((current) =>
                current.filter((item) => item.user_id !== member.user_id),
            );
            toast.success("Collaborator removed.");
        } catch (error) {
            console.error("Failed to remove collaborator", error);
            toast.error(
                error instanceof Error
                    ? error.message
                    : "Failed to remove collaborator.",
            );
        }
    };

    const transferOwnership = async () => {
        if (!transferTarget) return;
        setSaving(true);
        try {
            await fetchFromApi(`/api/projects/${project.id}/transfer`, {
                method: "POST",
                body: JSON.stringify({ new_owner_id: transferTarget.user_id }),
            });
            setTransferTarget(null);
            await Promise.all([load(), onProjectChanged?.()]);
            toast.success("Project ownership transferred.");
        } catch (error) {
            console.error("Failed to transfer project ownership", error);
            toast.error(
                error instanceof Error
                    ? error.message
                    : "Failed to transfer ownership.",
            );
        } finally {
            setSaving(false);
        }
    };

    const sendInvitation = async () => {
        if (!email.includes("@")) {
            toast.error("Enter a valid email address.");
            return;
        }
        setSaving(true);
        try {
            const invitation = await fetchFromApi(
                `/api/projects/${project.id}/invitations`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        email,
                        ...invitePermissions,
                    }),
                },
            ) as ProjectInvitation;
            setInvitations((current) => [invitation, ...current]);
            setEmail("");
            setInvitePermissions(NO_PERMISSIONS);
            toast.success("Invitation sent.");
        } catch (error) {
            console.error("Failed to invite collaborator", error);
            toast.error(
                error instanceof Error
                    ? error.message
                    : "Failed to send invitation.",
            );
        } finally {
            setSaving(false);
        }
    };

    const revokeInvitation = async (invitationId: string) => {
        try {
            await fetchFromApi(
                `/api/projects/${project.id}/invitations/${invitationId}`,
                { method: "DELETE" },
            );
            setInvitations((current) =>
                current.filter((item) => item.id !== invitationId),
            );
        } catch (error) {
            console.error("Failed to revoke invitation", error);
            toast.error("Failed to revoke invitation.");
        }
    };

    const visibleCollaborators = collaborators.slice(0, 4);

    return (
        <>
            <button
                type="button"
                className="flex items-center -space-x-2"
                onClick={() => setOpen(true)}
                aria-label="Project collaborators"
            >
                {visibleCollaborators.map((member) => {
                    const name = member.display_name || member.email;
                    return (
                        <Avatar
                            key={member.user_id}
                            className="h-8 w-8 border-2 border-background"
                        >
                            <AvatarFallback
                                className={getAlphaHashToBackgroundColor(name)}
                            >
                                {getInitials(name)}
                            </AvatarFallback>
                        </Avatar>
                    );
                })}
                {collaborators.length === 0 && (
                    <span className="flex h-8 w-8 items-center justify-center rounded-full border">
                        <Users className="h-4 w-4" />
                    </span>
                )}
            </button>

            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>Project collaborators</DialogTitle>
                        <DialogDescription>
                            Everyone can read the project and contribute research.
                            Management permissions are delegated independently.
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-3">
                        {collaborators.map((member) => (
                            <div
                                key={member.user_id}
                                className="rounded-lg border p-3"
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-medium">
                                            {member.display_name || member.email}
                                            {member.is_owner ? " · Owner" : ""}
                                        </p>
                                        <p className="truncate text-xs text-muted-foreground">
                                            {member.email}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-1">
                                        {project.capabilities.transfer &&
                                            !member.is_owner && (
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() =>
                                                        setTransferTarget(member)
                                                    }
                                                >
                                                    Make owner
                                                </Button>
                                            )}
                                        {canManageMember(member) && (
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => void removeMember(member)}
                                                aria-label="Remove collaborator"
                                            >
                                                <X className="h-4 w-4" />
                                            </Button>
                                        )}
                                    </div>
                                </div>
                                {!member.is_owner && (
                                    <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                        {PERMISSION_LABELS.map(([key, label]) => (
                                            <Label
                                                key={key}
                                                className="flex items-center gap-2 text-xs"
                                            >
                                                <Checkbox
                                                    checked={member.permissions[key]}
                                                    disabled={
                                                        !canManageMember(member) ||
                                                        (!actorPermissions[key] &&
                                                            project.membership.kind !==
                                                                "owner")
                                                    }
                                                    onCheckedChange={(checked) =>
                                                        void updateMemberPermission(
                                                            member,
                                                            key,
                                                            checked === true,
                                                        )
                                                    }
                                                />
                                                {label}
                                            </Label>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {canManage && (
                        <div className="space-y-3 border-t pt-4">
                            <div className="flex gap-2">
                                <Input
                                    type="email"
                                    value={email}
                                    onChange={(event) => setEmail(event.target.value)}
                                    placeholder="collaborator@example.com"
                                />
                                <Button
                                    onClick={() => void sendInvitation()}
                                    disabled={saving}
                                >
                                    <Plus className="mr-1 h-4 w-4" />
                                    Invite
                                </Button>
                            </div>
                            <div className="grid gap-2 sm:grid-cols-3">
                                {PERMISSION_LABELS.map(([key, label]) => (
                                    <Label
                                        key={key}
                                        className="flex items-center gap-2 text-xs"
                                    >
                                        <Checkbox
                                            checked={invitePermissions[key]}
                                            disabled={
                                                !actorPermissions[key] &&
                                                project.membership.kind !== "owner"
                                            }
                                            onCheckedChange={(checked) =>
                                                setInvitePermissions((current) => ({
                                                    ...current,
                                                    [key]: checked === true,
                                                }))
                                            }
                                        />
                                        {label}
                                    </Label>
                                ))}
                            </div>
                            {invitations.map((invitation) => (
                                <div
                                    key={invitation.id}
                                    className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm"
                                >
                                    <span>{invitation.email} · pending</span>
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() =>
                                            void revokeInvitation(invitation.id)
                                        }
                                    >
                                        Revoke
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}

                    <DialogFooter>
                        <Button variant="secondary" onClick={() => setOpen(false)}>
                            Close
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <AlertDialog
                open={transferTarget !== null}
                onOpenChange={(isOpen) => {
                    if (!isOpen) setTransferTarget(null);
                }}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Transfer project ownership?</AlertDialogTitle>
                        <AlertDialogDescription>
                            {transferTarget
                                ? `${transferTarget.display_name || transferTarget.email} will become the owner. You will remain a collaborator with all management permissions.`
                                : ""}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            disabled={saving}
                            onClick={() => void transferOwnership()}
                        >
                            Transfer ownership
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}
