import * as React from "react";

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
      className={["shrink-0", toneClass[tone], className]
        .filter(Boolean)
        .join(" ")}
      height={size}
      strokeWidth={1.5}
      width={size}
    />
  );
}
