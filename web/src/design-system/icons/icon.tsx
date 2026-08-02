import * as React from "react";

import { cn } from "@/lib/utilities/cn";

export type IconTone = "primary" | "secondary" | "inverse" | "disabled";
export type IconSize = 16 | 20 | 24;

const toneClass: Record<IconTone, string> = {
  primary: "text-ui-icon-primary",
  secondary: "text-ui-icon-secondary",
  inverse: "text-ui-icon-inverse",
  disabled: "text-ui-icon-disabled",
};

export type IconGlyph = React.ForwardRefExoticComponent<
  Omit<React.SVGProps<SVGSVGElement>, "ref"> &
    React.RefAttributes<SVGSVGElement>
>;

export function Icon({
  glyph: Glyph,
  size = 20,
  tone = "primary",
  className,
  label,
}: {
  glyph: IconGlyph;
  size?: IconSize;
  tone?: IconTone;
  className?: string;
  label?: string;
}) {
  return (
    <Glyph
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={cn("shrink-0", toneClass[tone], className)}
      height={size}
      strokeWidth={1.5}
      width={size}
    />
  );
}
