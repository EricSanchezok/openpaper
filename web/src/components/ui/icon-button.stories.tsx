import { Plus } from "iconoir-react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Icon } from "@/design-system/icons/icon";
import { IconButton } from "./button";

const meta = {
  title: "Actions/IconButton",
  component: IconButton,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { label: "Add item", variant: "secondary" },
  render: (args) => (
    <IconButton {...args}>
      <Icon glyph={Plus} size={20} />
    </IconButton>
  ),
} satisfies Meta<typeof IconButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="flex gap-3">
      <IconButton label="Add item">
        <Icon glyph={Plus} size={20} tone="inverse" />
      </IconButton>
      <IconButton label="Add item" variant="secondary">
        <Icon glyph={Plus} size={20} />
      </IconButton>
      <IconButton disabled label="Add item" variant="secondary">
        <Icon glyph={Plus} size={20} tone="disabled" />
      </IconButton>
      <IconButton label="Adding item" loading variant="secondary">
        <Icon glyph={Plus} size={20} />
      </IconButton>
    </div>
  ),
};
