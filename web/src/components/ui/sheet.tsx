"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { IconButton } from "./button";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;
export const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ children, className, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[var(--color-overlay-backdrop)]" />
    <DialogPrimitive.Content
      className={cn(
        "border-line bg-elevated fixed inset-y-0 right-0 z-50 w-[min(90vw,30rem)] border-l p-6 shadow-[0_0_48px_var(--color-elevation-shadow)]",
        className,
      )}
      ref={ref}
      {...props}
    >
      {children}
      <DialogPrimitive.Close asChild>
        <IconButton
          className="absolute top-3 right-3"
          label="Close panel"
          variant="ghost"
        >
          <Icon glyph={Xmark} size={20} />
        </IconButton>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = DialogPrimitive.Content.displayName;
