"use client";

import { Loader2, Sparkles, Table, Trash2, Volume2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import DataTableSchemaModal, {
    FieldDefinition,
} from "@/components/DataTableSchemaModal";
import { ResearchVisibilityButton } from "@/components/research/ResearchVisibilityButton";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useProjectWorkspace } from "@/components/project/ProjectWorkspaceProvider";
import { isTokenCreditAtLimit, useSubscription } from "@/hooks/useSubscription";
import { fetchFromApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DurableJob, ResearchItem } from "@/lib/schema";

const audioLengthOptions = [
    { label: "Short (5–10 mins)", value: "short" },
    { label: "Medium (10–20 mins)", value: "medium" },
    { label: "Long (20+ mins)", value: "long" },
] as const;

interface CreateTileProps {
    icon: React.ReactNode;
    label: string;
    description: string;
    disabled: boolean;
    onClick: () => void;
}

function CreateTile({
    icon,
    label,
    description,
    disabled,
    onClick,
}: CreateTileProps) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            className="flex flex-col gap-1.5 rounded-lg border p-3 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
                {icon}
            </div>
            <span className="text-sm font-semibold">{label}</span>
            <span className="text-xs leading-snug text-muted-foreground">
                {description}
            </span>
        </button>
    );
}

function ResearchItemCard({
    item,
    onChanged,
    onDeleted,
}: {
    item: ResearchItem;
    onChanged: (shared: boolean) => void;
    onDeleted: () => void;
}) {
    const deleteItem = async () => {
        try {
            await fetchFromApi(`/research-items/${item.id}`, {
                method: "DELETE",
            });
            onDeleted();
        } catch (error) {
            console.error("Failed to delete research item", error);
            toast.error("Could not delete this research item.");
        }
    };

    return (
        <article className="space-y-3 rounded-lg border p-3">
            <header className="flex items-center justify-between gap-2">
                <div>
                    <p className="text-sm font-medium">
                        {item.audio_overview?.title
                            || item.data_table?.title
                            || (item.kind === "citation" ? "Citation" : "Research item")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                        {item.kind.replaceAll("_", " ")}
                        {item.created_by.display_name
                            ? ` · ${item.created_by.display_name}`
                            : ""}
                    </p>
                </div>
                <div className="flex items-center">
                    <ResearchVisibilityButton
                        outputId={item.id}
                        shared={item.is_shared}
                        canManage={item.capabilities.share}
                        onChanged={onChanged}
                    />
                    {item.capabilities.delete && (
                        <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => void deleteItem()}
                            aria-label="Delete research item"
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                    )}
                </div>
            </header>

            {item.audio_overview && (
                <>
                    <audio
                        controls
                        preload="metadata"
                        className="w-full"
                        src={item.audio_overview.audio_url}
                    />
                    <details className="text-xs">
                        <summary className="cursor-pointer text-muted-foreground">
                            Transcript
                        </summary>
                        <p className="mt-2 whitespace-pre-wrap leading-relaxed">
                            {item.audio_overview.transcript}
                        </p>
                    </details>
                </>
            )}

            {item.data_table && (
                <div className="overflow-x-auto text-xs">
                    <table className="w-full border-collapse">
                        <thead>
                            <tr>
                                {item.data_table.columns.map((column) => (
                                    <th
                                        key={column}
                                        className="border-b px-2 py-1 text-left font-medium"
                                    >
                                        {column}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {item.data_table.rows.slice(0, 5).map((row, index) => (
                                <tr key={index}>
                                    {item.data_table?.columns.map((column) => (
                                        <td key={column} className="border-b px-2 py-1 align-top">
                                            {JSON.stringify(row[column] ?? "")}
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {item.data_table.rows.length > 5 && (
                        <p className="mt-2 text-muted-foreground">
                            Showing 5 of {item.data_table.rows.length} rows.
                        </p>
                    )}
                </div>
            )}

            {item.citation && (
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify(item.citation.snapshot, null, 2)}
                </pre>
            )}
        </article>
    );
}

export function ArtifactsPanel() {
    const { projectId, papers, rightPanel, closeArtifacts } = useProjectWorkspace();
    const { subscription, refetch: refetchSubscription } = useSubscription();
    const tokenCreditLimitReached = isTokenCreditAtLimit(subscription);
    const [items, setItems] = useState<ResearchItem[]>([]);
    const [jobs, setJobs] = useState<DurableJob[]>([]);
    const [audioInstructions, setAudioInstructions] = useState("");
    const [audioLength, setAudioLength] = useState<"short" | "medium" | "long">(
        "medium",
    );
    const [audioDialogOpen, setAudioDialogOpen] = useState(false);
    const [tableDialogOpen, setTableDialogOpen] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const refresh = useCallback(async () => {
        try {
            const [researchResponse, jobResponse] = await Promise.all([
                fetchFromApi(`/projects/${projectId}/research-items`),
                fetchFromApi(`/jobs?project_id=${projectId}&active=true`),
            ]);
            setItems(researchResponse.items ?? []);
            setJobs(jobResponse.items ?? []);
        } catch (error) {
            console.error("Failed to load Project research items", error);
        }
    }, [projectId]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    useEffect(() => {
        if (jobs.length === 0) return;
        const timer = window.setInterval(() => void refresh(), 5_000);
        return () => window.clearInterval(timer);
    }, [jobs.length, refresh]);

    const createAudio = async () => {
        if (tokenCreditLimitReached) {
            toast.error("Your weekly Token Credits are exhausted.");
            return;
        }
        setSubmitting(true);
        try {
            await fetchFromApi(`/projects/${projectId}/audio-overviews`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    additional_instructions: audioInstructions.trim() || null,
                    length: audioLength,
                }),
            });
            setAudioDialogOpen(false);
            setAudioInstructions("");
            await refresh();
            await refetchSubscription();
        } catch (error) {
            console.error("Failed to create audio overview", error);
            toast.error("Could not start the audio overview.");
        } finally {
            setSubmitting(false);
        }
    };

    const createDataTable = async (columns: FieldDefinition[]) => {
        setTableDialogOpen(false);
        setSubmitting(true);
        try {
            await fetchFromApi(`/projects/${projectId}/data-tables`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    columns: columns.map((column) => column.label),
                }),
            });
            await refresh();
            await refetchSubscription();
        } catch (error) {
            console.error("Failed to create data table", error);
            toast.error("Could not start the data table.");
        } finally {
            setSubmitting(false);
        }
    };

    const activeJobs = useMemo(
        () => jobs.filter((job) => job.status === "pending" || job.status === "running"),
        [jobs],
    );

    return (
        <>
            <aside
                className={cn(
                    "flex-col bg-background",
                    rightPanel === "artifacts" ? "flex" : "hidden",
                    "fixed inset-0 z-40 md:static md:z-auto md:w-[400px] md:shrink-0 md:border-l",
                )}
            >
                <div className="flex h-11 shrink-0 items-center justify-between border-b px-4">
                    <div className="flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-blue-500" />
                        <h2 className="text-sm font-semibold">Research</h2>
                    </div>
                    <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={closeArtifacts}
                        aria-label="Close research panel"
                    >
                        <X className="h-4 w-4" />
                    </Button>
                </div>

                <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4">
                    <div className="grid grid-cols-2 gap-2">
                        <CreateTile
                            icon={<Volume2 className="h-4 w-4" />}
                            label="Audio overview"
                            description="A spoken synthesis of Project papers"
                            disabled={papers.length === 0 || submitting}
                            onClick={() => setAudioDialogOpen(true)}
                        />
                        <CreateTile
                            icon={<Table className="h-4 w-4" />}
                            label="Data table"
                            description="Compare findings across Project papers"
                            disabled={papers.length === 0 || submitting}
                            onClick={() => setTableDialogOpen(true)}
                        />
                    </div>

                    {activeJobs.map((job) => (
                        <div
                            key={job.id}
                            className="flex items-center gap-2 rounded-lg border p-3 text-xs"
                        >
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            <span className="capitalize">
                                {job.operation.replaceAll("_", " ")}
                            </span>
                            <span className="ml-auto text-muted-foreground">
                                {job.progress_message || job.status}
                            </span>
                        </div>
                    ))}

                    <div className="space-y-3">
                        {items.map((item) => (
                            <ResearchItemCard
                                key={item.id}
                                item={item}
                                onChanged={(shared) =>
                                    setItems((current) =>
                                        current.map((candidate) =>
                                            candidate.id === item.id
                                                ? { ...candidate, is_shared: shared }
                                                : candidate,
                                        ),
                                    )
                                }
                                onDeleted={() =>
                                    setItems((current) =>
                                        current.filter(
                                            (candidate) => candidate.id !== item.id,
                                        ),
                                    )
                                }
                            />
                        ))}
                        {items.length === 0 && activeJobs.length === 0 && (
                            <p className="text-xs text-muted-foreground">
                                No research outputs yet.
                            </p>
                        )}
                    </div>
                </div>
            </aside>

            <Dialog open={audioDialogOpen} onOpenChange={setAudioDialogOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Create audio overview</DialogTitle>
                        <DialogDescription>
                            Scholens will synthesize the current Project papers.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <Label htmlFor="audio-length">Length</Label>
                            <Select
                                value={audioLength}
                                onValueChange={(value) =>
                                    setAudioLength(value as typeof audioLength)
                                }
                            >
                                <SelectTrigger id="audio-length">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {audioLengthOptions.map((option) => (
                                        <SelectItem
                                            key={option.value}
                                            value={option.value}
                                        >
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="audio-instructions">
                                Additional instructions
                            </Label>
                            <Textarea
                                id="audio-instructions"
                                maxLength={10_000}
                                value={audioInstructions}
                                onChange={(event) =>
                                    setAudioInstructions(event.target.value)
                                }
                            />
                        </div>
                        <Button
                            className="w-full"
                            disabled={submitting}
                            onClick={() => void createAudio()}
                        >
                            {submitting && (
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            )}
                            Create
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>

            <DataTableSchemaModal
                open={tableDialogOpen}
                onOpenChange={setTableDialogOpen}
                onSubmit={(columns) => void createDataTable(columns)}
                isCreating={submitting}
            />
        </>
    );
}
