import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Skeleton } from "./display";

const meta = {
  title: "Feedback/Skeleton",
  component: Skeleton,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { className: "h-11 w-72" },
} satisfies Meta<typeof Skeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid w-72 gap-3">
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-11 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  ),
};
