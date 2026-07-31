import { useEffect, useState } from "react";

import type { Citation, DocumentCitation, ExternalCitation, PaperItem } from "@/lib/schema";
import { groupConsecutiveNumbers } from "@/lib/utils";

interface ReferenceCardsProps {
    citations: Citation[];
    papers: PaperItem[];
    messageId?: string;
    messageIndex: number;
    highlightedPaper: string | null;
    onHighlightClear: () => void;
    onPaperClick?: (paper: PaperItem) => void;
}

function domain(url: string): string {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

export default function ReferenceCards({
    citations,
    papers,
    messageId,
    messageIndex,
    highlightedPaper,
    onHighlightClear,
    onPaperClick,
}: ReferenceCardsProps) {
    const [expanded, setExpanded] = useState<string | null>(null);

    useEffect(() => {
        if (!highlightedPaper) return;
        const timer = setTimeout(onHighlightClear, 1500);
        return () => clearTimeout(timer);
    }, [highlightedPaper, onHighlightClear]);

    const documents = citations
        .filter((citation): citation is DocumentCitation => citation.kind === "document")
        .reduce<Record<string, DocumentCitation[]>>((groups, citation) => {
            (groups[citation.document_id] ??= []).push(citation);
            return groups;
        }, {});
    const external = citations.filter(
        (citation): citation is ExternalCitation => citation.kind === "external",
    );
    const userReferences = citations.filter(citation => citation.kind === "user");

    return (
        <div className="mt-3 space-y-3">
            {Object.entries(documents).map(([documentId, documentCitations]) => {
                const paper = papers.find(item => item.document_id === documentId);
                const title = documentCitations[0].title || paper?.title || "Document source";
                const authors = documentCitations[0].authors.length
                    ? documentCitations[0].authors
                    : paper?.authors || [];
                const cardKey = `document:${documentId}`;
                const isExpanded = expanded === cardKey;
                const cardId = `${messageId || messageIndex}-reference-${documentId}`;
                return (
                    <div
                        key={cardKey}
                        id={cardId}
                        className={`space-y-3 rounded-lg border p-4 transition-colors ${
                            highlightedPaper === documentId
                                ? "border-blue-200 bg-blue-50/50 dark:border-blue-800 dark:bg-blue-900/10"
                                : "border-border bg-card"
                        }`}
                    >
                        <div className={`flex items-start gap-3 ${isExpanded ? "border-b pb-3" : ""}`}>
                            <button
                                type="button"
                                className="shrink-0 rounded-lg bg-secondary px-2 py-1 text-xs font-bold text-muted-foreground"
                                onClick={() => setExpanded(isExpanded ? null : cardKey)}
                            >
                                {groupConsecutiveNumbers(documentCitations.map(item => item.key))}
                            </button>
                            <button
                                type="button"
                                className="min-w-0 flex-1 text-left transition-opacity hover:opacity-80"
                                onClick={() => paper && onPaperClick?.(paper)}
                            >
                                <p className="m-0 line-clamp-2 text-sm font-medium">{title}</p>
                                {authors.length > 0 && (
                                    <p className="mt-1 text-xs text-muted-foreground">
                                        {authors.slice(0, 5).join(", ")}{authors.length > 5 ? " et al." : ""}
                                    </p>
                                )}
                            </button>
                        </div>
                        {isExpanded && (
                            <div className="space-y-3">
                                {documentCitations.map(citation => (
                                    <div key={citation.key} className="flex gap-2.5">
                                        <span className="shrink-0 font-mono text-xs font-semibold text-blue-600 dark:text-blue-400">
                                            [{citation.key}]
                                        </span>
                                        <div className="text-sm leading-relaxed text-foreground/90">
                                            {citation.reference}
                                            {citation.locator?.page_number != null && (
                                                <span className="ml-2 text-xs text-muted-foreground">
                                                    p. {String(citation.locator.page_number)}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                );
            })}

            {external.map(citation => (
                <a
                    key={`external:${citation.key}`}
                    href={citation.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-lg border border-border bg-card p-4 no-underline transition-colors hover:bg-muted/40"
                >
                    <div className="flex items-start gap-3">
                        <span className="rounded-lg bg-secondary px-2 py-1 font-mono text-xs font-semibold text-muted-foreground">
                            {citation.key}
                        </span>
                        <div className="min-w-0">
                            <p className="m-0 line-clamp-2 text-sm font-medium text-foreground">
                                {citation.title || domain(citation.url)}
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">{domain(citation.url)}</p>
                            {citation.reference && (
                                <p className="mt-2 line-clamp-4 text-sm leading-relaxed text-foreground/80">
                                    {citation.reference}
                                </p>
                            )}
                        </div>
                    </div>
                </a>
            ))}

            {userReferences.map(citation => (
                <div key={`user:${citation.key}`} className="rounded-lg border border-border bg-card p-3 text-sm">
                    {citation.reference}
                </div>
            ))}
        </div>
    );
}
