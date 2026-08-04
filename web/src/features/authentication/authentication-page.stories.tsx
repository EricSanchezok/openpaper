import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { authHandlers } from "../../../.storybook/msw/auth-handlers";
import { ToastProvider } from "@/components/ui/toast";
import { QueryProvider } from "@/lib/query/query-provider";
import { resetRefreshForTests } from "@/lib/api";
import { AuthProvider } from "./auth-session";
import {
  AuthenticationPage,
  resetVerificationFlightsForTests,
} from "./authentication-page";
import type { AuthenticationMode } from "./authentication-mode";

const anonymousLifecycleHandlers = [
  ...authHandlers.refreshMissing,
  ...authHandlers.lifecycleSuccess,
];

const meta = {
  title: "Features/Authentication/Lifecycle",
  component: AuthenticationPage,
  args: { mode: "sign-in" as AuthenticationMode },
  argTypes: {
    mode: {
      control: "select",
      options: ["sign-in", "register", "forgot", "verify", "reset"],
    },
  },
  decorators: [
    (Story) => (
      <QueryProvider>
        <AuthProvider>
          <ToastProvider dismissLabel="Dismiss">
            <Story />
          </ToastProvider>
        </AuthProvider>
      </QueryProvider>
    ),
  ],
  loaders: [
    async () => {
      resetRefreshForTests();
      resetVerificationFlightsForTests();
      window.sessionStorage.clear();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: anonymousLifecycleHandlers },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof AuthenticationPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SignIn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", { name: "Welcome back" }),
    ).toBeVisible();
    await expect(canvas.getByLabelText("Email address")).toHaveAttribute(
      "autocomplete",
      "email",
    );
  },
};

export const InvalidCredentials: Story = {
  parameters: {
    msw: {
      handlers: [
        ...authHandlers.refreshMissing,
        ...authHandlers.invalidCredentials,
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(
      await canvas.findByLabelText("Email address"),
      "eric@example.com",
    );
    await userEvent.type(canvas.getByLabelText("Password"), "wrong-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await expect(
      await canvas.findByText("The email or password is incorrect."),
    ).toBeVisible();
  },
};

export const RateLimited: Story = {
  parameters: {
    msw: {
      handlers: [...authHandlers.refreshMissing, ...authHandlers.rateLimited],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(
      await canvas.findByLabelText("Email address"),
      "eric@example.com",
    );
    await userEvent.type(canvas.getByLabelText("Password"), "wrong-password");
    await userEvent.click(canvas.getByRole("button", { name: "Sign in" }));
    await expect(await canvas.findByText(/60 seconds/)).toBeVisible();
  },
};

export const RegisterSubmitted: Story = {
  args: { mode: "register" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByLabelText("Display name"), "Eric");
    await userEvent.type(
      canvas.getByLabelText("Email address"),
      "eric@example.com",
    );
    await userEvent.type(canvas.getByLabelText("Password"), "twelve-chars!");
    await userEvent.type(
      canvas.getByLabelText("Confirm password"),
      "twelve-chars!",
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Create account" }),
    );
    await expect(
      await canvas.findByRole("heading", {
        level: 1,
        name: "Check your inbox",
      }),
    ).toBeVisible();
  },
};

export const RegisterPasswordGuidance: Story = {
  args: { mode: "register" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const password = await canvas.findByLabelText("Password");
    const confirmation = canvas.getByLabelText("Confirm password");

    await userEvent.type(password, "short");
    await expect(canvas.getByText("5 of 12 characters")).toBeVisible();

    await userEvent.type(confirmation, "different-pass");
    await userEvent.tab();
    await expect(canvas.getByText("Passwords do not match")).toBeVisible();

    await userEvent.clear(password);
    await userEvent.type(password, "different-pass");
    await expect(canvas.getByText("Password requirement met")).toBeVisible();
    await expect(canvas.getByText("Passwords match")).toBeVisible();
  },
};

export const ForgotPasswordSent: Story = {
  args: { mode: "forgot" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(
      await canvas.findByLabelText("Email address"),
      "eric@example.com",
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Send reset link" }),
    );
    await expect(
      await canvas.findByRole("heading", {
        level: 1,
        name: "Check your inbox",
      }),
    ).toBeVisible();
  },
};

export const VerifyLoadingThenSuccess: Story = {
  args: { mode: "verify", token: "valid-verification-token" },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByRole("heading", {
        level: 1,
        name: "Email verified",
      }),
    ).toBeVisible();
  },
};

export const VerifyInvalidLink: Story = {
  args: { mode: "verify" },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByRole("heading", {
        level: 1,
        name: "This link has expired",
      }),
    ).toBeVisible();
  },
};

export const ResetPasswordSuccess: Story = {
  args: { mode: "reset", token: "valid-reset-token" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(
      await canvas.findByLabelText("New password"),
      "twelve-chars!",
    );
    await userEvent.type(
      canvas.getByLabelText("Confirm password"),
      "twelve-chars!",
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Reset password" }),
    );
    await expect(
      await canvas.findByRole("heading", {
        level: 1,
        name: "Password updated",
      }),
    ).toBeVisible();
  },
};

export const ResetInvalidLink: Story = {
  args: { mode: "reset" },
};

export const MobileSignIn: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const MobileCreateAccount: Story = {
  args: { mode: "register" },
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const SimplifiedChinese: Story = {
  globals: { locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByRole("heading", { name: "欢迎回来" }),
    ).toBeVisible();
  },
};
