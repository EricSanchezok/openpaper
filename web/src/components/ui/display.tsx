import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "border-line bg-subtle text-secondary",
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

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(({ className, orientation = "horizontal", ...props }, ref) => (
  <SeparatorPrimitive.Root
    className={cn(
      "bg-line shrink-0",
      orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
      className,
    )}
    orientation={orientation}
    ref={ref}
    {...props}
  />
));
Separator.displayName = SeparatorPrimitive.Root.displayName;

export function Progress({
  value = 0,
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>) {
  const percentage = value ?? 0;
  return (
    <ProgressPrimitive.Root
      className={cn(
        "bg-secondary-action h-1.5 overflow-hidden rounded-full",
        className,
      )}
      value={percentage}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className="bg-primary h-full transition-transform"
        style={{ transform: `translateX(-${100 - percentage}%)` }}
      />
    </ProgressPrimitive.Root>
  );
}

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        "bg-secondary-action animate-pulse rounded-[var(--radius-md)]",
        className,
      )}
      {...props}
    />
  );
}
