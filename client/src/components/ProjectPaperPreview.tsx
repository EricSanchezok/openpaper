"use client";

import { reportClientIssue } from "@/lib/client-observability";
import type { CollectPaperResponse, PaperItem } from "@/lib/schema";
import { Button } from "./ui/button";
import { toast } from "sonner";
import { FilePlus2 } from "lucide-react";
import { PdfHighlighterViewer } from "./PdfHighlighterViewer";
import { useRouter } from "next/navigation";
import { fetchFromApi, getProjectPaperFileUrl } from "@/lib/api";
import { useState, useCallback } from "react";
import { CitePaperButton } from "./CitePaperButton";

interface ProjectPaperPreviewProps {
    paper: PaperItem;
    projectId: string;
    // Optional text to locate in the PDF (e.g. a clicked citation's reference).
    searchTerm?: string | null;
}

export function ProjectPaperPreview({ paper, projectId, searchTerm }: ProjectPaperPreviewProps) {
    const router = useRouter();
    const [isInLibrary, setIsInLibrary] = useState(Boolean(paper.in_library));

    const refreshPdfUrl = useCallback(async (): Promise<string | null> => {
        try {
            return await getProjectPaperFileUrl(projectId, paper.document_id);
        } catch (error) {
            reportClientIssue("Error refreshing PDF URL:", error);
            return null;
        }
    }, [projectId, paper.document_id]);

    const handleCollect = async () => {
        if (!projectId) {
            toast.error("Cannot duplicate", {
                description: "This paper is not part of a project.",
                richColors: true,
            });
            return;
        }

        const toastId = toast.loading("Adding paper to your library...");

        try {
            const requestBody = {
                source_project_id: projectId,
                document_id: paper.document_id,
            };

            const response = await fetchFromApi<CollectPaperResponse>('/library/papers', {
                method: 'POST',
                body: JSON.stringify(requestBody),
            });

            if (response.document_id) {
                toast.success("Paper added!", {
                    id: toastId,
                    description: "The paper is now in your personal library.",
                    richColors: true,
                });
                setIsInLibrary(true);
            } else {
                throw new Error("Invalid response from server.");
            }
        } catch (error) {
            reportClientIssue("Failed to add paper to library:", error);
            toast.error("Could not add paper", {
                id: toastId,
                description: "Could not duplicate the paper. Please try again.",
                richColors: true,
            });
        }
    };

    return (
        // Flush container — the reader panel / dialog hosting this provides the frame.
        <div className="bg-card transition-all duration-300 ease-in-out min-w-0 overflow-hidden h-full w-full">
            <div className="h-full flex flex-col">
                {/* Compact one-line header — the reader tab already shows the title */}
                <div className="flex items-center gap-2 border-b px-3 py-1.5">
                    <h3 className="min-w-0 flex-1 truncate text-sm font-medium" title={paper.title}>{paper.title}</h3>
                    <div className="flex shrink-0 items-center gap-1">
                        <CitePaperButton paper={[paper]} minimalist={true} />
                        {isInLibrary ? (
                            <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs" onClick={() => router.push(`/paper/${paper.document_id}?project_id=${projectId}`)}>
                                <FilePlus2 className="h-3.5 w-3.5 mr-1.5" />
                                Open
                            </Button>
                        ) : (
                            <Button variant="outline" size="sm" className="h-7 px-2.5 text-xs" onClick={handleCollect}>
                                <FilePlus2 className="h-3.5 w-3.5 mr-1.5" />
                                Add to My Library
                            </Button>
                        )}
                    </div>
                </div>
                <div className="flex-grow overflow-auto">
                    {paper.file_url && (
                        <PdfHighlighterViewer
                            pdfUrl={paper.file_url}
                            explicitSearchTerm={searchTerm || ""}
                            setUserMessageReferences={() => { }}
                            highlights={[]}
                            setHighlights={() => { }}
                            selectedText=""
                            setSelectedText={() => { }}
                            tooltipPosition={null}
                            setTooltipPosition={() => { }}
                            isAnnotating={false}
                            setIsAnnotating={() => { }}
                            isHighlightInteraction={false}
                            setIsHighlightInteraction={() => { }}
                            activeHighlight={null}
                            setActiveHighlight={() => { }}
                            addHighlight={() => { }}
                            removeHighlight={() => { }}
                            loadHighlights={async () => { }}
                            renderAnnotations={() => { }}
                            annotations={[]}
                            onRefreshUrl={refreshPdfUrl}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
