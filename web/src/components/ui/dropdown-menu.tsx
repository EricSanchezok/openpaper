"use client";

import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, NavArrowRight } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuGroup = DropdownPrimitive.Group;
export const DropdownMenuSub = DropdownPrimitive.Sub;
export const DropdownMenuRadioGroup = DropdownPrimitive.RadioGroup;

export const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <DropdownPrimitive.Portal>
    <DropdownPrimitive.Content
      className={cn(
        "border-line bg-elevated z-50 min-w-48 rounded-[var(--radius-lg)] border p-1 shadow-[0_12px_36px_var(--color-elevation-shadow)]",
        className,
      )}
      ref={ref}
      sideOffset={sideOffset}
      {...props}
    />
  </DropdownPrimitive.Portal>
));
DropdownMenuContent.displayName = DropdownPrimitive.Content.displayName;

export const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Item> & {
    destructive?: boolean;
  }
>(({ className, destructive, ...props }, ref) => (
  <DropdownPrimitive.Item
    className={cn(
      "data-[highlighted]:bg-hover data-[disabled]:text-disabled flex min-h-9 cursor-default items-center gap-2 rounded-[var(--radius-md)] px-2 text-sm outline-none select-none",
      destructive && "text-danger",
      className,
    )}
    ref={ref}
    {...props}
  />
));
DropdownMenuItem.displayName = DropdownPrimitive.Item.displayName;

export const DropdownMenuCheckboxItem = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.CheckboxItem>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.CheckboxItem>
>(({ children, className, ...props }, ref) => (
  <DropdownPrimitive.CheckboxItem
    className={cn(
      "data-[highlighted]:bg-hover relative flex min-h-9 cursor-default items-center rounded-[var(--radius-md)] py-2 pr-2 pl-8 text-sm outline-none",
      className,
    )}
    ref={ref}
    {...props}
  >
    <span className="absolute left-2">
      <DropdownPrimitive.ItemIndicator>
        <Icon glyph={Check} size={16} />
      </DropdownPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownPrimitive.CheckboxItem>
));
DropdownMenuCheckboxItem.displayName =
  DropdownPrimitive.CheckboxItem.displayName;

export const DropdownMenuRadioItem = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.RadioItem>
>(({ children, className, ...props }, ref) => (
  <DropdownPrimitive.RadioItem
    className={cn(
      "data-[highlighted]:bg-hover relative flex min-h-9 cursor-default items-center rounded-[var(--radius-md)] py-2 pr-2 pl-8 text-sm outline-none",
      className,
    )}
    ref={ref}
    {...props}
  >
    <span className="absolute left-2">
      <DropdownPrimitive.ItemIndicator>
        <span className="bg-primary block size-2 rounded-full" />
      </DropdownPrimitive.ItemIndicator>
    </span>
    {children}
  </DropdownPrimitive.RadioItem>
));
DropdownMenuRadioItem.displayName = DropdownPrimitive.RadioItem.displayName;

export const DropdownMenuSubTrigger = React.forwardRef<
  React.ElementRef<typeof DropdownPrimitive.SubTrigger>,
  React.ComponentPropsWithoutRef<typeof DropdownPrimitive.SubTrigger>
>(({ children, className, ...props }, ref) => (
  <DropdownPrimitive.SubTrigger
    className={cn(
      "data-[highlighted]:bg-hover flex min-h-9 items-center rounded-[var(--radius-md)] px-2 text-sm outline-none",
      className,
    )}
    ref={ref}
    {...props}
  >
    {children}
    <Icon className="ml-auto" glyph={NavArrowRight} size={16} />
  </DropdownPrimitive.SubTrigger>
));
DropdownMenuSubTrigger.displayName = DropdownPrimitive.SubTrigger.displayName;
export const DropdownMenuSubContent = DropdownMenuContent;
export const DropdownMenuSeparator = (
  props: React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Separator>,
) => <DropdownPrimitive.Separator className="bg-line my-1 h-px" {...props} />;
export const DropdownMenuLabel = (
  props: React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Label>,
) => (
  <DropdownPrimitive.Label
    className="text-muted px-2 py-1.5 text-xs font-medium"
    {...props}
  />
);
