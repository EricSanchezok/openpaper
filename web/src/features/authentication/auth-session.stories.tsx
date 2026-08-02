import { useTranslations } from "next-intl";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { authHandlers } from "../../../.storybook/msw/auth-handlers";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { resetRefreshForTests } from "@/lib/api/refresh";
import { AuthProvider, useAuthSession } from "./auth-session";
import { AuthViewport } from "./auth-surface";

type Scenario = "bootstrapping" | "authenticated" | "anonymous" | "unavailable";

function SessionPreview() {
  const session = useAuthSession();
  const t = useTranslations("Authentication.session");
  const actions = useTranslations("Common.actions");
  return (
    <AuthViewport>
      <Alert tone={session.status === "unavailable" ? "danger" : "neutral"}>
        <AlertTitle>{t(session.status)}</AlertTitle>
        <AlertDescription>
          {session.actor?.email ?? session.status}
        </AlertDescription>
        {session.status === "unavailable" ? (
          <Button
            className="mt-4 w-full sm:w-auto"
            onClick={() => void session.retryBootstrap()}
          >
            {actions("tryAgain")}
          </Button>
        ) : null}
      </Alert>
    </AuthViewport>
  );
}

const meta = {
  title: "Examples/Auth session harness",
  args: { scenario: "authenticated" as Scenario },
  loaders: [
    async () => {
      resetRefreshForTests();
      return {};
    },
  ],
  decorators: [
    (Story) => (
      <AuthProvider>
        <Story />
      </AuthProvider>
    ),
  ],
  render: () => <SessionPreview />,
  parameters: { layout: "fullscreen" },
} satisfies Meta<{ scenario: Scenario }>;

export default meta;
type Story = StoryObj<typeof meta>;

async function expectAuthenticatedAtViewport(
  canvasElement: HTMLElement,
  expectedWidth: number,
) {
  await within(canvasElement).findByText("Signed in");
  const storyDocument = canvasElement.ownerDocument;
  expect(storyDocument.documentElement.scrollWidth).toBeLessThanOrEqual(
    storyDocument.defaultView?.innerWidth ?? expectedWidth,
  );
}

export const Bootstrapping: Story = {
  args: { scenario: "bootstrapping" },
  parameters: { msw: { handlers: authHandlers.bootstrapping } },
};
export const Authenticated: Story = {
  args: { scenario: "authenticated" },
  parameters: { msw: { handlers: authHandlers.success } },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText("Signed in");
    expect(
      await within(canvasElement).findByText("eric@scholens.ai"),
    ).toBeVisible();
  },
};
export const Anonymous: Story = {
  args: { scenario: "anonymous" },
  parameters: { msw: { handlers: authHandlers.refreshMissing } },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText("Signed out");
  },
};
export const Unavailable: Story = {
  args: { scenario: "unavailable" },
  parameters: { msw: { handlers: authHandlers.unavailable } },
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText("Session service unavailable");
    expect(
      await within(canvasElement).findByRole("button", { name: "Try again" }),
    ).toBeVisible();
  },
};
export const SmallMobile: Story = {
  args: { scenario: "authenticated" },
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  parameters: { msw: { handlers: authHandlers.success } },
  play: async ({ canvasElement }) => {
    await expectAuthenticatedAtViewport(canvasElement, 320);
  },
};
export const Mobile: Story = {
  args: { scenario: "authenticated" },
  globals: { viewport: { value: "mobile", isRotated: false } },
  parameters: { msw: { handlers: authHandlers.success } },
  play: async ({ canvasElement }) => {
    await expectAuthenticatedAtViewport(canvasElement, 390);
  },
};
export const Tablet: Story = {
  args: { scenario: "authenticated" },
  globals: { viewport: { value: "tablet", isRotated: false } },
  parameters: { msw: { handlers: authHandlers.success } },
  play: async ({ canvasElement }) => {
    await expectAuthenticatedAtViewport(canvasElement, 768);
  },
};
export const Desktop: Story = {
  args: { scenario: "authenticated" },
  globals: { viewport: { value: "desktop", isRotated: false } },
  parameters: { msw: { handlers: authHandlers.success } },
  play: async ({ canvasElement }) => {
    await expectAuthenticatedAtViewport(canvasElement, 1440);
  },
};
