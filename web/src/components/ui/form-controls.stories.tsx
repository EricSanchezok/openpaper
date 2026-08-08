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
  title: "Examples/Auth control gallery",
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
      <Input
        aria-label="Unavailable field"
        disabled
        value="Unavailable"
        readOnly
      />
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
      aria-label="Password"
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

export const QuietPointerFocus: Story = {
  render: () => (
    <div className="grid w-[min(90vw,26rem)] gap-3">
      <button className="sr-only" type="button">
        Before field
      </button>
      <Field>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input placeholder="name@example.com" />
        </FieldControl>
      </Field>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("textbox", { name: "Email" });
    const restingBorder = getComputedStyle(input).borderColor;

    await userEvent.click(input);
    await expect(input).toHaveAttribute("data-focus-origin", "pointer");
    await expect(input).toHaveStyle({ outlineStyle: "none" });
    await expect(getComputedStyle(input).borderColor).toBe(restingBorder);

    await userEvent.click(canvas.getByRole("button", { name: "Before field" }));
    await userEvent.tab();
    await expect(input).toHaveFocus();
    await expect(input).toHaveAttribute("data-focus-origin", "keyboard");
  },
};

export const QuietPointerFocusDark: Story = {
  ...QuietPointerFocus,
  globals: { appearance: "dark" },
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
