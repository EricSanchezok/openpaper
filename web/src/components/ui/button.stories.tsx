import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { Button, IconButton, LinkButton } from "./button";

const meta = {
  title: "Actions/Button",
  component: Button,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { children: "Continue", onClick: fn() },
  argTypes: {
    variant: {
      control: "select",
      options: ["primary", "secondary", "ghost", "danger"],
    },
    size: { control: "select", options: ["sm", "md", "icon", "icon-sm"] },
  },
} satisfies Meta<typeof Button>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const AllStates: Story = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <Button>Default</Button>
      <Button variant="secondary">Secondary</Button>
      <Button variant="ghost">Ghost</Button>
      <Button loading>Submitting</Button>
      <Button disabled>Disabled</Button>
      <IconButton label="Add item">+</IconButton>
      <LinkButton href="#example" variant="secondary">
        Link action
      </LinkButton>
      <LinkButton disabled href="#disabled" variant="secondary">
        Disabled link
      </LinkButton>
    </div>
  ),
};

export const LoadingPreventsSubmission: Story = {
  args: { loading: true, onClick: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Continue" });
    await expect(button).toBeDisabled();
    await userEvent.click(button);
    await expect(args.onClick).not.toHaveBeenCalled();
  },
};

export const MobileLongContent: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
  render: () => (
    <Button className="w-full">
      Continue securely with this deliberately long translated action
    </Button>
  ),
};
