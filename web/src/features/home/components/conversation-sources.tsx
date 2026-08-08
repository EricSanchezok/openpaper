"use client";

import { Page } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  keyboardFocusRing,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

export type ReferenceBundle = components["schemas"]["ReferenceBundle"];
type AnswerSource = NonNullable<ReferenceBundle["sources"]>[number];

export function isReferenceBundle(value: unknown): value is ReferenceBundle {
  return Boolean(
    value &&
    typeof value === "object" &&
    Array.isArray((value as { sources?: unknown }).sources),
  );
}

export function referenceSourceCount(references: unknown) {
  return isReferenceBundle(references) ? (references.sources?.length ?? 0) : 0;
}

function sourceTitle(source: AnswerSource, fallback: string): string {
  return "title" in source && source.title ? source.title : fallback;
}

function sourceMeta(source: AnswerSource) {
  if (source.kind === "external") {
    try {
      return new URL(source.url).hostname.replace(/^www\./, "");
    } catch {
      return source.url;
    }
  }
  if (source.kind === "document" && source.authors?.length) {
    return source.authors.slice(0, 3).join(", ");
  }
  return null;
}

function SourceRow({
  source,
  selected,
  fallbackTitle,
}: {
  source: AnswerSource;
  selected: boolean;
  fallbackTitle: string;
}) {
  const t = useTranslations("Home.conversation");
  const meta = sourceMeta(source);
  const content = (
    <>
      <span className="bg-subtle grid size-8 shrink-0 place-items-center rounded-full text-xs font-medium">
        {source.key}
      </span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 block text-sm font-medium">
          {sourceTitle(source, fallbackTitle)}
        </span>
        {meta && (
          <span className="text-caption text-muted mt-0.5 block truncate">
            {meta}
          </span>
        )}
        <span className="text-muted mt-1 line-clamp-2 block text-sm leading-5">
          {source.reference}
        </span>
      </span>
    </>
  );
  const className = cn(
    "border-line hover:bg-hover flex min-h-20 w-full items-start gap-3 border-b px-5 py-4 text-left transition-colors last:border-b-0 lg:px-6",
    source.kind === "external" && keyboardFocusRing,
    selected && "bg-subtle",
  );

  if (source.kind === "external") {
    return (
      <a
        aria-label={t("openSource", {
          title: sourceTitle(source, fallbackTitle),
        })}
        className={className}
        href={source.url}
        rel="noreferrer"
        target="_blank"
      >
        {content}
      </a>
    );
  }
  return <div className={className}>{content}</div>;
}

export function ConversationSources({
  references,
  open,
  onOpenChange,
  selectedSourceKey,
}: {
  references: unknown;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selectedSourceKey?: number;
}) {
  const t = useTranslations("Home.conversation");
  if (!isReferenceBundle(references) || !references.sources?.length) {
    return null;
  }
  const sources = references.sources;

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogTrigger asChild>
        <button
          className={cn(
            "bg-subtle hover:bg-hover ml-auto flex min-h-10 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors",
            keyboardFocusRing,
          )}
          type="button"
        >
          <Icon glyph={Page} size={16} tone="secondary" />
          {t("sourceSummary", { count: sources.length })}
        </button>
      </DialogTrigger>
      <DialogContent
        aria-describedby="conversation-sources-description"
        closeLabel={t("closeSources")}
        placement="responsive-bottom"
      >
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-[var(--color-border-strong)] lg:hidden" />
        <div className="border-line border-b px-5 pt-5 pr-14 pb-4 lg:px-6">
          <DialogTitle>
            {t("sourcePanelTitle", { count: sources.length })}
          </DialogTitle>
          <DialogDescription id="conversation-sources-description">
            {t("sourcePanelDescription")}
          </DialogDescription>
        </div>
        <div className="max-h-[calc(82dvh-7rem)] overflow-y-auto overscroll-contain lg:max-h-[min(65vh,34rem)]">
          {sources.map((source, index) => (
            <SourceRow
              fallbackTitle={t("reference", { number: index + 1 })}
              key={`${source.kind}-${source.key}`}
              selected={source.key === selectedSourceKey}
              source={source}
            />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
