import { ArrowRight } from "iconoir-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Icon } from "@/design-system/icons/icon";

export default function FoundationSmokePage() {
  const common = useTranslations("Common");
  const smoke = useTranslations("FoundationSmoke");

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl items-center px-6 py-16">
      <section className="border-line grid w-full gap-12 border-y py-12 md:grid-cols-[1fr_auto] md:items-end">
        <div className="max-w-2xl space-y-4">
          <p className="text-muted text-sm">{smoke("eyebrow")}</p>
          <h1 className="text-4xl font-semibold tracking-[-0.035em] md:text-5xl">
            {common("appName")}
          </h1>
          <p className="text-secondary max-w-xl text-base leading-7">
            {smoke("description")}
          </p>
        </div>
        <Button asChild>
          <a href="http://127.0.0.1:7306">
            {common("actions.openStorybook")}
            <Icon glyph={ArrowRight} size={16} tone="inverse" />
          </a>
        </Button>
      </section>
    </main>
  );
}
