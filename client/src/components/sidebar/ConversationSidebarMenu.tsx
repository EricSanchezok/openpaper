"use client";

import {
    Archive,
    ArrowRight,
    ChevronDown,
    FolderInput,
    MessageSquare,
    MoreHorizontal,
    Pencil,
    Pin,
    PinOff,
    Trash2,
    Unlink,
} from "lucide-react";
import Link from "next/link";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarMenuSub,
    SidebarMenuSubButton,
    SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { fetchFromApi } from "@/lib/api";
import type { Conversation, Project } from "@/lib/schema";

interface ConversationSidebarMenuProps {
    conversations: Conversation[];
    projects: Project[];
    onChanged: (conversation: Conversation | string) => void;
}

function conversationUrl(conversation: Conversation): string {
    if (conversation.scope_type === "project" && conversation.scope_id) {
        return `/projects/${conversation.scope_id}/conversations/${conversation.id}`;
    }
    if (conversation.scope_type === "paper" && conversation.scope_id) {
        const query = new URLSearchParams({
            rsf: "chat",
            conversation: conversation.id,
        });
        return `/paper/${conversation.scope_id}?${query.toString()}`;
    }
    return `/understand?id=${conversation.id}`;
}

function ConversationActions({
    conversation,
    projects,
    onChanged,
}: {
    conversation: Conversation;
    projects: Project[];
    onChanged: (conversation: Conversation | string) => void;
}) {
    const patch = async (body: Record<string, unknown>) => {
        const updated = await fetchFromApi(`/conversations/${conversation.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
        }) as Conversation;
        onChanged(updated);
    };

    const move = async (scopeType: "global" | "project", scopeId?: string) => {
        const updated = await fetchFromApi(
            `/conversations/${conversation.id}/scope`,
            {
                method: "PUT",
                body: JSON.stringify({
                    scope_type: scopeType,
                    scope_id: scopeId ?? null,
                }),
            },
        ) as Conversation;
        onChanged(updated);
    };

    const rename = async () => {
        const title = window.prompt("Conversation title", conversation.title)?.trim();
        if (title && title !== conversation.title) {
            await patch({ title });
        }
    };

    const remove = async () => {
        if (!window.confirm(`Delete “${conversation.title}”?`)) return;
        await fetchFromApi(`/conversations/${conversation.id}`, {
            method: "DELETE",
        });
        onChanged(conversation.id);
    };

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    aria-label={`Actions for ${conversation.title}`}
                    className="rounded p-1 opacity-0 transition-opacity hover:bg-sidebar-accent group-hover/conversation:opacity-100 focus:opacity-100"
                    onClick={(event) => event.preventDefault()}
                >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="right">
                {conversation.capabilities.rename && (
                    <DropdownMenuItem onSelect={() => void rename()}>
                        <Pencil className="h-4 w-4" />
                        Rename
                    </DropdownMenuItem>
                )}
                {conversation.capabilities.pin && (
                    <DropdownMenuItem
                        onSelect={() => void patch({ pinned: !conversation.pinned_at })}
                    >
                        {conversation.pinned_at ? (
                            <PinOff className="h-4 w-4" />
                        ) : (
                            <Pin className="h-4 w-4" />
                        )}
                        {conversation.pinned_at ? "Unpin" : "Pin"}
                    </DropdownMenuItem>
                )}
                {conversation.capabilities.move
                    && conversation.scope_type === "global"
                    && projects.length > 0 && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger>
                                <FolderInput className="h-4 w-4" />
                                Move to project
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuLabel>Projects</DropdownMenuLabel>
                                {projects.map((project) => (
                                    <DropdownMenuItem
                                        key={project.id}
                                        onSelect={() => void move("project", project.id)}
                                    >
                                        {project.title}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                {conversation.capabilities.detach && (
                    <DropdownMenuItem onSelect={() => void move("global")}>
                        <Unlink className="h-4 w-4" />
                        Detach from project
                    </DropdownMenuItem>
                )}
                {conversation.capabilities.archive && (
                    <DropdownMenuItem onSelect={() => void patch({ archived: true })}>
                        <Archive className="h-4 w-4" />
                        Archive
                    </DropdownMenuItem>
                )}
                {conversation.capabilities.delete && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onSelect={() => void remove()}
                        >
                            <Trash2 className="h-4 w-4" />
                            Delete
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

function ConversationSection({
    label,
    conversations,
    projects,
    onChanged,
    defaultOpen,
}: {
    label: string;
    conversations: Conversation[];
    projects: Project[];
    onChanged: (conversation: Conversation | string) => void;
    defaultOpen: boolean;
}) {
    if (conversations.length === 0) return null;

    return (
        <Collapsible defaultOpen={defaultOpen}>
            <CollapsibleTrigger className="flex w-full items-center gap-1 px-2 py-1 text-[11px] font-medium text-muted-foreground">
                <ChevronDown className="h-3 w-3 transition-transform [[data-state=closed]>&]:-rotate-90" />
                {label}
            </CollapsibleTrigger>
            <CollapsibleContent>
                <SidebarMenuSub>
                    {conversations.map((conversation) => (
                        <SidebarMenuSubItem
                            key={conversation.id}
                            className="group/conversation"
                        >
                            <div className="flex items-center">
                                <SidebarMenuSubButton asChild className="min-w-0 flex-1">
                                    <Link href={conversationUrl(conversation)}>
                                        <div className="min-w-0">
                                            <p className="truncate text-xs font-medium">
                                                {conversation.title}
                                            </p>
                                            {conversation.scope_label && (
                                                <p className="truncate text-[10px] text-muted-foreground">
                                                    {conversation.scope_label}
                                                </p>
                                            )}
                                        </div>
                                    </Link>
                                </SidebarMenuSubButton>
                                <ConversationActions
                                    conversation={conversation}
                                    projects={projects}
                                    onChanged={onChanged}
                                />
                            </div>
                        </SidebarMenuSubItem>
                    ))}
                </SidebarMenuSub>
            </CollapsibleContent>
        </Collapsible>
    );
}

export function ConversationSidebarMenu({
    conversations,
    projects,
    onChanged,
}: ConversationSidebarMenuProps) {
    const pinned = conversations.filter((conversation) => conversation.pinned_at);
    const recent = conversations.filter((conversation) => !conversation.pinned_at);

    return (
        <SidebarMenuItem>
            <div className="flex items-center">
                <SidebarMenuButton asChild className="flex-1">
                    <Link href="/understand">
                        <MessageSquare />
                        <span>Ask</span>
                    </Link>
                </SidebarMenuButton>
            </div>
            <ConversationSection
                label="Pinned"
                conversations={pinned}
                projects={projects}
                onChanged={onChanged}
                defaultOpen
            />
            <ConversationSection
                label="Recent"
                conversations={recent.slice(0, 10)}
                projects={projects}
                onChanged={onChanged}
                defaultOpen={pinned.length === 0}
            />
            {conversations.length > 0 && (
                <SidebarMenuSub>
                    <SidebarMenuSubItem>
                        <SidebarMenuSubButton asChild>
                            <Link href="/understand/past" className="text-xs">
                                View conversations
                                <ArrowRight className="ml-auto h-3 w-3" />
                            </Link>
                        </SidebarMenuSubButton>
                    </SidebarMenuSubItem>
                </SidebarMenuSub>
            )}
        </SidebarMenuItem>
    );
}
