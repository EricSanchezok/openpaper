import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Input } from "./input";

const meta = {
  title: "Forms/Input",
  component: Input,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { placeholder: "name@example.com", type: "email" },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,24rem)]">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-3">
      <Input placeholder="Default" />
      <Input aria-invalid placeholder="Invalid" />
      <Input disabled placeholder="Disabled" />
      <Input aria-label="Read only field" readOnly value="Read only" />
    </div>
  ),
};
export const MobileLongContent: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  args: { placeholder: "请输入与账户关联的电子邮箱地址" },
};
