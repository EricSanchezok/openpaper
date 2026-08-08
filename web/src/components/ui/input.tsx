"use client";

import { Eye, EyeClosed, Search } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { keyboardFocusRing } from "./focus";
import { useTextControlFocus } from "./text-control-focus";

const controlClass =
  "w-full rounded-[var(--radius-md)] border border-control bg-surface px-3 text-sm text-foreground placeholder:text-muted transition-colors hover:border-line-strong aria-invalid:border-[var(--color-danger-border)] disabled:cursor-not-allowed disabled:border-line disabled:bg-subtle disabled:text-disabled";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, onBlur, onFocus, ...props }, ref) => {
  const { focusHandlers, focusOrigin } = useTextControlFocus<HTMLInputElement>({
    onBlur,
    onFocus,
  });

  return (
    <input
      className={cn(controlClass, "h-11", className)}
      data-focus-delegate="self"
      data-focus-origin={focusOrigin ?? undefined}
      ref={ref}
      {...focusHandlers}
      {...props}
    />
  );
});
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, onBlur, onFocus, ...props }, ref) => {
  const { focusHandlers, focusOrigin } =
    useTextControlFocus<HTMLTextAreaElement>({ onBlur, onFocus });

  return (
    <textarea
      className={cn(controlClass, "min-h-24 resize-y py-3", className)}
      data-focus-delegate="self"
      data-focus-origin={focusOrigin ?? undefined}
      ref={ref}
      {...focusHandlers}
      {...props}
    />
  );
});
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
          className={cn(
            "text-ui-icon-secondary hover:bg-hover absolute top-1/2 right-0 grid size-11 -translate-y-1/2 place-items-center rounded-[var(--radius-md)]",
            keyboardFocusRing,
          )}
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
