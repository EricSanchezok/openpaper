import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { authHandlers, actor } from "../../../.storybook/msw/auth-handlers";
import { Providers } from "@/app/providers";
import { resetRefreshForTests } from "@/lib/api";
import { homeHandlers } from "./api/handlers";
import { homeConversations } from "./api/fixtures";
import { HomeWorkspace } from "./home-page";

const meta = {
  title: "Features/Home/Workspace",
  component: HomeWorkspace,
  args: { actor },
  decorators: [
    (Story) => (
      <Providers>
        <Story />
      </Providers>
    ),
  ],
  loaders: [
    async () => {
      resetRefreshForTests();
      window.sessionStorage.clear();
      return {};
    },
  ],
  parameters: {
    layout: "fullscreen",
    msw: { handlers: [...authHandlers.success, ...homeHandlers.populated] },
    nextjs: { appDirectory: true },
  },
} satisfies Meta<typeof HomeWorkspace>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("heading", {
        name: "What are you working on?",
      }),
    ).toBeVisible();
    await expect(
      await canvas.findByText("Attention Is All You Need"),
    ).toBeVisible();
    await expect(
      await canvas.findByText("Thesis literature review"),
    ).toBeVisible();
  },
};

export const ContextPicker: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Add context" }),
    );
    const body = within(document.body);
    await expect(
      await body.findByRole("heading", { name: "Add context" }),
    ).toBeVisible();
    await userEvent.click(body.getByRole("switch", { name: "Entire library" }));
    await userEvent.type(body.getByRole("searchbox"), "RAG");
    await expect(
      body.getByRole("checkbox", { name: /RAG evaluation/ }),
    ).toBeVisible();
  },
};

export const SidebarCollapsed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Collapse sidebar" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Expand sidebar" }),
    ).toBeVisible();
  },
};

export const AccountMenuOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", {
      name: "Open account menu",
    });
    await expect(trigger.querySelector("svg")).toBeNull();
    await userEvent.click(trigger);
    const body = within(document.body);
    const menu = await body.findByRole("menu");
    await expect(within(menu).getByText(actor.email)).toBeVisible();
    await expect(
      body.getByRole("menuitemradio", { name: "System" }),
    ).toBeVisible();
  },
};

export const Conversation: Story = {
  args: { initialConversationId: homeConversations[0]!.id },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText("What is the paper’s central contribution?"),
    ).toBeVisible();
    await expect(
      canvas.getByText(/persistent runtime for agents/),
    ).toBeVisible();
  },
};

export const Processing: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.processing] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = await canvas.findByRole("textbox", {
      name: "Ask anything",
    });
    await userEvent.type(composer, "Compare the selected papers");
    await userEvent.click(canvas.getByRole("button", { name: "Ask Scholens" }));
    await expect(
      await canvas.findByText("Searching the library"),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Stop response" }),
    ).toBeVisible();
  },
};

export const ReadOnly: Story = {
  args: { initialConversationId: homeConversations[0]!.id },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.readOnly] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByText(/research context is no longer available/),
    ).toBeVisible();
    await expect(
      canvas.getByRole("textbox", { name: "Ask a follow-up" }),
    ).toBeDisabled();
  },
};

export const Empty: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/Ask across a paper/)).toBeVisible();
    await expect(canvas.queryByText("Recent papers")).not.toBeInTheDocument();
    await expect(
      canvas.queryByText("No recent projects"),
    ).not.toBeInTheDocument();
  },
};

export const Error: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.error] },
  },
};

export const Slow: Story = {
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.slow] },
  },
};

export const Mobile: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
};

export const SimplifiedChinese: Story = {
  globals: { locale: "zh-CN" },
  play: async ({ canvasElement }) => {
    await expect(
      await within(canvasElement).findByRole("heading", {
        name: "你正在研究什么？",
      }),
    ).toBeVisible();
  },
};

export const EmptySimplifiedChinese: Story = {
  globals: { locale: "zh-CN" },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/从一篇论文/)).toBeVisible();
    await expect(canvas.queryByText("最近论文")).not.toBeInTheDocument();
  },
};
