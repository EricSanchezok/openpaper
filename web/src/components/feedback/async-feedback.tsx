"use client";

import {
  Database,
  RefreshDouble,
  WarningTriangle,
  WifiOff,
} from "iconoir-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/display";
import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";

export type AsyncFeedbackState =
  "loading" | "empty" | "error" | "offline" | "retrying";
export type AsyncFeedbackPresentation = "inline" | "block" | "overlay";

type FeedbackAction = { label: string; onClick: () => void };

const stateDefaults: Record<
  Exclude<AsyncFeedbackState, "loading" | "retrying">,
  { title: string; description: string; icon: typeof Database }
> = {
  empty: {
    title: "Nothing here yet",
    description: "Content will appear here when it becomes available.",
    icon: Database,
  },
  error: {
    title: "Could not load this content",
    description: "Try again. If the problem continues, come back later.",
    icon: WarningTriangle,
  },
  offline: {
    title: "You are offline",
    description: "Reconnect to continue.",
    icon: WifiOff,
  },
};

export function LoadingState({
  presentation = "block",
  label = "Loading",
}: {
  presentation?: AsyncFeedbackPresentation;
  label?: string;
}) {
  if (presentation === "inline")
    return (
      <span className="text-muted inline-flex items-center gap-2 text-sm">
        <span className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
        {label}
      </span>
    );
  return (
    <div aria-label={label} className="grid gap-3" role="status">
      <Skeleton className="h-4 w-2/5" />
      <Skeleton className="h-4 w-4/5" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}

export function RetryAction({
  action,
  retrying,
}: {
  action: FeedbackAction;
  retrying?: boolean;
}) {
  return (
    <Button
      loading={retrying}
      onClick={action.onClick}
      size="sm"
      variant="secondary"
    >
      <Icon glyph={RefreshDouble} size={16} />
      {action.label}
    </Button>
  );
}

export function AsyncFeedback({
  state,
  presentation = "block",
  title,
  description,
  action,
  icon,
}: {
  state: AsyncFeedbackState;
  presentation?: AsyncFeedbackPresentation;
  title?: string;
  description?: string;
  action?: FeedbackAction;
  icon?: typeof Database;
}) {
  if (state === "loading") return <LoadingState presentation={presentation} />;
  if (state === "retrying")
    return <LoadingState label="Trying again" presentation={presentation} />;
  const defaults = stateDefaults[state];
  const Glyph = icon ?? defaults.icon;
  return (
    <section
      className={cn(
        "relative text-center",
        presentation === "inline" && "flex items-center gap-3 text-left",
        presentation === "block" &&
          "border-line bg-surface grid min-h-48 place-items-center rounded-[var(--radius-lg)] border p-8",
        presentation === "overlay" &&
          "absolute inset-0 z-10 grid place-items-center bg-[color-mix(in_srgb,var(--color-bg-canvas)_86%,transparent)] p-8 backdrop-blur-sm",
      )}
      role={state === "error" || state === "offline" ? "alert" : "status"}
    >
      <div
        className={cn(
          "grid justify-items-center gap-3",
          presentation === "inline" &&
            "grid-flow-col items-center justify-items-start",
        )}
      >
        <div className="bg-subtle grid size-10 place-items-center rounded-[var(--radius-lg)]">
          <Icon glyph={Glyph} size={20} tone="secondary" />
        </div>
        <div>
          <h2 className="text-sm font-medium">{title ?? defaults.title}</h2>
          <p className="text-muted mt-1 max-w-md text-sm">
            {description ?? defaults.description}
          </p>
        </div>
        {action && <RetryAction action={action} />}
      </div>
    </section>
  );
}

export const EmptyState = (
  props: Omit<React.ComponentProps<typeof AsyncFeedback>, "state">,
) => <AsyncFeedback state="empty" {...props} />;
export const ErrorState = (
  props: Omit<React.ComponentProps<typeof AsyncFeedback>, "state">,
) => <AsyncFeedback state="error" {...props} />;

export function AsyncBoundary<T>({
  data,
  loading,
  error,
  offline,
  retrying,
  retry,
  empty,
  children,
}: {
  data: T | undefined;
  loading?: boolean;
  error?: unknown;
  offline?: boolean;
  retrying?: boolean;
  retry?: () => void;
  empty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
}) {
  if (offline)
    return (
      <AsyncFeedback
        action={retry ? { label: "Retry", onClick: retry } : undefined}
        state="offline"
      />
    );
  if (error)
    return (
      <AsyncFeedback
        action={retry ? { label: "Try again", onClick: retry } : undefined}
        state="error"
      />
    );
  if (loading || data === undefined)
    return <AsyncFeedback state={retrying ? "retrying" : "loading"} />;
  if (empty?.(data)) return <AsyncFeedback state="empty" />;
  return <>{children(data)}</>;
}
