import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { homePapers, homeProjects } from "../api/fixtures";
import { HomeDashboard } from "./home-dashboard";

const meta = {
  title: "Features/Home/Dashboard",
  component: HomeDashboard,
  args: {
    papers: homePapers,
    projects: homeProjects,
    context: { kind: "library" },
    reasoningLevel: "standard",
    onContextChange: fn(),
    onReasoningLevelChange: fn(),
    onSubmit: fn(async () => undefined),
    onRetryPapers: fn(),
    onRetryProjects: fn(),
  },
  decorators: [
    (Story) => (
      <div className="h-screen">
        <Story />
      </div>
    ),
  ],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof HomeDashboard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const PapersOnly: Story = {
  args: { projects: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Recent papers")).toBeVisible();
    await expect(canvas.queryByText("Recent projects")).not.toBeInTheDocument();
  },
};

export const ProjectsOnly: Story = {
  args: { papers: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Recent projects")).toBeVisible();
    await expect(canvas.queryByText("Recent papers")).not.toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { papers: [], projects: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Ask across a paper/)).toBeVisible();
    await expect(canvas.queryByText("Recent papers")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Recent projects")).not.toBeInTheDocument();
  },
};

export const MobileRecents: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "mobile", isRotated: false },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("继续最近研究")).toBeVisible();
    await expect(canvas.getByText("最近论文")).not.toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", {
        name: /将论文《Attention Is All You Need》设为研究范围/,
      }),
    );
    await expect(args.onContextChange).toHaveBeenCalledWith({
      kind: "selection",
      project_ids: [],
      document_ids: [homePapers[0]!.document.document_id],
    });
  },
};

export const MobileRecentsLoading: Story = {
  globals: { viewport: { value: "mobile", isRotated: false } },
  args: {
    papers: [],
    projects: [],
    papersLoading: true,
    projectsLoading: true,
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("status", {
        name: "Loading recent research",
      }),
    ).toBeVisible();
  },
};

export const MobileRecentsError: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: { papers: [], projects: [], papersError: true, projectsError: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const visibleError = canvas
      .getAllByText("Could not load recent research")
      .find((element) => element.getClientRects().length > 0);
    await expect(visibleError).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Try again" }),
    ).toBeVisible();
  },
};
