"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { IconButton } from "./button";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;
export const SheetContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    closeLabel: string;
    closeGlyph?: IconGlyph;
  }
>(({ children, className, closeGlyph = Xmark, closeLabel, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[var(--color-overlay-backdrop)]" />
    <DialogPrimitive.Content
      className={cn(
        "border-line bg-elevated shadow-panel fixed inset-y-0 right-0 z-50 w-[min(90vw,30rem)] border-l p-6",
        className,
      )}
      ref={ref}
      {...props}
    >
      {children}
      <DialogPrimitive.Close asChild>
        <IconButton
          className="absolute top-3 right-3"
          label={closeLabel}
          variant="ghost"
        >
          <Icon glyph={closeGlyph} size={24} />
        </IconButton>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = DialogPrimitive.Content.displayName;
