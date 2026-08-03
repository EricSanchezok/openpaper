import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import {
  Field,
  FieldControl,
  FieldDescription,
  FieldLabel,
  FieldMessage,
} from "./field";
import { Input } from "./input";

const meta = {
  title: "Forms/Field",
  component: Field,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { invalid: false },
  decorators: [
    (Story) => (
      <div className="w-[min(90vw,24rem)]">
        <Story />
      </div>
    ),
  ],
  render: (args) => (
    <Field {...args}>
      <FieldLabel>Email</FieldLabel>
      <FieldControl>
        <Input placeholder="name@example.com" />
      </FieldControl>
      <FieldDescription>Use your account email.</FieldDescription>
      <FieldMessage>
        {args.invalid ? "Enter a valid email." : null}
      </FieldMessage>
    </Field>
  ),
} satisfies Meta<typeof Field>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="grid gap-6">
      <Field>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input defaultValue="eric@example.com" />
        </FieldControl>
        <FieldDescription>Default field.</FieldDescription>
      </Field>
      <Field invalid>
        <FieldLabel>Email</FieldLabel>
        <FieldControl>
          <Input defaultValue="invalid" />
        </FieldControl>
        <FieldMessage>Enter a valid email.</FieldMessage>
      </Field>
    </div>
  ),
};
