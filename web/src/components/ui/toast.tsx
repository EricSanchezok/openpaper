"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { Xmark } from "iconoir-react";
import * as React from "react";

import { Icon } from "@/design-system/icons/icon";
import { cn } from "@/lib/utilities/cn";
import { keyboardFocusRing } from "./focus";

type ToastNotice = {
  description?: string;
  duration?: number;
  id: string;
  title: string;
};

type ToastInput = Omit<ToastNotice, "id">;

const ToastContext = React.createContext<{
  notify: (notice: ToastInput) => string;
  dismiss: (id: string) => void;
} | null>(null);

export function useToast() {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}

export function ToastProvider({
  children,
  dismissLabel,
}: {
  children: React.ReactNode;
  dismissLabel: string;
}) {
  const [notices, setNotices] = React.useState<ToastNotice[]>([]);
  const dismiss = React.useCallback((id: string) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);
  const notify = React.useCallback((notice: ToastInput) => {
    const id = crypto.randomUUID();
    setNotices((current) => [...current, { ...notice, id }]);
    return id;
  }, []);
  const value = React.useMemo(() => ({ dismiss, notify }), [dismiss, notify]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider>
        {children}
        {notices.map((notice) => (
          <ToastRoot
            duration={notice.duration}
            key={notice.id}
            onOpenChange={(open) => {
              if (!open) dismiss(notice.id);
            }}
            open
          >
            <ToastTitle>{notice.title}</ToastTitle>
            {notice.description ? (
              <ToastDescription>{notice.description}</ToastDescription>
            ) : null}
            <ToastClose label={dismissLabel} />
          </ToastRoot>
        ))}
        <ToastViewport />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

export const ToastViewport = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>,
) => (
  <ToastPrimitive.Viewport
    className="fixed right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-[100] flex w-[min(calc(100vw-2rem),24rem)] flex-col gap-2 outline-none"
    {...props}
  />
);

export const ToastRoot = React.forwardRef<
  React.ElementRef<typeof ToastPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root>
>(({ className, ...props }, ref) => (
  <ToastPrimitive.Root
    className={cn(
      "border-line bg-elevated shadow-overlay relative grid gap-1 rounded-[var(--radius-lg)] border px-4 py-3 pr-12",
      className,
    )}
    ref={ref}
    {...props}
  />
));
ToastRoot.displayName = ToastPrimitive.Root.displayName;

export const ToastTitle = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Title>,
) => <ToastPrimitive.Title className="text-sm font-medium" {...props} />;

export const ToastDescription = (
  props: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Description>,
) => <ToastPrimitive.Description className="text-muted text-sm" {...props} />;

export const ToastAction = ToastPrimitive.Action;

export const ToastClose = ({
  label,
  ...props
}: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close> & {
  label: string;
}) => (
  <ToastPrimitive.Close
    aria-label={label}
    className={cn(
      "hover:bg-hover absolute top-1 right-1 grid size-11 place-items-center rounded-[var(--radius-md)]",
      keyboardFocusRing,
    )}
    {...props}
  >
    <Icon glyph={Xmark} size={16} tone="secondary" />
  </ToastPrimitive.Close>
);
