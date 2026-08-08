import { Plus } from "iconoir-react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

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

export const DisabledPrimary: Story = {
  render: () => (
    <IconButton disabled label="Unavailable action">
      <Icon glyph={Plus} size={20} tone="inverse" />
    </IconButton>
  ),
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", {
      name: "Unavailable action",
    });
    const icon = button.querySelector("svg");
    await expect(button).toBeDisabled();
    await expect(icon).not.toBeNull();
    await expect(getComputedStyle(icon!).color).toBe(
      getComputedStyle(button).color,
    );
  },
};
