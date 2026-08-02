"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { NavArrowLeft, NavArrowRight } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { Button, IconButton } from "./button";

export const Tabs = TabsPrimitive.Root;
export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    className={cn(
      "bg-subtle inline-flex gap-1 rounded-[var(--radius-lg)] p-1",
      className,
    )}
    ref={ref}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;
export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    className={cn(
      "text-muted hover:text-foreground data-[state=active]:bg-surface data-[state=active]:text-foreground disabled:text-disabled h-9 rounded-[var(--radius-md)] px-3 text-sm transition-colors data-[state=active]:shadow-sm",
      className,
    )}
    ref={ref}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;
export const TabsContent = TabsPrimitive.Content;

export function Pagination({
  page,
  pages,
  onPageChange,
}: {
  page: number;
  pages: number;
  onPageChange?: (page: number) => void;
}) {
  const visible = Array.from(
    { length: Math.min(pages, 3) },
    (_, index) => index + 1,
  );
  return (
    <nav aria-label="Pagination" className="flex items-center gap-1">
      <IconButton
        disabled={page <= 1}
        label="Previous page"
        onClick={() => onPageChange?.(page - 1)}
        variant="secondary"
      >
        <Icon glyph={NavArrowLeft} size={16} />
      </IconButton>
      {visible.map((number) => (
        <Button
          aria-current={number === page ? "page" : undefined}
          key={number}
          onClick={() => onPageChange?.(number)}
          size="icon-sm"
          variant={number === page ? "primary" : "ghost"}
        >
          {number}
        </Button>
      ))}
      <IconButton
        disabled={page >= pages}
        label="Next page"
        onClick={() => onPageChange?.(page + 1)}
        variant="secondary"
      >
        <Icon glyph={NavArrowRight} size={16} />
      </IconButton>
    </nav>
  );
}
