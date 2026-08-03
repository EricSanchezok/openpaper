import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Button } from "./button";
import { Popover, PopoverContent, PopoverTrigger } from "./tooltip-popover";

function PopoverDemo() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="secondary">Open popover</Button>
      </PopoverTrigger>
      <PopoverContent>
        Contextual controls remain keyboard accessible.
      </PopoverContent>
    </Popover>
  );
}

const meta = {
  title: "Overlays/Popover",
  component: PopoverDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
} satisfies Meta<typeof PopoverDemo>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Playground: Story = {};
export const Mobile: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};
