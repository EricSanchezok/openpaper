import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";

import { cn } from "@/lib/utilities/cn";

type FieldContextValue = {
  controlId: string;
  descriptionId?: string;
  invalid: boolean;
  messageId?: string;
};

const FieldContext = React.createContext<FieldContextValue | null>(null);

function useFieldContext() {
  const context = React.useContext(FieldContext);
  if (!context) throw new Error("Field parts must be rendered inside Field");
  return context;
}

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    className={cn("text-sm font-medium", className)}
    ref={ref}
    {...props}
  />
));
Label.displayName = LabelPrimitive.Root.displayName;

export function Field({
  children,
  className,
  invalid = false,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { invalid?: boolean }) {
  const id = React.useId();
  const parts = React.Children.toArray(children);
  const hasDescription = parts.some(
    (child) => React.isValidElement(child) && child.type === FieldDescription,
  );
  const hasMessage = parts.some(
    (child) => React.isValidElement(child) && child.type === FieldMessage,
  );
  const value = {
    controlId: `${id}-control`,
    descriptionId: hasDescription ? `${id}-description` : undefined,
    messageId: hasMessage ? `${id}-message` : undefined,
    invalid,
  };
  return (
    <FieldContext.Provider value={value}>
      <div className={cn("grid gap-2", className)} {...props}>
        {children}
      </div>
    </FieldContext.Provider>
  );
}

export function FieldLabel(
  props: React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>,
) {
  const { controlId } = useFieldContext();
  return <Label htmlFor={controlId} {...props} />;
}

export function FieldControl({
  children,
}: {
  children: React.ReactElement<Record<string, unknown>>;
}) {
  const { controlId, descriptionId, invalid, messageId } = useFieldContext();
  const childProps = children.props;
  const describedBy = [descriptionId, messageId].filter(Boolean).join(" ");
  return React.cloneElement(children, {
    id: childProps.id ?? controlId,
    "aria-invalid": childProps["aria-invalid"] ?? (invalid || undefined),
    "aria-describedby":
      childProps["aria-describedby"] ?? (describedBy || undefined),
  });
}

export function FieldDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  const { descriptionId } = useFieldContext();
  return (
    <p
      className={cn("text-muted text-sm", className)}
      id={descriptionId}
      {...props}
    />
  );
}

export function FieldMessage({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  const { invalid, messageId } = useFieldContext();
  return (
    <p
      aria-live={invalid ? "polite" : undefined}
      className={cn(
        "text-sm",
        invalid ? "text-danger" : "text-muted",
        className,
      )}
      id={messageId}
      {...props}
    />
  );
}
