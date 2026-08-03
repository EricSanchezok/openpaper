import { cn } from "@/lib/utilities/cn";

export function AuthViewport({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <main
      className={cn(
        "safe-page bg-canvas flex min-h-[100dvh] w-full items-start justify-center overflow-x-clip px-4 py-6 sm:items-center sm:px-8 sm:py-10",
        className,
      )}
    >
      <div className="component-container w-full max-w-md">{children}</div>
    </main>
  );
}
