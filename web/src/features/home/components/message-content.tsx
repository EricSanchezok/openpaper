import type { Components } from "react-markdown";
import { useTranslations } from "next-intl";
import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { keyboardFocusRing } from "@/components/ui";
import type { components as ApiComponents } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

type CitationAnnotation = ApiComponents["schemas"]["CitationAnnotation"];

export function annotateMarkdownContent(
  content: string,
  annotations: CitationAnnotation[] = [],
) {
  const insertions = new Map<number, Set<number>>();
  for (const annotation of annotations) {
    if (
      annotation.end_offset <= 0 ||
      annotation.end_offset > content.length ||
      annotation.start_offset < 0 ||
      annotation.start_offset >= annotation.end_offset
    ) {
      continue;
    }
    const keys = insertions.get(annotation.end_offset) ?? new Set<number>();
    annotation.source_keys.forEach((key) => keys.add(key));
    insertions.set(annotation.end_offset, keys);
  }
  return [...insertions.entries()]
    .sort(([left], [right]) => right - left)
    .reduce((result, [offset, keys]) => {
      const sourceKeys = [...keys].sort((left, right) => left - right);
      const marker = ` [${sourceKeys.join(",")}](#scholens-source=${sourceKeys.join(",")})`;
      return `${result.slice(0, offset)}${marker}${result.slice(offset)}`;
    }, content);
}

const baseComponents: Components = {
  h1: ({ children }) => (
    <h1 className="text-[1.375rem] leading-[1.875rem] font-semibold tracking-[-0.02em] lg:text-xl lg:leading-tight">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-[1.1875rem] leading-7 font-semibold tracking-[-0.015em] lg:text-lg lg:leading-snug">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-[1.0625rem] leading-[1.625rem] font-semibold lg:text-base lg:leading-snug">
      {children}
    </h3>
  ),
  p: ({ children }) => <p className="text-pretty">{children}</p>,
  ul: ({ children }) => (
    <ul className="marker:text-secondary list-disc space-y-2 pl-5 lg:pl-6">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="marker:text-secondary list-decimal space-y-2 pl-5 lg:pl-6">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="pl-1">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="border-line-strong text-secondary border-l pl-4">
      {children}
    </blockquote>
  ),
  code: ({ children, className }) => (
    <code
      className={
        className
          ? className
          : "bg-subtle rounded-[var(--radius-xs)] px-1.5 py-0.5 text-[0.9em] [overflow-wrap:anywhere]"
      }
    >
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="bg-subtle max-w-full overflow-x-auto overscroll-x-contain rounded-[var(--radius-lg)] p-4 text-sm leading-6">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="border-line max-w-full overflow-x-auto overscroll-x-contain rounded-[var(--radius-lg)] border">
      <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
        {children}
      </table>
    </div>
  ),
  th: ({ children }) => (
    <th className="bg-subtle border-line border-b px-3 py-2 font-medium">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-line border-b px-3 py-2 align-top last:border-b-0">
      {children}
    </td>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  hr: () => <hr className="border-line" />,
};

export function MessageContent({
  content,
  annotations,
  onCitationOpen,
}: {
  content: string;
  annotations?: CitationAnnotation[];
  onCitationOpen?: (sourceKeys: number[]) => void;
}) {
  const t = useTranslations("Home.conversation");
  const renderedContent = React.useMemo(
    () => annotateMarkdownContent(content, annotations),
    [annotations, content],
  );
  const components = React.useMemo<Components>(
    () => ({
      ...baseComponents,
      a: ({ children, href }) => {
        if (href?.startsWith("#scholens-source=")) {
          const sourceKeys = href
            .slice("#scholens-source=".length)
            .split(",")
            .map(Number)
            .filter(Number.isFinite);
          return (
            <button
              aria-label={t("openCitation", {
                keys: sourceKeys.join(", "),
              })}
              className={cn(
                "bg-subtle hover:bg-hover mx-0.5 inline-flex min-h-6 items-center rounded-full px-2 align-baseline text-xs font-medium",
                keyboardFocusRing,
              )}
              onClick={() => onCitationOpen?.(sourceKeys)}
              type="button"
            >
              {children}
            </button>
          );
        }
        return (
          <a
            className="decoration-line-strong hover:decoration-foreground [overflow-wrap:anywhere] underline underline-offset-4"
            href={href}
            rel="noreferrer"
            target="_blank"
          >
            {children}
          </a>
        );
      },
    }),
    [onCitationOpen, t],
  );
  return (
    <div className="max-w-[72ch] min-w-0 text-base leading-7 [overflow-wrap:anywhere] lg:text-sm lg:leading-7 [&>*+*]:mt-5 lg:[&>*+*]:mt-4">
      <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
        {renderedContent}
      </ReactMarkdown>
    </div>
  );
}
