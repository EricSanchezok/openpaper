import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Database } from "iconoir-react";
import { fn } from "storybook/test";

import { AsyncFeedback } from "./async-feedback";

const meta = {
  title: "Foundation/Async feedback",
  component: AsyncFeedback,
  tags: ["autodocs"],
  args: { action: { label: "Try again", onClick: fn() } },
} satisfies Meta<typeof AsyncFeedback>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Loading: Story = {
  args: { state: "loading", presentation: "block" },
};
export const Empty: Story = {
  args: {
    state: "empty",
    presentation: "block",
    title: "No results",
    description: "Domain-specific copy belongs to the caller.",
    icon: Database,
  },
};
export const Error: Story = { args: { state: "error", presentation: "block" } };
export const Offline: Story = {
  args: { state: "offline", presentation: "block" },
};
export const RetryingInline: Story = {
  args: { state: "retrying", presentation: "inline" },
};
export const Overlay: Story = {
  render: (args) => (
    <div className="bg-surface relative h-80 rounded-[var(--radius-lg)] border p-6">
      <p>Existing content remains in place while feedback overlays it.</p>
      <AsyncFeedback {...args} />
    </div>
  ),
  args: { state: "error", presentation: "overlay" },
};
