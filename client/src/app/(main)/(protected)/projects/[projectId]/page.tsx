"use client";

import { ArrowRight, BookOpen, Library, MessageCircle, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { fetchFromApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { MentionInput } from "@/components/chat/MentionInput";
import { WorkspacePermissionPicker } from "@/components/permissions/WorkspacePermissionPicker";
import {
    EMPTY_PAPER_CONTEXT_SELECTION,
    EMPTY_TURN_ATTACHMENTS,
    PaperContextSelection,
    TurnAttachments,
} from "@/components/chat/MentionAutocomplete";
import { AnimatedGradientText } from "@/components/magicui/animated-gradient-text";
import { isTokenCreditAtLimit, useSubscription } from "@/hooks/useSubscription";
import { useProjectWorkspace } from "@/components/project/ProjectWorkspaceProvider";
import { useProjects } from "@/hooks/useProjects";
import type { ConversationCreateRequest, ConversationDetail } from "@/lib/schema";
import {
    DEFAULT_CONVERSATION_TOOL_PERMISSIONS,
    serializeWorkspacePermissions,
    type WorkspacePermission,
} from "@/lib/workspace-permissions";

// Project home is the new-chat surface: a centered composer over the project's
// papers. Navigation to existing chats lives in the workspace rail.
export default function ProjectPage() {
    const router = useRouter();
    const {
        projectId,
        project,
        isProjectLoading,
        projectError,
        papers,
        isPapersLoading,
        conversations,
        isConversationsLoading,
        openAddPapers,
    } = useProjectWorkspace();

    const [error, setError] = useState<string | null>(null);
    const [newQuery, setNewQuery] = useState("");
    const { projects: allProjects } = useProjects();
    const [paperContextSelection, setPaperContextSelection] = useState<PaperContextSelection>({
        ...EMPTY_PAPER_CONTEXT_SELECTION,
        projectIds: [projectId],
    });
    const [turnAttachments, setTurnAttachments] = useState<TurnAttachments>(
        EMPTY_TURN_ATTACHMENTS,
    );
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [toolPermissions, setToolPermissions] = useState<WorkspacePermission[]>(
        () => [...DEFAULT_CONVERSATION_TOOL_PERMISSIONS],
    );
    const { subscription } = useSubscription();

    const aiDisabled = isTokenCreditAtLimit(subscription);
    const canManagePapers = project?.capabilities.manage_papers === true;

    useEffect(() => {
        const TOKEN_CREDIT_TOAST_KEY = "token_credit_limit_toast_shown";
        if (aiDisabled && !sessionStorage.getItem(TOKEN_CREDIT_TOAST_KEY)) {
            toast.error("You've used this week's Token Credits. Upgrade your plan to continue using AI features.", {
                action: {
                    label: "Upgrade",
                    onClick: () => router.push("/pricing"),
                },
            });
            sessionStorage.setItem(TOKEN_CREDIT_TOAST_KEY, "true");
        }
    }, [aiDisabled, router]);

    const handleNewQuery = async () => {
        if (!newQuery.trim()) return;

        setIsSubmitting(true);
        try {
            const createRequest: ConversationCreateRequest = {
                title: "New conversation",
                scope_type: "project",
                scope_id: projectId,
                paper_context: {
                    kind: "selection",
                    project_ids: paperContextSelection.projectIds,
                    document_ids: paperContextSelection.documentIds,
                },
                tool_permissions: serializeWorkspacePermissions(toolPermissions),
            };
            const newConversation = await fetchFromApi<ConversationDetail>("/conversations", {
                method: "POST",
                body: JSON.stringify(createRequest),
            });
            localStorage.setItem(`pending-query-${newConversation.id}`, newQuery);
            localStorage.setItem(
                `pending-paper-context-${newConversation.id}`,
                JSON.stringify(paperContextSelection),
            );
            localStorage.setItem(
                `pending-turn-attachments-${newConversation.id}`,
                JSON.stringify(turnAttachments),
            );
            router.push(`/projects/${projectId}/conversations/${newConversation.id}`);
        } catch (err) {
            setError("Failed to create a new conversation. Please try again.");
            console.error(err);
            setIsSubmitting(false);
        }
    };

    const isInitialLoading = isProjectLoading ||
        ((isPapersLoading || isConversationsLoading) && !papers.length && !conversations.length);

    if (isInitialLoading) {
        return (
            <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center space-y-4 px-4">
                <Skeleton className="mx-auto h-7 w-2/3" />
                <Skeleton className="h-28 w-full" />
                <Skeleton className="mx-auto h-4 w-40" />
            </div>
        );
    }

    if (projectError || error) {
        return <div className="p-4 text-red-500">{projectError?.message || error}</div>;
    }

    if (!project) {
        return <div className="p-4">Project not found.</div>;
    }

    const isEmpty = papers.length === 0 && conversations.length === 0;

    if (isEmpty) {
        return (
            <div className="flex-1 overflow-y-auto">
                <div className="mx-auto flex max-w-lg flex-col items-center justify-center px-4 py-12 text-center">
                    <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100 p-4 dark:bg-blue-900/30">
                        <BookOpen className="h-8 w-8 text-blue-500" />
                    </div>
                    <h2 className="mb-2 text-2xl font-bold">Get Started with Your Project</h2>
                    <p className="mb-8 text-muted-foreground">Add research papers to your project, then ask questions and generate insights.</p>

                    {canManagePapers && (
                        <div className="mb-8 grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
                            {/* Deep-link straight to the chosen flow — no second chooser in the sheet */}
                            <button
                                onClick={() => openAddPapers("upload")}
                                className="group flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors hover:bg-accent"
                            >
                                <UploadCloud className="mb-3 h-10 w-10 text-muted-foreground transition-colors group-hover:text-blue-500" />
                                <h3 className="font-semibold transition-colors group-hover:text-blue-600">Upload Papers</h3>
                                <p className="mt-1 text-sm text-muted-foreground">Upload PDFs from your computer</p>
                            </button>
                            <button
                                onClick={() => openAddPapers("library")}
                                className="group flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors hover:bg-accent"
                            >
                                <Library className="mb-3 h-10 w-10 text-muted-foreground transition-colors group-hover:text-blue-500" />
                                <h3 className="font-semibold transition-colors group-hover:text-blue-600">Add from Library</h3>
                                <p className="mt-1 text-sm text-muted-foreground">Choose from your existing papers</p>
                            </button>
                        </div>
                    )}

                    <div className="flex items-center gap-3 text-sm text-muted-foreground">
                        <div className="flex items-center gap-1.5">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-600 dark:bg-blue-900/30">1</span>
                            Add papers
                        </div>
                        <ArrowRight className="h-3 w-3" />
                        <div className="flex items-center gap-1.5">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">2</span>
                            Ask questions
                        </div>
                        <ArrowRight className="h-3 w-3" />
                        <div className="flex items-center gap-1.5">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">3</span>
                            Generate insights
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto">
            {/* min-h-full (not h-full) so tall content grows instead of clipping under justify-center */}
            <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-4 py-8">
                {papers.length > 0 ? (
                    <>
                        {/* The project itself is the hero — title + description ground the user */}
                        <div className="mb-6 text-center">
                            <AnimatedGradientText
                                className="text-2xl font-bold"
                                colorFrom="#6366f1"
                                colorTo="#3b82f6"
                            >
                                {project.title}
                            </AnimatedGradientText>
                            {project.description && (
                                <p className="mx-auto mt-2 max-w-lg text-sm text-muted-foreground">{project.description}</p>
                            )}
                        </div>
                        <MentionInput
                            value={newQuery}
                            onValueChange={setNewQuery}
                            onSubmit={handleNewQuery}
                            papers={papers}
                            projects={allProjects}
                            paperContext={paperContextSelection}
                            onPaperContextChange={setPaperContextSelection}
                            turnAttachments={turnAttachments}
                            onTurnAttachmentsChange={setTurnAttachments}
                            lockedProjectIds={[projectId]}
                            placeholder={aiDisabled ? "You have used this week's Token Credits. Upgrade your plan to continue." : "Ask a question about your papers, analyze findings, or explore new ideas..."}
                            disabled={aiDisabled || isSubmitting}
                            sendDisabled={!newQuery.trim()}
                            busy={isSubmitting}
                            autoFocus
                        />
                        <div className="mt-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-2">
                            <span className="text-xs font-medium text-foreground">Agent tools</span>
                            <WorkspacePermissionPicker
                                value={toolPermissions}
                                onChange={setToolPermissions}
                                disabled={isSubmitting}
                            />
                        </div>
                        <p className="mt-3 text-center text-xs text-muted-foreground">
                            {papers.length} paper{papers.length === 1 ? "" : "s"} in context · pick up past chats from the sidebar
                        </p>
                    </>
                ) : (
                    <div className="rounded-xl border-2 border-dashed bg-muted/30 p-8 text-center">
                        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted p-3">
                            <MessageCircle className="h-6 w-6 text-muted-foreground" />
                        </div>
                        <h3 className="mb-1 text-sm font-semibold">Ready to Start Conversations</h3>
                        <p className="text-sm text-muted-foreground">Add papers to your project to begin discussing and analyzing them.</p>
                        {canManagePapers && (
                            <Button variant="outline" size="sm" className="mt-3" onClick={() => openAddPapers()}>
                                Add papers
                            </Button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
