"use client";

import { BookStack, Folder } from "iconoir-react";
import { useFormatter, useTranslations } from "next-intl";

import { Button, keyboardFocusRing, Skeleton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";
import {
  ResearchComposer,
  type ResearchContext,
  type ReasoningLevel,
} from "./research-composer";
import type { ComposerValues } from "../schemas";
import type { UseFormReturn } from "react-hook-form";

type LibraryPaper = components["schemas"]["LibraryPaperResponse"];
type Project = components["schemas"]["ProjectResponse"];

function PaperPreview({ paper }: { paper: LibraryPaper }) {
  if (paper.preview_url) {
    return (
      // The URL is a short-lived, authenticated preview owned by the paper API.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        alt=""
        className="h-36 w-full rounded-[var(--radius-md)] border object-cover object-top"
        src={paper.preview_url}
      />
    );
  }
  return (
    <div className="border-line bg-subtle grid h-36 place-items-center overflow-hidden rounded-[var(--radius-md)] border">
      <div className="bg-surface border-line h-[150px] w-28 translate-y-2 rounded-sm border px-3 pt-3 shadow-sm">
        <div className="bg-muted mx-auto h-0.5 w-16 rounded-full" />
        <div className="bg-foreground mx-auto mt-2 h-1 w-20 rounded-full" />
        <div className="bg-foreground mx-auto mt-1 h-0.5 w-14 rounded-full" />
        <div className="bg-line mt-3 h-px" />
        <div className="mt-2 space-y-1">
          <div className="bg-muted h-0.5 rounded-full" />
          <div className="bg-muted h-0.5 rounded-full" />
          <div className="bg-muted h-0.5 w-4/5 rounded-full" />
        </div>
        <div className="bg-hover mt-3 flex h-12 items-end justify-center gap-1 rounded-sm px-3 pb-2">
          {[12, 21, 16, 27, 19].map((height, index) => (
            <span
              className="bg-secondary w-1 rounded-t-sm"
              key={index}
              style={{ height }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function PaperCard({ paper }: { paper: LibraryPaper }) {
  const t = useTranslations("Home.recents");
  const format = useFormatter();
  const title =
    paper.metadata_overrides.title ??
    paper.document.title ??
    paper.document.original_filename;
  const authors = paper.document.authors?.join(", ") || paper.document.journal;

  return (
    <article className="border-line bg-surface grid min-w-0 gap-2 rounded-[var(--radius-md)] border p-3">
      <PaperPreview paper={paper} />
      <div className="min-w-0">
        <h3 className="line-clamp-2 min-h-10 text-sm leading-5 font-medium">
          {title}
        </h3>
        <p className="text-secondary mt-1 truncate text-xs">
          {authors || paper.document.original_filename}
        </p>
      </div>
      <p className="text-muted text-xs">
        {t("opened", {
          relative: format.relativeTime(new Date(paper.last_accessed_at)),
        })}
      </p>
    </article>
  );
}

function ProjectRow({ project }: { project: Project }) {
  const t = useTranslations("Home.recents");
  const format = useFormatter();
  return (
    <article className="border-line bg-surface flex min-w-0 items-center gap-3 rounded-[var(--radius-md)] border p-3">
      <span className="bg-subtle grid size-9 shrink-0 place-items-center rounded-[var(--radius-md)]">
        <Icon glyph={Folder} size={20} tone="secondary" />
      </span>
      <div className="min-w-0">
        <h3 className="truncate text-sm font-medium">{project.title}</h3>
        <p className="text-secondary mt-0.5 truncate text-xs">
          {t("paperCount", { count: project.num_papers })} ·{" "}
          {t("updated", {
            relative: format.relativeTime(new Date(project.updated_at)),
          })}
        </p>
      </div>
    </article>
  );
}

type MobileRecentItem =
  | { kind: "paper"; id: string; title: string; updatedAt: string }
  | { kind: "project"; id: string; title: string; updatedAt: string };

function MobileRecentLauncher({
  papers,
  projects,
  loading,
  error,
  context,
  onContextChange,
  onRetry,
}: {
  papers: LibraryPaper[];
  projects: Project[];
  loading: boolean;
  error: boolean;
  context: ResearchContext;
  onContextChange: (context: ResearchContext) => void;
  onRetry: () => void;
}) {
  const t = useTranslations("Home.recents");
  const items: MobileRecentItem[] = [
    ...papers.map((paper): MobileRecentItem => ({
      kind: "paper",
      id: paper.document.document_id,
      title:
        paper.metadata_overrides.title ??
        paper.document.title ??
        paper.document.original_filename,
      updatedAt: paper.last_accessed_at,
    })),
    ...projects.map((project): MobileRecentItem => ({
      kind: "project",
      id: project.id,
      title: project.title,
      updatedAt: project.updated_at,
    })),
  ]
    .sort(
      (left, right) =>
        new Date(right.updatedAt).getTime() -
        new Date(left.updatedAt).getTime(),
    )
    .slice(0, 3);

  if (!loading && !error && items.length === 0) return null;

  return (
    <section className="mt-auto w-full max-w-[800px] pb-4 lg:hidden">
      <h2 className="text-secondary mb-3 px-1 text-sm font-medium">
        {t("continue")}
      </h2>
      {loading ? (
        <div aria-label={t("loading")} className="grid gap-2" role="status">
          {["first", "second", "third"].map((key, index) => (
            <Skeleton
              className={cn(
                "h-12 rounded-full",
                index === 0 ? "w-[88%]" : index === 1 ? "w-[72%]" : "w-[80%]",
              )}
              key={key}
            />
          ))}
        </div>
      ) : error && items.length === 0 ? (
        <div
          className="flex min-h-12 items-center justify-between gap-3 px-1"
          role="alert"
        >
          <p className="text-secondary text-sm">{t("loadError")}</p>
          <Button onClick={onRetry} size="sm" variant="secondary">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="grid justify-items-start gap-2">
          {items.map((item) => {
            const selected =
              context.kind === "selection" &&
              (item.kind === "paper"
                ? context.document_ids?.includes(item.id)
                : context.project_ids?.includes(item.id));
            const label = t(item.kind === "paper" ? "usePaper" : "useProject", {
              title: item.title,
            });
            return (
              <button
                aria-label={label}
                aria-pressed={selected}
                className={cn(
                  "bg-subtle hover:bg-hover flex min-h-12 max-w-full items-center gap-2.5 rounded-full px-4 text-left text-sm font-medium transition-colors motion-reduce:transition-none",
                  keyboardFocusRing,
                  selected && "bg-pressed",
                )}
                key={`${item.kind}:${item.id}`}
                onClick={() =>
                  onContextChange({
                    kind: "selection",
                    project_ids: item.kind === "project" ? [item.id] : [],
                    document_ids: item.kind === "paper" ? [item.id] : [],
                  })
                }
                type="button"
              >
                <Icon
                  glyph={item.kind === "paper" ? BookStack : Folder}
                  size={20}
                  tone="secondary"
                />
                <span className="truncate">{item.title}</span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

function RecentSection({
  title,
  loading,
  error,
  kind,
  onRetry,
  children,
  className,
}: {
  title: string;
  loading?: boolean;
  error?: boolean;
  kind: "papers" | "projects";
  onRetry: () => void;
  children?: React.ReactNode;
  className?: string;
}) {
  const t = useTranslations("Home.recents");

  if (!loading && !error && !children) return null;

  return (
    <section className={className}>
      <div className="mb-3 flex h-6 items-center">
        <h2 className="text-base font-medium">{title}</h2>
      </div>
      {loading ? (
        <div
          aria-label={title}
          className={cn("grid gap-3", kind === "papers" && "sm:grid-cols-2")}
          role="status"
        >
          {Array.from({ length: kind === "papers" ? 2 : 3 }).map((_, index) => (
            <Skeleton
              className={kind === "papers" ? "h-[262px]" : "h-[72px]"}
              key={index}
            />
          ))}
        </div>
      ) : error ? (
        <div
          className="border-line bg-surface flex min-h-[72px] items-center justify-between gap-4 rounded-[var(--radius-md)] border px-3 py-3"
          role="alert"
        >
          <p className="text-sm font-medium">{t("loadError")}</p>
          <Button onClick={onRetry} size="sm" variant="secondary">
            {t("retry")}
          </Button>
        </div>
      ) : (
        children
      )}
    </section>
  );
}

export function HomeDashboard({
  papers,
  projects,
  papersLoading,
  projectsLoading,
  papersError,
  projectsError,
  context,
  reasoningLevel,
  onContextChange,
  onReasoningLevelChange,
  onSubmit,
  onRetryPapers,
  onRetryProjects,
  composerForm,
  showComposer = true,
}: {
  papers: LibraryPaper[];
  projects: Project[];
  papersLoading?: boolean;
  projectsLoading?: boolean;
  papersError?: boolean;
  projectsError?: boolean;
  context: ResearchContext;
  reasoningLevel: ReasoningLevel;
  onContextChange: (context: ResearchContext) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSubmit: (message: string) => Promise<void>;
  onRetryPapers: () => void;
  onRetryProjects: () => void;
  composerForm?: UseFormReturn<ComposerValues>;
  showComposer?: boolean;
}) {
  const t = useTranslations("Home");
  const recentPapers = [...papers]
    .sort(
      (left, right) =>
        new Date(right.last_accessed_at).getTime() -
        new Date(left.last_accessed_at).getTime(),
    )
    .slice(0, 2);
  const recentProjects = [...projects]
    .sort(
      (left, right) =>
        new Date(right.updated_at).getTime() -
        new Date(left.updated_at).getTime(),
    )
    .slice(0, 3);
  const showPapers = papersLoading || papersError || recentPapers.length > 0;
  const showProjects =
    projectsLoading || projectsError || recentProjects.length > 0;
  const emptyWorkspace = !showPapers && !showProjects;

  return (
    <div
      className={cn(
        "mx-auto flex min-h-full w-full max-w-[1088px] flex-col px-3 sm:px-8 lg:px-16",
        emptyWorkspace
          ? "pb-3 lg:pt-[clamp(12rem,28vh,18rem)] lg:pb-16"
          : "pb-3 lg:py-16",
      )}
    >
      <section
        className={cn(
          "mx-auto flex w-full max-w-[800px] flex-col items-center gap-7 text-center lg:gap-6",
          !emptyWorkspace && "pt-[clamp(7rem,20vh,11rem)] lg:pt-0",
          emptyWorkspace &&
            "min-h-full flex-1 justify-between gap-0 lg:min-h-0 lg:flex-none lg:justify-start lg:gap-6",
        )}
      >
        <div
          className={cn(
            emptyWorkspace &&
              "flex flex-1 flex-col justify-center pb-[10vh] lg:block lg:pb-0",
          )}
        >
          <h1 className="text-[clamp(1.875rem,4vw,2.25rem)] leading-tight font-medium tracking-[-0.02em] text-balance [&:lang(zh-CN)]:leading-[1.28] [&:lang(zh-CN)]:tracking-normal">
            {t("hero.title")}
          </h1>
          <p className="text-secondary mx-auto mt-2 max-w-[40rem] text-base leading-[1.6] text-pretty lg:text-sm">
            {emptyWorkspace
              ? t("hero.emptyDescription")
              : t("hero.description")}
          </p>
        </div>
        {showComposer && (
          <ResearchComposer
            context={context}
            form={composerForm}
            onContextChange={onContextChange}
            onReasoningLevelChange={onReasoningLevelChange}
            onSubmit={onSubmit}
            papers={papers}
            projects={projects}
            reasoningLevel={reasoningLevel}
          />
        )}
      </section>
      {!emptyWorkspace && (
        <MobileRecentLauncher
          context={context}
          error={Boolean(papersError || projectsError)}
          loading={Boolean(papersLoading || projectsLoading)}
          onContextChange={onContextChange}
          onRetry={() => {
            onRetryPapers();
            onRetryProjects();
          }}
          papers={recentPapers}
          projects={recentProjects}
        />
      )}
      {!emptyWorkspace && (
        <div
          className={cn(
            "mt-10 hidden w-full gap-8 lg:mx-auto lg:mt-12 lg:grid",
            showPapers &&
              showProjects &&
              "lg:grid-cols-[minmax(0,600px)_minmax(280px,340px)] lg:gap-5",
            showPapers && !showProjects && "lg:max-w-[600px]",
            !showPapers && showProjects && "lg:max-w-[340px]",
          )}
        >
          <RecentSection
            className="min-w-0"
            error={papersError}
            kind="papers"
            loading={papersLoading}
            onRetry={onRetryPapers}
            title={t("recents.papers")}
          >
            {recentPapers.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {recentPapers.map((paper) => (
                  <PaperCard key={paper.document.document_id} paper={paper} />
                ))}
              </div>
            ) : undefined}
          </RecentSection>
          <RecentSection
            className="min-w-0"
            error={projectsError}
            kind="projects"
            loading={projectsLoading}
            onRetry={onRetryProjects}
            title={t("recents.projects")}
          >
            {recentProjects.length > 0 ? (
              <div className="grid gap-2">
                {recentProjects.map((project) => (
                  <ProjectRow key={project.id} project={project} />
                ))}
              </div>
            ) : undefined}
          </RecentSection>
        </div>
      )}
    </div>
  );
}
