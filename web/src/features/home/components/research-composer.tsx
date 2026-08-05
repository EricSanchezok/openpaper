"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowUp, AtSign, Folder, Xmark } from "iconoir-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm, type UseFormReturn } from "react-hook-form";

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

export function useResearchComposerForm() {
  return useForm<ComposerValues>({
    defaultValues: { message: "" },
    mode: "onChange",
    resolver: zodResolver(composerSchema),
  });
}

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
          className="size-12 rounded-full lg:size-9"
          disabled={disabled}
          label={t("title")}
          variant="secondary"
        >
          <Icon glyph={AtSign} size={20} />
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
          <label className="text-ui font-medium" htmlFor="entire-library">
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
                      <span className="text-ui block truncate font-medium">
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
                      <span className="text-ui block truncate font-medium">
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
          <span className="text-ui min-w-0 flex-1 font-medium">
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

function ReasoningSelector({
  className,
  disabled,
  onChange,
  value,
}: {
  className?: string;
  disabled?: boolean;
  onChange: (level: ReasoningLevel) => void;
  value: ReasoningLevel;
}) {
  const t = useTranslations("Home");
  return (
    <div
      aria-label={t("composer.deepDescription")}
      className={cn(
        "border-line bg-surface flex h-11 items-center overflow-hidden rounded-[var(--radius-md)] border lg:h-8 lg:rounded-[var(--radius-sm)] lg:p-1",
        className,
      )}
      role="group"
    >
      {(["standard", "deep"] as const).map((level) => (
        <button
          aria-pressed={value === level}
          className={cn(
            "text-secondary h-11 rounded-[var(--radius-sm)] px-3 text-sm font-medium lg:h-6 lg:rounded-[var(--radius-xs)] lg:px-2 lg:text-xs",
            value === level && "bg-subtle text-foreground",
          )}
          disabled={disabled}
          key={level}
          onClick={() => onChange(level)}
          type="button"
        >
          {t(`composer.${level}`)}
        </button>
      ))}
    </div>
  );
}

export function ResearchComposer({
  form,
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
  form?: UseFormReturn<ComposerValues>;
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
  const internalForm = useResearchComposerForm();
  const composerForm = form ?? internalForm;
  const selectionCount =
    context.kind === "selection"
      ? (context.project_ids?.length ?? 0) + (context.document_ids?.length ?? 0)
      : 0;

  async function submit(values: ComposerValues) {
    await onSubmit(values.message.trim());
    composerForm.reset();
  }

  return (
    <form
      className={cn(
        "border-line bg-surface focus-within:border-control shadow-composer lg:shadow-raised grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-end gap-2 rounded-[var(--radius-xl)] border p-2.5 transition-colors lg:px-4",
        compact
          ? "max-w-[720px] lg:gap-3 lg:pt-4 lg:pb-2"
          : "max-w-[760px] lg:gap-4 lg:pt-4 lg:pb-3",
      )}
      onSubmit={composerForm.handleSubmit(submit)}
    >
      <textarea
        aria-label={
          compact
            ? t("composer.followUpPlaceholder")
            : t("composer.placeholder")
        }
        className={cn(
          "placeholder:text-muted col-start-2 row-start-1 [field-sizing:content] max-h-32 min-h-12 w-full resize-none self-center overflow-y-auto bg-transparent py-3 text-[17px] leading-6 outline-none focus-visible:outline-none lg:col-span-3 lg:col-start-1 lg:py-0 lg:text-sm",
          compact
            ? "lg:min-h-[22px] lg:leading-[22px]"
            : "lg:min-h-7 lg:leading-7",
        )}
        data-focus-delegate
        disabled={busy || unavailable}
        onKeyDown={(event) => {
          if (event.key === "@") setPickerOpen(true);
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            void composerForm.handleSubmit(submit)();
          }
        }}
        placeholder={
          compact
            ? t("composer.followUpPlaceholder")
            : t("composer.placeholder")
        }
        rows={1}
        {...composerForm.register("message")}
      />
      {context.kind === "selection" && selectionCount > 0 ? (
        <div className="col-span-3 row-start-2 flex flex-wrap gap-1.5">
          <span className="bg-subtle text-secondary inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm lg:text-xs">
            <Icon glyph={Folder} size={16} tone="secondary" />
            {t("context.selectionSummary", { count: selectionCount })}
          </span>
        </div>
      ) : null}
      <div className="col-start-1 row-start-1 lg:row-start-3">
        <ContextPicker
          context={context}
          disabled={unavailable}
          onChange={onContextChange}
          onOpenChange={setPickerOpen}
          open={pickerOpen}
          papers={papers}
          projects={projects}
        />
      </div>
      <ReasoningSelector
        className="hidden lg:col-start-2 lg:row-start-3 lg:flex lg:justify-self-start"
        disabled={unavailable}
        onChange={onReasoningLevelChange}
        value={reasoningLevel}
      />
      {busy && onStop ? (
        <IconButton
          className="col-start-3 row-start-1 size-12 lg:row-start-3 lg:size-11"
          label={t("composer.stop")}
          onClick={onStop}
          variant="secondary"
        >
          <Icon glyph={Xmark} size={20} />
        </IconButton>
      ) : (
        <IconButton
          className="col-start-3 row-start-1 size-12 lg:row-start-3 lg:size-11"
          disabled={!composerForm.formState.isValid || busy || unavailable}
          label={t("composer.submit")}
          type="submit"
        >
          <Icon glyph={ArrowUp} size={24} tone="inverse" />
        </IconButton>
      )}
    </form>
  );
}
