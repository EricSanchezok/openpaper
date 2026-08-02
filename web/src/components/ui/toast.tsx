"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";

export const ToastProvider = ToastPrimitive.Provider;
export const ToastViewport = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>,
) => (
  <ToastPrimitive.Viewport
    className="fixed right-4 bottom-4 z-[100] flex w-[min(92vw,24rem)] flex-col gap-2 outline-none"
    {...props}
  />
);
export const Toast = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Root
    className={cn(
      "border-line bg-elevated relative grid gap-1 rounded-[var(--radius-lg)] border px-4 py-3 pr-10 shadow-[0_12px_36px_var(--color-elevation-shadow)]",
      className,
    )}
    ref={ref}
    {...props}
  />
));
Toast.displayName = ToastPrimitive.Root.displayName;
export const ToastTitle = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Title>,
) => <ToastPrimitive.Title className="text-sm font-medium" {...props} />;
export const ToastDescription = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Description>,
) => <ToastPrimitive.Description className="text-muted text-sm" {...props} />;
export const ToastAction = ToastPrimitive.Action;
export const ToastClose = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close>,
) => (
  <ToastPrimitive.Close
    aria-label="Dismiss"
    className="absolute top-3 right-3"
    {...props}
  >
    <Icon glyph={Xmark} size={16} tone="secondary" />
  </ToastPrimitive.Close>
);
