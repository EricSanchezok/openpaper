"use client";

import { Loader2, Volume2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ResearchVisibilityButton } from "@/components/research/ResearchVisibilityButton";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { fetchFromApi } from "@/lib/api";
import type {
    DurableJob,
    JobListResponse,
    ResearchItem,
    ResearchItemListResponse,
} from "@/lib/schema";

interface AudioOverviewProps {
    document_id: string;
}

export function AudioOverviewPanel({ document_id }: AudioOverviewProps) {
    const [items, setItems] = useState<ResearchItem[]>([]);
    const [jobs, setJobs] = useState<DurableJob[]>([]);
    const [instructions, setInstructions] = useState("");
    const [length, setLength] = useState<"short" | "medium" | "long">("medium");
    const [submitting, setSubmitting] = useState(false);

    const refresh = useCallback(async () => {
        try {
            const [researchResponse, jobResponse] = await Promise.all([
                fetchFromApi<ResearchItemListResponse>(`/papers/${document_id}/research-items`),
                fetchFromApi<JobListResponse>(
                    `/jobs?document_id=${document_id}&operation=audio_generate&active=true`,
                ),
            ]);
            setItems(
                (researchResponse.items ?? []).filter(
                    (item: ResearchItem) => item.kind === "audio_overview",
                ),
            );
            setJobs(jobResponse.items ?? []);
        } catch (error) {
            console.error("Failed to load audio overviews", error);
        }
    }, [document_id]);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    useEffect(() => {
        if (jobs.length === 0) return;
        const timer = window.setInterval(() => void refresh(), 5_000);
        return () => window.clearInterval(timer);
    }, [jobs.length, refresh]);

    const create = async () => {
        setSubmitting(true);
        try {
            await fetchFromApi(`/papers/${document_id}/audio-overviews`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    additional_instructions: instructions.trim() || null,
                    length,
                }),
            });
            setInstructions("");
            await refresh();
        } catch (error) {
            console.error("Failed to start audio overview", error);
            toast.error("Could not start the audio overview.");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="space-y-5 p-3">
            <div>
                <div className="mb-2 flex items-center gap-2">
                    <Volume2 className="h-4 w-4 text-blue-500" />
                    <h2 className="text-sm font-semibold">Audio overview</h2>
                </div>
                <div className="space-y-3 rounded-lg border p-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="paper-audio-length">Length</Label>
                        <Select
                            value={length}
                            onValueChange={(value) =>
                                setLength(value as typeof length)
                            }
                        >
                            <SelectTrigger id="paper-audio-length">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="short">Short</SelectItem>
                                <SelectItem value="medium">Medium</SelectItem>
                                <SelectItem value="long">Long</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <Textarea
                        value={instructions}
                        maxLength={10_000}
                        placeholder="Optional focus or instructions"
                        onChange={(event) => setInstructions(event.target.value)}
                    />
                    <Button
                        className="w-full"
                        disabled={submitting}
                        onClick={() => void create()}
                    >
                        {submitting && (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        Generate
                    </Button>
                </div>
            </div>

            {jobs.map((job) => (
                <div
                    key={job.id}
                    className="flex items-center gap-2 rounded-lg border p-3 text-xs"
                >
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>{job.progress_message || "Generating audio…"}</span>
                </div>
            ))}

            {items.map((item) => (
                <article key={item.id} className="space-y-3 rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium">
                            {item.audio_overview?.title || "Audio overview"}
                        </p>
                        <ResearchVisibilityButton
                            outputId={item.id}
                            shared={item.is_shared}
                            canManage={item.capabilities.share}
                            onChanged={(shared) =>
                                setItems((current) =>
                                    current.map((candidate) =>
                                        candidate.id === item.id
                                            ? { ...candidate, is_shared: shared }
                                            : candidate,
                                    ),
                                )
                            }
                        />
                    </div>
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
                                <p className="mt-2 whitespace-pre-wrap">
                                    {item.audio_overview.transcript}
                                </p>
                            </details>
                        </>
                    )}
                </article>
            ))}
        </div>
    );
}
