import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";

function LanguageSelect({ disabled = false }: { disabled?: boolean }) {
  return (
    <Select defaultValue="en" disabled={disabled}>
      <SelectTrigger aria-label="Language">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="en">English</SelectItem>
        <SelectItem value="zh-CN">简体中文</SelectItem>
      </SelectContent>
    </Select>
  );
}

const meta = {
  title: "Forms/Select",
  component: LanguageSelect,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,20rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof LanguageSelect>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-3">
      <LanguageSelect />
      <LanguageSelect disabled />
    </div>
  ),
};
export const KeyboardInteraction: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("combobox", { name: "Language" });
    await userEvent.click(trigger);
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await expect(trigger).toHaveTextContent("简体中文");
  },
};
