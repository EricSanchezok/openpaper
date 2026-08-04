import { CheckCircle, Circle } from "iconoir-react";
import { useTranslations } from "next-intl";

import { Icon } from "@/design-system/icons/icon";

export const minimumPasswordLength = 12;

export function PasswordLengthGuidance({ password }: { password: string }) {
  const t = useTranslations("Authentication.passwordGuidance");
  const length = password.length;
  const complete = length >= minimumPasswordLength;
  const message =
    length === 0
      ? t("minimum", { minimum: minimumPasswordLength })
      : t("progress", { count: length, minimum: minimumPasswordLength });

  return (
    <span
      aria-live="polite"
      className={
        complete
          ? "text-success inline-flex items-center gap-1.5"
          : "inline-flex items-center gap-1.5"
      }
    >
      <Icon
        glyph={complete ? CheckCircle : Circle}
        size={16}
        tone="secondary"
      />
      {message}
    </span>
  );
}

export function PasswordMatchGuidance({
  confirmation,
  password,
}: {
  confirmation: string;
  password: string;
}) {
  const t = useTranslations("Authentication.passwordGuidance");
  const hasConfirmation = confirmation.length > 0;
  const matches = hasConfirmation && confirmation === password;
  const message = !hasConfirmation
    ? t("confirm")
    : matches
      ? t("matches")
      : t("mismatch");

  return (
    <span
      aria-live="polite"
      className={
        hasConfirmation
          ? matches
            ? "text-success inline-flex items-center gap-1.5"
            : "text-danger inline-flex items-center gap-1.5"
          : "inline-flex items-center gap-1.5"
      }
    >
      <Icon glyph={matches ? CheckCircle : Circle} size={16} tone="secondary" />
      {message}
    </span>
  );
}
