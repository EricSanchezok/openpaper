"use client";

import { Eye, EyeClosed, Search } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";

const controlClass =
  "w-full rounded-[var(--radius-md)] border border-control bg-surface px-3 text-sm text-foreground placeholder:text-muted transition-colors hover:border-line-strong focus-visible:border-[var(--color-border-focus)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-canvas aria-invalid:border-[var(--color-danger-border)] aria-invalid:ring-[var(--color-danger-border)] disabled:cursor-not-allowed disabled:border-line disabled:bg-subtle disabled:text-disabled";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input className={cn(controlClass, "h-11", className)} ref={ref} {...props} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    className={cn(controlClass, "min-h-24 resize-y py-3", className)}
    ref={ref}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const SearchField = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <div className="relative">
    <Icon
      className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2"
      glyph={Search}
      size={20}
      tone="secondary"
    />
    <Input
      className={cn("pl-10", className)}
      ref={ref}
      type="search"
      {...props}
    />
  </div>
));
SearchField.displayName = "SearchField";

export type PasswordInputProps = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type"
> & {
  showPasswordLabel: string;
  hidePasswordLabel: string;
};

export const PasswordInput = React.forwardRef<
  HTMLInputElement,
  PasswordInputProps
>(
  (
    { className, showPasswordLabel, hidePasswordLabel, autoComplete, ...props },
    ref,
  ) => {
    const [visible, setVisible] = React.useState(false);
    const label = visible ? hidePasswordLabel : showPasswordLabel;

    return (
      <div className="relative">
        <Input
          autoComplete={autoComplete ?? "current-password"}
          className={cn("pr-12", className)}
          ref={ref}
          type={visible ? "text" : "password"}
          {...props}
        />
        <button
          aria-label={label}
          aria-pressed={visible}
          className="text-ui-icon-secondary hover:bg-hover absolute top-1/2 right-0 grid size-11 -translate-y-1/2 place-items-center rounded-[var(--radius-md)] focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:outline-none"
          disabled={props.disabled}
          onClick={() => setVisible((value) => !value)}
          type="button"
        >
          <Icon
            glyph={visible ? EyeClosed : Eye}
            size={20}
            tone={props.disabled ? "disabled" : "secondary"}
          />
        </button>
      </div>
    );
  },
);
PasswordInput.displayName = "PasswordInput";
