"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

export const buttonVariants = cva(
  "inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-[var(--radius-md)] border text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:pointer-events-none disabled:border-transparent disabled:bg-[var(--color-action-disabled-bg)] disabled:text-disabled aria-busy:cursor-wait",
  {
    variants: {
      variant: {
        primary:
          "border-primary bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-hover",
        secondary:
          "border-line bg-surface text-foreground hover:bg-hover active:bg-pressed",
        ghost:
          "border-transparent bg-transparent text-foreground hover:bg-hover active:bg-pressed",
        danger:
          "border-[var(--color-danger-border)] bg-state-danger-bg text-danger hover:brightness-95",
      },
      size: {
        sm: "h-11 px-3 sm:h-9",
        md: "h-11 px-4",
        icon: "size-11 p-0",
        "icon-sm": "size-11 p-0 sm:size-9",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    loading?: boolean;
  };

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      asChild,
      className,
      loading,
      children,
      disabled,
      onClick,
      tabIndex,
      variant,
      size,
      ...props
    },
    ref,
  ) => {
    const classes = cn(buttonVariants({ variant, size }), className);
    if (asChild) {
      return (
        <Slot
          aria-disabled={disabled || loading || undefined}
          aria-busy={loading || undefined}
          className={classes}
          data-disabled={disabled || loading || undefined}
          onClick={(event) => {
            if (disabled || loading) {
              event.preventDefault();
              event.stopPropagation();
              return;
            }
            onClick?.(event as React.MouseEvent<HTMLButtonElement>);
          }}
          ref={ref}
          tabIndex={disabled || loading ? -1 : tabIndex}
          {...props}
        >
          {children}
        </Slot>
      );
    }
    return (
      <button
        aria-busy={loading || undefined}
        className={classes}
        disabled={disabled || loading}
        onClick={onClick}
        ref={ref}
        tabIndex={tabIndex}
        {...props}
      >
        {loading && (
          <span
            aria-hidden
            className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export const IconButton = React.forwardRef<
  HTMLButtonElement,
  Omit<ButtonProps, "size"> & { label: string }
>(({ label, ...props }, ref) => (
  <Button aria-label={label} ref={ref} size="icon" {...props} />
));
IconButton.displayName = "IconButton";

export function LinkButton({
  className,
  disabled,
  variant,
  size,
  onClick,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement> &
  VariantProps<typeof buttonVariants> & { disabled?: boolean }) {
  return (
    <a
      aria-disabled={disabled || undefined}
      className={cn(buttonVariants({ variant, size }), className)}
      data-disabled={disabled || undefined}
      onClick={(event) => {
        if (disabled) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      tabIndex={disabled ? -1 : props.tabIndex}
      {...props}
    />
  );
}
