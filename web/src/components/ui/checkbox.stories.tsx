import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Checkbox } from "./selection-controls";

const meta = {
  title: "Forms/Checkbox",
  component: Checkbox,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { "aria-label": "Remember me" },
} satisfies Meta<typeof Checkbox>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-3">
      <label className="flex min-h-11 items-center gap-3">
        <Checkbox />
        Unchecked
      </label>
      <label className="flex min-h-11 items-center gap-3">
        <Checkbox defaultChecked />
        Checked
      </label>
      <label className="text-muted flex min-h-11 items-center gap-3">
        <Checkbox disabled />
        Disabled
      </label>
    </div>
  ),
};
