import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { LinkButton } from "./button";

const meta = {
  title: "Actions/LinkButton",
  component: LinkButton,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  args: { children: "Continue", href: "#example", variant: "secondary" },
} satisfies Meta<typeof LinkButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const AllStates: Story = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <LinkButton href="#primary">Primary</LinkButton>
      <LinkButton href="#secondary" variant="secondary">
        Secondary
      </LinkButton>
      <LinkButton href="#ghost" variant="ghost">
        Ghost
      </LinkButton>
      <LinkButton disabled href="#disabled" variant="secondary">
        Disabled
      </LinkButton>
    </div>
  ),
};
