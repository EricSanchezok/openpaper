"use client";

import type { Citation, PaperItem, ReferenceCitation } from "@/lib/schema";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";

export interface InlineCitation {
    key: string | number;
    reference: string;
}

type CitationValue = Citation | ReferenceCitation | InlineCitation;

interface CitationLinkProps {
    citationKey: string;
    messageIndex: number;
    onCitationClick: (key: string, messageIndex: number) => void;
    citations?: CitationValue[];
    papers?: PaperItem[];
}

function isExternalCitation(value: CitationValue): value is Extract<Citation, { kind: "external" }> {
    return "kind" in value && value.kind === "external";
}

export function CitationLink({
    citationKey,
    messageIndex,
    onCitationClick,
    citations,
    papers,
}: CitationLinkProps) {
    const citation = citations?.find(value =>
        "key" in value
            ? String(value.key) === citationKey
            : String(value.index) === citationKey,
    ) ?? null;
    const paper = citation && "document_id" in citation && papers
        ? papers.find(value => value.document_id === citation.document_id)
        : null;
    const externalUrl = citation && isExternalCitation(citation) ? citation.url : null;
    const sourceTitle = citation && "title" in citation && typeof citation.title === "string"
        ? citation.title
        : null;
    const referenceText = citation
        ? ("text" in citation ? citation.text : citation.reference)
        : null;

    const handleClick = (event: React.MouseEvent) => {
        event.preventDefault();
        if (externalUrl) {
            window.open(externalUrl, "_blank", "noopener,noreferrer");
            return;
        }
        onCitationClick(citationKey, messageIndex);
    };

    const marker = (
        <button
            type="button"
            className="rounded bg-secondary px-1 text-secondary-foreground"
            onClick={handleClick}
        >
            {citationKey}
        </button>
    );

    if (!citation) return marker;

    return (
        <HoverCard openDelay={100} closeDelay={100}>
            <HoverCardTrigger asChild>{marker}</HoverCardTrigger>
            <HoverCardContent className="w-80 bg-accent p-2 pt-3 shadow-md" sideOffset={0}>
                {(sourceTitle || paper?.title) && (
                    <p className="text-sm font-bold text-accent-foreground">
                        {sourceTitle || paper?.title}
                    </p>
                )}
                {referenceText && (
                    <p className="text-sm text-accent-foreground">{referenceText}</p>
                )}
                {externalUrl && (
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                        {new URL(externalUrl).hostname}
                    </p>
                )}
            </HoverCardContent>
        </HoverCard>
    );
}
