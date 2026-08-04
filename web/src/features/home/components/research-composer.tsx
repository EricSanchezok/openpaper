"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowUp, AtSign, Folder, Page, Xmark } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";

import {
  Button,
  Checkbox,
  IconButton,
  Popover,
  PopoverContent,
  PopoverTrigger,
  SearchField,
  Switch,
} from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import { composerSchema, type ComposerValues } from "../schemas";

type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];
export type ResearchContext =
  | components["schemas"]["LibraryPaperContext"]
  | components["schemas"]["SelectedPaperContext"];
export type ReasoningLevel = components["schemas"]["ReasoningLevel"];

function ContextPicker({
  context,
  papers,
  projects,
  onChange,
  open,
  onOpenChange,
  disabled,
}: {
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
  onChange: (context: ResearchContext) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("Home.context");
  const [query, setQuery] = React.useState("");
  const selectedProjects =
    context.kind === "selection" ? (context.project_ids ?? []) : [];
  const selectedDocuments =
    context.kind === "selection" ? (context.document_ids ?? []) : [];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleProjects = projects.filter((project) =>
    project.title.toLocaleLowerCase().includes(normalizedQuery),
  );
  const visiblePapers = papers.filter((paper) =>
    (paper.metadata_overrides.title ?? paper.document.title ?? "")
      .toLocaleLowerCase()
      .includes(normalizedQuery),
  );
  const selectionCount = selectedProjects.length + selectedDocuments.length;

  function updateSelection(
    field: "project_ids" | "document_ids",
    id: string,
    checked: boolean,
  ) {
    const selection =
      context.kind === "selection"
        ? context
        : { kind: "selection" as const, project_ids: [], document_ids: [] };
    const values = new Set(selection[field]);
    if (checked) values.add(id);
    else values.delete(id);
    onChange({ ...selection, [field]: [...values] });
  }

  return (
    <Popover onOpenChange={onOpenChange} open={open}>
      <PopoverTrigger asChild>
        <IconButton
          className="size-9 rounded-full"
          disabled={disabled}
          label={t("title")}
          variant="secondary"
        >
          <Icon glyph={AtSign} size={16} />
        </IconButton>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label={t("title")}
        className="flex max-h-[min(603px,calc(100dvh-9rem))] w-[min(460px,calc(100vw-1.5rem))] flex-col gap-3 overflow-hidden p-3"
        side="bottom"
      >
        <h2 className="text-base font-medium">{t("title")}</h2>
        <div className="bg-subtle flex items-center justify-between rounded-[var(--radius-md)] px-3 py-2.5">
          <label className="text-[13px] font-medium" htmlFor="entire-library">
            {t("entireLibrary")}
          </label>
          <Switch
            checked={context.kind === "library"}
            id="entire-library"
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? { kind: "library" }
                  : { kind: "selection", project_ids: [], document_ids: [] },
              )
            }
          />
        </div>
        <SearchField
          aria-label={t("search")}
          className="h-10"
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("search")}
          value={query}
        />
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
          {visibleProjects.length > 0 && (
            <section className="grid gap-2">
              <h3 className="text-secondary text-xs">{t("projects")}</h3>
              {visibleProjects.map((project) => {
                const checked = selectedProjects.includes(project.id);
                return (
                  <label
                    className={cn(
                      "hover:bg-hover flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] p-2",
                      checked && "bg-subtle",
                    )}
                    key={project.id}
                  >
                    <Checkbox
                      checked={checked}
                      disabled={context.kind === "library"}
                      onCheckedChange={(value) =>
                        updateSelection(
                          "project_ids",
                          project.id,
                          value === true,
                        )
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">
                        {project.title}
                      </span>
                      <span className="text-secondary mt-1 block text-xs">
                        {project.num_papers} · {project.num_conversations}
                      </span>
                    </span>
                  </label>
                );
              })}
            </section>
          )}
          {visiblePapers.length > 0 && (
            <section className="grid gap-2">
              <h3 className="text-secondary text-xs">{t("papers")}</h3>
              {visiblePapers.map((paper) => {
                const checked = selectedDocuments.includes(
                  paper.document.document_id,
                );
                const title =
                  paper.metadata_overrides.title ??
                  paper.document.title ??
                  paper.document.original_filename;
                const authors = paper.document.authors?.slice(0, 2).join(", ");
                return (
                  <label
                    className={cn(
                      "hover:bg-hover flex cursor-pointer items-center gap-3 rounded-[var(--radius-sm)] p-2",
                      checked && "bg-subtle",
                    )}
                    key={paper.document.document_id}
                  >
                    <Checkbox
                      checked={checked}
                      disabled={context.kind === "library"}
                      onCheckedChange={(value) =>
                        updateSelection(
                          "document_ids",
                          paper.document.document_id,
                          value === true,
                        )
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">
                        {title}
                      </span>
                      <span className="text-secondary mt-1 block truncate text-xs">
                        {authors ||
                          paper.document.journal ||
                          paper.document.original_filename}
                      </span>
                    </span>
                  </label>
                );
              })}
            </section>
          )}
          {visibleProjects.length === 0 && visiblePapers.length === 0 && (
            <p className="text-muted py-8 text-center text-sm">
              {t("noMatches")}
            </p>
          )}
        </div>
        <div className="border-line flex items-center gap-3 border-t pt-3">
          <span className="min-w-0 flex-1 text-[13px] font-medium">
            {context.kind === "library"
              ? t("librarySelected")
              : t("selected", { count: selectionCount })}
          </span>
          {context.kind === "selection" && selectionCount > 0 && (
            <Button
              className="min-h-9 px-2"
              onClick={() =>
                onChange({
                  kind: "selection",
                  project_ids: [],
                  document_ids: [],
                })
              }
              size="sm"
              variant="ghost"
            >
              {t("clear")}
            </Button>
          )}
          <Button
            className="min-h-9"
            onClick={() => onOpenChange(false)}
            size="sm"
          >
            {t("done")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function ResearchComposer({
  context,
  papers,
  projects,
  reasoningLevel,
  busy,
  compact,
  onContextChange,
  onReasoningLevelChange,
  onSubmit,
  onStop,
  unavailable,
}: {
  context: ResearchContext;
  papers: LibraryPaper[];
  projects: Project[];
  reasoningLevel: ReasoningLevel;
  busy?: boolean;
  compact?: boolean;
  onContextChange: (context: ResearchContext) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSubmit: (message: string) => Promise<void>;
  onStop?: () => void;
  unavailable?: boolean;
}) {
  const t = useTranslations("Home");
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const form = useForm<ComposerValues>({
    defaultValues: { message: "" },
    mode: "onChange",
    resolver: zodResolver(composerSchema),
  });
  const selectionCount =
    context.kind === "selection"
      ? (context.project_ids?.length ?? 0) + (context.document_ids?.length ?? 0)
      : 0;

  async function submit(values: ComposerValues) {
    await onSubmit(values.message.trim());
    form.reset();
  }

  return (
    <form
      className={cn(
        "border-line-strong bg-surface flex w-full flex-col gap-2 rounded-[var(--radius-xl)] border px-4 pt-3 pb-2 shadow-[0_4px_12px_var(--color-elevation-shadow)]",
        compact ? "max-w-[720px]" : "max-w-[680px]",
      )}
      onSubmit={form.handleSubmit(submit)}
    >
      <textarea
        aria-label={
          compact
            ? t("composer.followUpPlaceholder")
            : t("composer.placeholder")
        }
        className="placeholder:text-muted max-h-32 min-h-9 w-full resize-none bg-transparent py-1 text-sm leading-6 outline-none"
        disabled={busy || unavailable}
        onKeyDown={(event) => {
          if (event.key === "@") setPickerOpen(true);
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void form.handleSubmit(submit)();
          }
        }}
        placeholder={
          compact
            ? t("composer.followUpPlaceholder")
            : t("composer.placeholder")
        }
        rows={1}
        {...form.register("message")}
      />
      {context.kind === "library" || selectionCount > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          <span className="bg-subtle text-secondary inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs">
            <Icon
              glyph={context.kind === "library" ? Page : Folder}
              size={16}
              tone="secondary"
            />
            {context.kind === "library"
              ? t("context.librarySelected")
              : t("context.selectionSummary", { count: selectionCount })}
          </span>
        </div>
      ) : null}
      <div className="flex min-h-11 items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ContextPicker
            context={context}
            onChange={onContextChange}
            onOpenChange={setPickerOpen}
            open={pickerOpen}
            papers={papers}
            projects={projects}
            disabled={unavailable}
          />
          <div
            aria-label={t("composer.deepDescription")}
            className="border-line bg-surface flex h-8 items-center rounded-[var(--radius-sm)] border p-1"
            role="group"
          >
            {(["standard", "deep"] as const).map((level) => (
              <button
                aria-pressed={reasoningLevel === level}
                className={cn(
                  "text-secondary h-6 rounded-[var(--radius-xs)] px-2 text-xs font-medium",
                  reasoningLevel === level && "bg-subtle text-foreground",
                )}
                disabled={unavailable}
                key={level}
                onClick={() => onReasoningLevelChange(level)}
                type="button"
              >
                {t(`composer.${level}`)}
              </button>
            ))}
          </div>
        </div>
        {busy && onStop ? (
          <IconButton
            className="size-11"
            label={t("composer.stop")}
            onClick={onStop}
            variant="secondary"
          >
            <Icon glyph={Xmark} size={20} />
          </IconButton>
        ) : (
          <IconButton
            className="size-11"
            disabled={!form.formState.isValid || busy || unavailable}
            label={t("composer.submit")}
            type="submit"
          >
            <Icon glyph={ArrowUp} size={20} tone="inverse" />
          </IconButton>
        )}
      </div>
    </form>
  );
}
