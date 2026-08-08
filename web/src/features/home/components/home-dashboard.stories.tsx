import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, within } from "storybook/test";

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
