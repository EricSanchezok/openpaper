import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import { PasswordInput } from "./input";

const meta = {
  title: "Forms/PasswordInput",
  component: PasswordInput,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: {
    "aria-label": "Password",
    hidePasswordLabel: "Hide password",
    showPasswordLabel: "Show password",
  },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,24rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof PasswordInput>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: (args) => (
    <div className="grid gap-3">
      <PasswordInput {...args} placeholder="At least 12 characters" />
      <PasswordInput {...args} aria-invalid defaultValue="short" />
      <PasswordInput {...args} disabled value="unavailable" readOnly />
    </div>
  ),
};
export const KeyboardInteraction: Story = {
  args: { defaultValue: "twelve-characters" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByDisplayValue("twelve-characters")).toHaveAttribute(
      "type",
      "text",
    );
  },
};
