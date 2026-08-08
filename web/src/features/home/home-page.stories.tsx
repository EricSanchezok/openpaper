import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

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
      await canvas.findByRole("heading", { level: 1 }),
    ).toBeVisible();
    await expect(
      await canvas.findByText("Attention Is All You Need"),
    ).toBeVisible();
    await expect(
      await canvas.findByText("Thesis literature review"),
    ).toBeVisible();
    const composer = canvas.getByRole("textbox", {
      name: /Ask anything|问任何问题/,
    });
    const submit = canvas.getByRole("button", {
      name: /Ask Scholens|询问 Scholens/,
    });
    await expect(submit).toBeDisabled();
    await userEvent.click(composer);
    await expect(composer).toHaveAttribute("data-focus-delegate", "surface");
    await expect(composer).toHaveAttribute("data-focus-origin", "pointer");
    await expect(composer).toHaveStyle({ outlineStyle: "none" });
    await expect(composer.closest("form")).toHaveStyle({
      outlineStyle: "none",
    });
  },
};

export const ContextPicker: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "Research scope: Library" }),
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
    await waitFor(() =>
      expect(canvas.getByText("Searching your research…")).toBeVisible(),
    );
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

export const MobileEmpty: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const primaryNavigation = await canvas.findByRole("navigation", {
      name: "主导航",
    });
    const activeDestination = within(primaryNavigation).getByRole("link", {
      name: "问答",
    });
    await expect(activeDestination).toHaveAttribute("aria-current", "page");
    await expect(
      activeDestination.querySelector("[data-selected-indicator]"),
    ).not.toBeNull();
    await expect(
      canvas.getByRole("textbox", { name: "问任何问题" }),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "思考强度：标准" }),
    ).toBeVisible();
  },
};

export const MobileComposerExpanded: Story = {
  ...MobileEmpty,
  play: async ({ canvasElement }) => {
    const composer = await within(canvasElement).findByRole("textbox", {
      name: "问任何问题",
    });
    await userEvent.type(
      composer,
      "比较这三篇论文的核心方法{Shift>}{Enter}{/Shift}并说明它们在推理成本和准确率上的差异",
    );
    await expect(composer).toHaveValue(
      "比较这三篇论文的核心方法\n并说明它们在推理成本和准确率上的差异",
    );
  },
};

export const MobileConversation: Story = {
  args: { initialConversationId: homeConversations[0]!.id },
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("button", { name: "打开导航" }),
    ).toBeVisible();
    await expect(
      await canvas.findByRole("textbox", { name: "继续追问" }),
    ).toBeVisible();
  },
};

export const MobileConversationLarge: Story = {
  ...MobileConversation,
  globals: {
    locale: "zh-CN",
    viewport: { value: "largeMobile", isRotated: false },
  },
};

export const MobileKeyboardOpen: Story = {
  args: {
    mobileKeyboardOverride: { open: true, viewportHeight: 548 },
  },
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.empty] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      await canvas.findByRole("textbox", { name: "问任何问题" }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("navigation", { name: "主导航" }),
    ).not.toBeInTheDocument();
  },
};

export const MobileReasoningMenuOpen: Story = {
  ...MobileEmpty,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "思考强度：标准" }),
    );
    const body = within(document.body);
    await expect(
      await body.findByRole("menuitemradio", { name: /标准/ }),
    ).toBeVisible();
    await expect(
      body.getByRole("menuitemradio", { name: /深入/ }),
    ).toBeVisible();
    await expect(body.queryByText("选择模型")).not.toBeInTheDocument();
  },
};

export const MobileNavigationOpen: Story = {
  args: { initialConversationId: homeConversations[0]!.id },
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      await canvas.findByRole("button", { name: "打开导航" }),
    );
    const body = within(document.body);
    const dialog = await body.findByRole("dialog");
    const navigation = within(dialog);
    await expect(dialog).toBeVisible();
    await expect(
      navigation.getByRole("searchbox", { name: "搜索对话" }),
    ).toBeVisible();
    await expect(
      navigation.getByRole("button", { name: "关闭导航" }),
    ).toBeVisible();
    await expect(
      navigation.queryByRole("link", { name: "新对话" }),
    ).not.toBeInTheDocument();
    await expect(navigation.getByText(actor.email)).toBeVisible();
  },
};

export const MobileProcessing: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  parameters: {
    msw: { handlers: [...authHandlers.success, ...homeHandlers.processing] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const composer = await canvas.findByRole("textbox", { name: "问任何问题" });
    await userEvent.type(composer, "比较选中的论文");
    await userEvent.click(
      canvas.getByRole("button", { name: "询问 Scholens" }),
    );
    await waitFor(() =>
      expect(canvas.getByText("正在检索你的研究资料…")).toBeVisible(),
    );
  },
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
