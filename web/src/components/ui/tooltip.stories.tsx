import { InfoCircle } from "iconoir-react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Icon } from "@/design-system/icons/icon";
import { IconButton } from "./button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip-popover";

function TooltipDemo() {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <IconButton label="More information" variant="secondary">
            <Icon glyph={InfoCircle} size={20} />
          </IconButton>
        </TooltipTrigger>
        <TooltipContent>More information</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const meta = {
  title: "Overlays/Tooltip",
  component: TooltipDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
} satisfies Meta<typeof TooltipDemo>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Playground: Story = {};
