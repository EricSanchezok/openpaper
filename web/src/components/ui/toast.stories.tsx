import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Button } from "./button";
import { ToastProvider, useToast } from "./toast";

function ToastDemo() {
  const toast = useToast();
  return (
    <Button
      onClick={() =>
        toast.notify({ title: "Saved", description: "Your changes are ready." })
      }
    >
      Show toast
    </Button>
  );
}

const meta = {
  title: "Feedback/Toast",
  component: ToastDemo,
  tags: ["autodocs"],
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <ToastProvider dismissLabel="Dismiss notification">
        <Story />
      </ToastProvider>
    ),
  ],
} satisfies Meta<typeof ToastDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};
export const MobileLongContent: Story = {
  globals: { viewport: { value: "smallMobile", isRotated: false } },
};
