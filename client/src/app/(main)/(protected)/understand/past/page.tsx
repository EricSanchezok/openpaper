"use client";

import { Archive, ArchiveRestore, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { fetchFromApi } from "@/lib/api";
import type { ConversationListResponse, ConversationSummary } from "@/lib/schema";
import { cn, formatDate } from "@/lib/utils";

function conversationUrl(conversation: ConversationSummary): string {
    if (conversation.scope_type === "project" && conversation.scope_id) {
        return `/projects/${conversation.scope_id}/conversations/${conversation.id}`;
    }
    if (conversation.scope_type === "paper" && conversation.scope_id) {
        return `/paper/${conversation.scope_id}?rsf=chat&conversation=${conversation.id}`;
    }
    return `/understand?id=${conversation.id}`;
}

export default function PastConversationsPage() {
    const [archived, setArchived] = useState(false);
    const [conversations, setConversations] = useState<ConversationSummary[]>([]);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const response = await fetchFromApi(
                `/conversations?archived=${archived}&limit=100`,
            ) as ConversationListResponse;
            setConversations(response.items);
        } finally {
            setLoading(false);
        }
    }, [archived]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    const setArchivedState = async (
        conversation: ConversationSummary,
        nextArchived: boolean,
    ) => {
        await fetchFromApi(`/conversations/${conversation.id}`, {
            method: "PATCH",
            body: JSON.stringify({ archived: nextArchived }),
        });
        setConversations((current) =>
            current.filter((item) => item.id !== conversation.id),
        );
    };

    const remove = async (conversation: ConversationSummary) => {
        if (!window.confirm(`Delete “${conversation.title}”?`)) return;
        await fetchFromApi(`/conversations/${conversation.id}`, {
            method: "DELETE",
        });
        setConversations((current) =>
            current.filter((item) => item.id !== conversation.id),
        );
    };

    return (
        <div className="mx-auto p-4 md:w-2/3 md:p-6">
            <div className="mb-6 flex items-start justify-between">
                <div>
                    <h1 className="text-3xl font-bold">Conversations</h1>
                    <p className="mt-1 text-muted-foreground">
                        Your private chats across Scholens.
                    </p>
                </div>
                <Button variant="outline" asChild>
                    <Link href="/understand">
                        <Plus className="mr-2 h-4 w-4" />
                        New chat
                    </Link>
                </Button>
            </div>

            <div className="mb-5 flex gap-1 rounded-lg bg-muted p-1">
                {[false, true].map((value) => (
                    <button
                        key={String(value)}
                        type="button"
                        onClick={() => setArchived(value)}
                        className={cn(
                            "flex-1 rounded-md px-3 py-1.5 text-sm",
                            archived === value
                                ? "bg-background font-medium shadow-sm"
                                : "text-muted-foreground",
                        )}
                    >
                        {value ? "Archive" : "Active"}
                    </button>
                ))}
            </div>

            {loading ? (
                <p className="py-12 text-center text-sm text-muted-foreground">
                    Loading conversations…
                </p>
            ) : conversations.length === 0 ? (
                <p className="py-12 text-center text-sm text-muted-foreground">
                    {archived
                        ? "No archived conversations."
                        : "No conversations yet."}
                </p>
            ) : (
                <div className="divide-y rounded-lg border">
                    {conversations.map((conversation) => (
                        <div
                            key={conversation.id}
                            className="group flex items-center gap-3 p-3"
                        >
                            <Link
                                href={conversationUrl(conversation)}
                                className="min-w-0 flex-1"
                            >
                                <p className="truncate text-sm font-medium">
                                    {conversation.title}
                                </p>
                                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                                    {conversation.scope_label ?? "Everything"}
                                    {" · "}
                                    {formatDate(conversation.updated_at)}
                                    {conversation.read_only
                                        ? " · Read-only"
                                        : ""}
                                </p>
                            </Link>
                            <Button
                                variant="ghost"
                                size="icon"
                                title={archived ? "Restore" : "Archive"}
                                onClick={() =>
                                    void setArchivedState(conversation, !archived)
                                }
                            >
                                {archived ? (
                                    <ArchiveRestore className="h-4 w-4" />
                                ) : (
                                    <Archive className="h-4 w-4" />
                                )}
                            </Button>
                            <Button
                                variant="ghost"
                                size="icon"
                                title="Delete"
                                onClick={() => void remove(conversation)}
                            >
                                <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
