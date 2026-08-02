"use client";

import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area";
import * as VisuallyHiddenPrimitive from "@radix-ui/react-visually-hidden";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

export const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root>
>(({ children, className, ...props }, ref) => (
  <ScrollAreaPrimitive.Root
    className={cn("relative overflow-hidden", className)}
    ref={ref}
    {...props}
  >
    <ScrollAreaPrimitive.Viewport
      className="size-full rounded-[inherit]"
      tabIndex={0}
    >
      {children}
    </ScrollAreaPrimitive.Viewport>
    <ScrollAreaPrimitive.Scrollbar
      className="flex w-2.5 touch-none p-0.5 select-none"
      orientation="vertical"
    >
      <ScrollAreaPrimitive.Thumb className="bg-line-strong relative flex-1 rounded-full" />
    </ScrollAreaPrimitive.Scrollbar>
    <ScrollAreaPrimitive.Corner />
  </ScrollAreaPrimitive.Root>
));
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName;

export const VisuallyHidden = VisuallyHiddenPrimitive.Root;
