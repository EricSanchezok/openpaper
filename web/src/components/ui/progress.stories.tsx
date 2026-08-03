import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Progress } from "./display";

const meta = {
  title: "Feedback/Progress",
  component: Progress,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { "aria-label": "Upload progress", value: 42 },
  decorators: [
    (Story) => (
      <div className="w-[min(80vw,24rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof Progress>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-4">
      <Progress aria-label="Not started" value={0} />
      <Progress aria-label="In progress" value={42} />
      <Progress aria-label="Complete" value={100} />
    </div>
  ),
};
