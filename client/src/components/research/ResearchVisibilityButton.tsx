"use client";

import { LockKeyhole, UsersRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { fetchFromApi } from "@/lib/api";
import { cn } from "@/lib/utils";

export type ResearchOutputKind = "artifact" | "audio" | "data_table" | "highlight";

interface ResearchVisibilityButtonProps {
    kind: ResearchOutputKind;
    outputId: string;
    shared: boolean;
    canManage: boolean;
    onChanged: (shared: boolean) => void;
    className?: string;
}

export function ResearchVisibilityButton({
    kind,
    outputId,
    shared,
    canManage,
    onChanged,
    className,
}: ResearchVisibilityButtonProps) {
    const [isSaving, setIsSaving] = useState(false);

    if (!canManage) {
        return (
            <span
                className={cn(
                    "inline-flex items-center gap-1 text-xs text-muted-foreground",
                    className,
                )}
                title={shared ? "Shared with Project collaborators" : "Visible only to its creator"}
            >
                {shared ? <UsersRound className="h-3.5 w-3.5" /> : <LockKeyhole className="h-3.5 w-3.5" />}
                {shared ? "Shared" : "Hidden"}
            </span>
        );
    }

    const toggleVisibility = async () => {
        if (isSaving) return;
        const nextShared = !shared;
        setIsSaving(true);
        try {
            await fetchFromApi(`/api/research/${kind}/${outputId}/visibility`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ shared: nextShared }),
            });
            onChanged(nextShared);
            toast.success(
                nextShared
                    ? "Shared with Project collaborators"
                    : "Hidden from Project collaborators",
            );
        } catch (error) {
            console.error("Failed to update research visibility:", error);
            toast.error("Could not update sharing");
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn("h-7 gap-1.5 px-2 text-xs text-muted-foreground", className)}
            disabled={isSaving}
            onClick={(event) => {
                event.stopPropagation();
                void toggleVisibility();
            }}
            title={shared ? "Hide from Project collaborators" : "Share with Project collaborators"}
        >
            {shared ? <UsersRound className="h-3.5 w-3.5" /> : <LockKeyhole className="h-3.5 w-3.5" />}
            {isSaving ? "Saving…" : shared ? "Shared" : "Hidden"}
        </Button>
    );
}
