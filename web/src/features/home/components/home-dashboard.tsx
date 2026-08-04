"use client";

import { Folder, Page } from "iconoir-react";
import { useFormatter, useTranslations } from "next-intl";

import { Button, Skeleton } from "@/components/ui";
import { Icon } from "@/design-system/icons/icon";
import type { components } from "@/lib/api/generated/schema";
import {
  ResearchComposer,
  type ResearchContext,
  type ReasoningLevel,
} from "./research-composer";

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

function RecentSection({
  title,
  loading,
  error,
  emptyTitle,
  emptyDescription,
  onRetry,
  children,
  className,
}: {
  title: string;
  loading?: boolean;
  error?: boolean;
  emptyTitle: string;
  emptyDescription: string;
  onRetry: () => void;
  children?: React.ReactNode;
  className?: string;
}) {
  const t = useTranslations("Home.recents");
  return (
    <section className={className}>
      <div className="mb-3 flex h-6 items-center justify-between">
        <h2 className="text-base font-medium">{title}</h2>
        <button
          aria-disabled
          className="text-secondary cursor-not-allowed text-xs"
          title={t("viewAll")}
          type="button"
        >
          {t("viewAll")}
        </button>
      </div>
      {loading ? (
        <div aria-label={title} className="grid gap-3" role="status">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : error ? (
        <div
          className="border-line bg-surface grid min-h-40 place-items-center rounded-[var(--radius-md)] border p-6 text-center"
          role="alert"
        >
          <div>
            <p className="text-sm font-medium">{t("loadError")}</p>
            <Button
              className="mt-3"
              onClick={onRetry}
              size="sm"
              variant="secondary"
            >
              {t("retry")}
            </Button>
          </div>
        </div>
      ) : children ? (
        children
      ) : (
        <div className="border-line bg-surface grid min-h-40 place-items-center rounded-[var(--radius-md)] border p-6 text-center">
          <div>
            <span className="bg-subtle mx-auto grid size-10 place-items-center rounded-[var(--radius-md)]">
              <Icon glyph={Page} size={20} tone="secondary" />
            </span>
            <p className="mt-3 text-sm font-medium">{emptyTitle}</p>
            <p className="text-muted mt-1 text-xs">{emptyDescription}</p>
          </div>
        </div>
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

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[1088px] flex-col px-4 py-8 sm:px-8 lg:px-16 lg:py-16">
      <section className="mx-auto flex w-full max-w-[720px] flex-col items-center gap-5 text-center">
        <div>
          <h1 className="text-[clamp(1.75rem,4vw,2.25rem)] leading-tight font-medium tracking-[-0.025em]">
            {t("hero.title")}
          </h1>
          <p className="text-secondary mt-3 text-sm">{t("hero.description")}</p>
        </div>
        <ResearchComposer
          context={context}
          onContextChange={onContextChange}
          onReasoningLevelChange={onReasoningLevelChange}
          onSubmit={onSubmit}
          papers={papers}
          projects={projects}
          reasoningLevel={reasoningLevel}
        />
      </section>
      <div className="mt-12 grid gap-8 lg:grid-cols-[minmax(0,600px)_minmax(280px,340px)] lg:gap-5">
        <RecentSection
          className="min-w-0"
          emptyDescription={t("recents.noPapersDescription")}
          emptyTitle={t("recents.noPapersTitle")}
          error={papersError}
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
          emptyDescription={t("recents.noProjectsDescription")}
          emptyTitle={t("recents.noProjectsTitle")}
          error={projectsError}
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
    </div>
  );
}
