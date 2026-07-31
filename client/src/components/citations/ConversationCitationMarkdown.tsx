"use client";

import { useMemo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { PluggableList } from "unified";

import { CopyableTable } from "@/components/AnimatedMarkdown";
import { CitationLink } from "@/components/citations/CitationLink";
import type { CitationAnnotation, PaperItem, Reference } from "@/lib/schema";

interface PositionPoint {
    offset?: number;
}

interface MarkdownNode {
    type: string;
    value?: string;
    children?: MarkdownNode[];
    position?: { start: PositionPoint; end: PositionPoint };
    data?: Record<string, unknown>;
}

function codePointToUtf16Offsets(content: string): number[] {
    const offsets = [0];
    let utf16Offset = 0;
    for (const character of content) {
        utf16Offset += character.length;
        offsets.push(utf16Offset);
    }
    return offsets;
}

function citationNode(annotation: CitationAnnotation): MarkdownNode {
    return {
        type: "citationAnnotation",
        data: {
            hName: "sup",
            hProperties: {
                "data-citation-keys": annotation.source_keys.join(","),
                "data-citation-start": String(annotation.start_offset),
                "data-citation-end": String(annotation.end_offset),
            },
        },
        children: [],
    };
}

function insertAtOffset(parent: MarkdownNode, offset: number, node: MarkdownNode): boolean {
    if (!parent.children) return false;
    for (let index = 0; index < parent.children.length; index += 1) {
        const child = parent.children[index];
        if (insertAtOffset(child, offset, node)) return true;
        if (child.position?.end.offset === offset) {
            parent.children.splice(index + 1, 0, node);
            return true;
        }
        const start = child.position?.start.offset;
        const end = child.position?.end.offset;
        if (
            child.type === "text"
            && typeof child.value === "string"
            && start !== undefined
            && end !== undefined
            && start < offset
            && offset < end
        ) {
            const split = offset - start;
            parent.children.splice(
                index,
                1,
                { ...child, value: child.value.slice(0, split), position: undefined },
                node,
                { ...child, value: child.value.slice(split), position: undefined },
            );
            return true;
        }
    }
    return false;
}

function citationAnnotationsPlugin(content: string, annotations: CitationAnnotation[]) {
    const codePointOffsets = codePointToUtf16Offsets(content);
    const grouped = new Map<number, CitationAnnotation>();
    for (const annotation of annotations) {
        if (
            annotation.start_offset < 0
            || annotation.start_offset >= annotation.end_offset
            || annotation.end_offset >= codePointOffsets.length
        ) continue;
        const existing = grouped.get(annotation.end_offset);
        grouped.set(annotation.end_offset, {
            start_offset: existing
                ? Math.min(existing.start_offset, annotation.start_offset)
                : annotation.start_offset,
            end_offset: annotation.end_offset,
            source_keys: Array.from(new Set([
                ...(existing?.source_keys ?? []),
                ...annotation.source_keys,
            ])),
        });
    }
    const ordered = Array.from(grouped.values()).sort(
        (left, right) => right.end_offset - left.end_offset,
    );
    return () => (tree: MarkdownNode) => {
        for (const annotation of ordered) {
            insertAtOffset(
                tree,
                codePointOffsets[annotation.end_offset],
                citationNode(annotation),
            );
        }
    };
}

interface ConversationCitationMarkdownProps {
    content: string;
    references?: Reference;
    papers?: PaperItem[];
    messageIndex: number;
    onCitationClick: (key: string, messageIndex: number) => void;
}

export function ConversationCitationMarkdown({
    content,
    references,
    papers,
    messageIndex,
    onCitationClick,
}: ConversationCitationMarkdownProps) {
    const remarkPlugins = useMemo<PluggableList>(() => [
        [remarkMath, { singleDollarTextMath: false }],
        remarkGfm,
        citationAnnotationsPlugin(content, references?.annotations ?? []),
    ] as PluggableList, [content, references?.annotations]);
    const sources = references?.sources ?? [];

    return (
        <Markdown
            remarkPlugins={remarkPlugins}
            rehypePlugins={[rehypeKatex]}
            components={{
                table: CopyableTable,
                sup: ({ children, ...props }) => {
                    const keys = String(props["data-citation-keys" as keyof typeof props] ?? "")
                        .split(",")
                        .filter(Boolean);
                    if (!keys.length) return <sup {...props}>{children}</sup>;
                    return (
                        <sup className="ml-0.5 inline-flex gap-0.5 align-super text-xs">
                            {keys.map(key => (
                                <CitationLink
                                    key={key}
                                    citationKey={key}
                                    messageIndex={messageIndex}
                                    onCitationClick={onCitationClick}
                                    citations={sources}
                                    papers={papers}
                                />
                            ))}
                        </sup>
                    );
                },
            }}
        >
            {content}
        </Markdown>
    );
}
