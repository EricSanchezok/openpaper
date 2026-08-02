import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, userEvent, within } from "storybook/test";

import {
  Field,
  FieldControl,
  FieldDescription,
  FieldLabel,
  FieldMessage,
} from "./field";
import { Input, PasswordInput } from "./input";
import { Checkbox, Switch } from "./selection-controls";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";

const meta = {
  title: "Forms/Auth controls",
  tags: ["autodocs"],
  parameters: { layout: "centered" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {
  render: () => (
    <div className="component-container w-[min(90vw,26rem)]">
      <Field>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input autoComplete="email" placeholder="name@example.com" />
        </FieldControl>
        <FieldDescription>
          Use the email associated with your account.
        </FieldDescription>
        <FieldMessage />
      </Field>
    </div>
  ),
};

export const AllStates: Story = {
  render: () => (
    <div className="grid w-[min(90vw,28rem)] gap-6">
      <Field>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input defaultValue="eric@example.com" />
        </FieldControl>
        <FieldDescription>Default field</FieldDescription>
        <FieldMessage />
      </Field>
      <Field invalid>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input defaultValue="not-an-email" />
        </FieldControl>
        <FieldDescription />
        <FieldMessage>Enter a valid email address.</FieldMessage>
      </Field>
      <PasswordInput
        aria-label="Password"
        hidePasswordLabel="Hide password"
        placeholder="At least 12 characters"
        showPasswordLabel="Show password"
      />
      <Input disabled value="Unavailable" readOnly />
      <label className="flex min-h-11 items-center gap-3">
        <Checkbox /> Remember me
      </label>
      <label className="flex min-h-11 items-center justify-between gap-3">
        Email updates <Switch />
      </label>
      <Select defaultValue="en">
        <SelectTrigger aria-label="Language">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="en">English</SelectItem>
          <SelectItem value="zh-CN">简体中文</SelectItem>
        </SelectContent>
      </Select>
    </div>
  ),
};

export const PasswordKeyboardInteraction: Story = {
  render: () => (
    <PasswordInput
      defaultValue="twelve-characters"
      hidePasswordLabel="Hide password"
      showPasswordLabel="Show password"
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByDisplayValue("twelve-characters");
    await expect(input).toHaveAttribute("type", "password");
    await userEvent.click(
      canvas.getByRole("button", { name: "Show password" }),
    );
    await expect(input).toHaveAttribute("type", "text");
  },
};

export const SimplifiedChineseLongContent: Story = {
  globals: {
    locale: "zh-CN",
    viewport: { value: "smallMobile", isRotated: false },
  },
  render: () => (
    <div className="w-full max-w-sm">
      <Field invalid>
        <FieldLabel>电子邮箱地址</FieldLabel>
        <FieldControl>
          <Input placeholder="请输入与账户关联的电子邮箱地址" />
        </FieldControl>
        <FieldDescription />
        <FieldMessage>请输入有效的电子邮箱地址后继续。</FieldMessage>
      </Field>
    </div>
  ),
};
