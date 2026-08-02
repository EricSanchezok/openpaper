import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

const alertVariants = cva(
  "grid gap-1 rounded-[var(--radius-lg)] border px-4 py-3 text-sm",
  {
    variants: {
      tone: {
        neutral: "border-line bg-subtle text-foreground",
        info: "border-[var(--color-info-border)] bg-state-info-bg text-info",
        success:
          "border-[var(--color-success-border)] bg-state-success-bg text-success",
        warning:
          "border-[var(--color-warning-border)] bg-state-warning-bg text-warning",
        danger:
          "border-[var(--color-danger-border)] bg-state-danger-bg text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Alert({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return (
    <div
      className={cn(alertVariants({ tone }), className)}
      role={tone === "danger" ? "alert" : "status"}
      {...props}
    />
  );
}

export function AlertTitle(props: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className="font-medium" {...props} />;
}

export function AlertDescription(
  props: React.HTMLAttributes<HTMLParagraphElement>,
) {
  return <p className="text-sm opacity-90" {...props} />;
}
