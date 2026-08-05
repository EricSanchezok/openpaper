import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { homePapers, homeProjects } from "../api/fixtures";
import { ResearchComposer } from "./research-composer";

const meta = {
  title: "Features/Home/Research Composer",
  component: ResearchComposer,
  args: {
    context: { kind: "library" },
    papers: homePapers,
    projects: homeProjects,
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onStop: fn(),
  },
  decorators: [
    (Story) => (
      <div className="flex min-h-screen items-end p-2">
        <Story />
      </div>
    ),
  ],
  globals: { locale: "zh-CN", viewport: { value: "mobile", isRotated: false } },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof ResearchComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LibraryScope: Story = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "研究范围：资料库",
      }),
    ).toBeVisible();
  },
};

export const MultiplePapersScope: Story = {
  args: {
    context: {
      kind: "selection",
      project_ids: [],
      document_ids: homePapers
        .slice(0, 2)
        .map((paper) => paper.document.document_id),
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "研究范围：2 篇" }),
    ).toBeVisible();
  },
};

export const LongProjectScope: Story = {
  args: {
    projects: [
      {
        ...homeProjects[0]!,
        title: "面向长上下文推理的多阶段研究项目",
      },
    ],
    context: {
      kind: "selection",
      project_ids: [homeProjects[0]!.id],
      document_ids: [],
    },
  },
  globals: {
    locale: "zh-CN",
    viewport: { value: "smallMobile", isRotated: false },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "研究范围：面向长上下文推理的多阶段研究项目",
      }),
    ).toBeVisible();
  },
};

export const MultilineInput: Story = {
  play: async ({ canvasElement }) => {
    const composer = within(canvasElement).getByRole("textbox", {
      name: "问任何问题",
    });
    await userEvent.type(
      composer,
      "比较论文方法{Shift>}{Enter}{/Shift}说明推理成本{Shift>}{Enter}{/Shift}列出关键差异",
    );
    await expect(composer).toHaveValue(
      "比较论文方法\n说明推理成本\n列出关键差异",
    );
  },
};

export const StreamingStop: Story = {
  args: { busy: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "停止生成" }),
    ).toBeVisible();
  },
};

export const DarkEnglishLarge: Story = {
  globals: {
    appearance: "dark",
    locale: "en",
    viewport: { value: "largeMobile", isRotated: false },
  },
};
