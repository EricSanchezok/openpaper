"use client";

import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { IconButton } from "./button";

const overlayClass =
  "fixed inset-0 z-50 bg-[var(--color-overlay-backdrop)] backdrop-blur-sm";
const contentClass =
  "fixed left-1/2 top-1/2 z-50 w-[min(92vw,36rem)] -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-line bg-elevated p-6 shadow-[0_20px_60px_var(--color-elevation-shadow)]";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = (
  props: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>,
) => <DialogPrimitive.Title className="text-xl font-semibold" {...props} />;
export const DialogDescription = (
  props: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>,
) => (
  <DialogPrimitive.Description className="text-muted mt-2 text-sm" {...props} />
);
export const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    closeLabel: string;
  }
>(({ children, className, closeLabel, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className={overlayClass} />
    <DialogPrimitive.Content
      className={cn(contentClass, className)}
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
          <Icon glyph={Xmark} size={20} />
        </IconButton>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
DialogContent.displayName = DialogPrimitive.Content.displayName;

export const AlertDialog = AlertDialogPrimitive.Root;
export const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
export const AlertDialogCancel = AlertDialogPrimitive.Cancel;
export const AlertDialogAction = AlertDialogPrimitive.Action;
export const AlertDialogTitle = (
  props: React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>,
) => (
  <AlertDialogPrimitive.Title className="text-xl font-semibold" {...props} />
);
export const AlertDialogDescription = (
  props: React.ComponentPropsWithoutRef<
    typeof AlertDialogPrimitive.Description
  >,
) => (
  <AlertDialogPrimitive.Description
    className="text-muted mt-2 text-sm"
    {...props}
  />
);
export const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Portal>
    <AlertDialogPrimitive.Overlay className={overlayClass} />
    <AlertDialogPrimitive.Content
      className={cn(contentClass, className)}
      ref={ref}
      {...props}
    />
  </AlertDialogPrimitive.Portal>
));
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;
