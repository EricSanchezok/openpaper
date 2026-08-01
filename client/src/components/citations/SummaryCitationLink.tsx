import { reportClientIssue } from "@/lib/client-observability";
import { Citation, ReferenceCitation } from "@/lib/schema";
import { HTMLAttributes, ReactNode, createElement, Children } from "react";
import { PaperItem } from "@/lib/schema";
import { CitationLink, InlineCitation } from "@/components/citations/CitationLink";

interface SummaryCitationLinkProps extends HTMLAttributes<HTMLElement> {
    children?: ReactNode;
    handleCitationClick: (key: string, messageIndex: number) => void;
    messageIndex: number;
    node?: {
        tagName?: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        properties?: Record<string, any>;
    };
    className?: string;
    citations?: (Citation | ReferenceCitation | InlineCitation)[];
    papers?: PaperItem[];
}

export default function SummaryCitationLink({ children, handleCitationClick, messageIndex, className, papers, ...props }: SummaryCitationLinkProps) {
    // Create a clone of props to avoid mutating the original
    const elementProps = {
        ...props,
        className: `${className || ''}`
    };

    return createElement(
        // Use the original component type from props
        props.node?.tagName || 'span',
        elementProps,
        Children.map(children, (child) => {
            // If the child is a string, process it for citations
            if (typeof child === 'string') {
                // Updated regex to match both single citations [^1] and multiple citations [^10, ^14]
                const citationRegex = /\[\^(\d+(?:[a-zA-Z]*)?(?:,\s*\^?\d+(?:[a-zA-Z]*)?)*)\]/g;

                if (citationRegex.test(child)) {
                    // Reset regex state
                    citationRegex.lastIndex = 0;
                    // Create a React element array from the string with replaced citations
                    const parts: React.ReactNode[] = [];
                    let lastIndex = 0;
                    let match: RegExpExecArray | null = null;

                    while ((match = citationRegex.exec(child)) !== null) {

                        if (!match || match.index === undefined) {
                            reportClientIssue('Invalid match found in citation regex:', match);
                            continue; // Skip invalid matches
                        }

                        // Add text before the citation
                        if (match.index > lastIndex) {
                            parts.push(child.substring(lastIndex, match.index));
                        }

                        // Parse multiple citations from the match
                        const citationsStr = match[1];
                        const individualCitations = citationsStr.split(',').map(c => c.trim().replace(/^\^?/, ''));

                        // Create a container for multiple citations
                        parts.push(
                            <span key={`citations-${match.index}`} className="inline-flex gap-1">
                                {individualCitations.map((citationKey, index) => (
                                    <CitationLink
                                        key={`citation-${citationKey}-${index}`}
                                        citationKey={citationKey}
                                        messageIndex={messageIndex}
                                        onCitationClick={handleCitationClick}
                                        citations={props.citations}
                                        papers={papers}
                                    />
                                ))}
                            </span>
                        );

                        // Update lastIndex to continue after current match
                        lastIndex = match.index + match[0].length;
                    }

                    // Add remaining text
                    if (lastIndex < child.length) {
                        parts.push(child.substring(lastIndex));
                    }

                    return <>{parts}</>;
                }
                return child;
            }
            return child;
        })
    );
};
