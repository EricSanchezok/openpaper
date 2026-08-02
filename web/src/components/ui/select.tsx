"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, NavArrowDown } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;
export const SelectGroup = SelectPrimitive.Group;
export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ children, className, ...props }, ref) => (
  <SelectPrimitive.Trigger
    className={cn(
      "border-control bg-surface hover:border-line-strong disabled:text-disabled flex h-11 w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border px-3 text-sm",
      className,
    )}
    ref={ref}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon>
      <Icon glyph={NavArrowDown} size={16} tone="secondary" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;
export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ children, className, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      className={cn(
        "border-line bg-elevated z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[var(--radius-lg)] border p-1 shadow-[0_12px_36px_var(--color-elevation-shadow)]",
        className,
      )}
      position={position}
      ref={ref}
      {...props}
    >
      <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;
export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ children, className, ...props }, ref) => (
  <SelectPrimitive.Item
    className={cn(
      "data-[highlighted]:bg-hover relative flex min-h-10 cursor-default items-center rounded-[var(--radius-md)] py-2 pr-9 pl-3 text-sm outline-none select-none",
      className,
    )}
    ref={ref}
    {...props}
  >
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    <span className="absolute right-3">
      <SelectPrimitive.ItemIndicator>
        <Icon glyph={Check} size={16} />
      </SelectPrimitive.ItemIndicator>
    </span>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;
export const SelectLabel = (
  props: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>,
) => (
  <SelectPrimitive.Label
    className="text-muted px-3 py-2 text-xs font-medium"
    {...props}
  />
);
export const SelectSeparator = (
  props: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>,
) => <SelectPrimitive.Separator className="bg-line my-1 h-px" {...props} />;
